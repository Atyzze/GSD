from __future__ import annotations

from copy import deepcopy
import json
try:
    import resource
except ImportError:  # pragma: no cover
    resource = None

import psutil
import sys
from pathlib import Path

from graph_scale_dynamics.observability.child_diagnostics import enable_fatal_tracebacks, write_terminal_receipt
from graph_scale_dynamics.observability.evidence_sources import runtime_import_snapshot
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.streaming_envelope import publish_envelope_artifacts

from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.domain.version import (
    DeploymentProvenanceFence, verify_environment_fingerprint, verify_runtime_fingerprint,
)
from graph_scale_dynamics.dsl.dsl import fingerprint
from graph_scale_dynamics.services.worker.cpu_speed import chain_moves, cpu_speed
from graph_scale_dynamics.services.worker.engine_registry import engine_sources_digest, resolve_engine

RUN_ENGINE: dict = {}
from graph_scale_dynamics.engine.engine import COMPATIBLE_ENGINE_VERSIONS, ENGINE_VERSION
from graph_scale_dynamics.scaleflow.one_shot import ONE_SHOT_CONTRACT, ONE_SHOT_CONTRACTS, StopRequested, run_one_shot

STOPPED_EXIT_CODE = 75
from graph_scale_dynamics.artifact_store.resume_state import (
    RESUME_MIN_SECONDS, discard_resume_state, let_go_of_its_states, load_resume_state, resume_path, save_resume_state,
    stop_file_for)


def without_the_whole_chunk(state: dict, refused: Exception) -> dict:
    kept = {key: value for key, value in state.items() if key not in ("whole", "whole_envelope")}
    return dict(kept, whole_chunk_left_out=f"{type(refused).__name__}: {refused}"[:200])


def _sweeps_multiplier(job: dict) -> int:
    execution = job.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError("execution must be an object")
    multiplier = execution.get("sweeps_multiplier", 1)
    if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier < 1:
        raise ValueError("execution.sweeps_multiplier must be a positive integer")
    return multiplier


def _run(argv: list[str]) -> int:
    job_file, out_file = argv[0], argv[1]
    with open(job_file, encoding="utf-8") as handle:
        job = json.load(handle)

    expected_engine = job.get("engine_version")
    if expected_engine not in COMPATIBLE_ENGINE_VERSIONS:
        raise ValueError(f"job engine version {expected_engine!r} is not one this worker runs "
                         f"(it runs {ENGINE_VERSION!r})")

    provenance = job.get("execution_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("execution_provenance must be an object")
    expected_source = str(provenance.get("source_fingerprint") or "").strip()
    if not expected_source:
        raise ValueError("execution_provenance.source_fingerprint is required")
    observed_source = verify_runtime_fingerprint(
        expected_source, stage="simulation child start"
    )
    expected_environment = str(provenance.get("environment_fingerprint") or "").strip()
    if not expected_environment:
        raise ValueError("execution_provenance.environment_fingerprint is required")
    observed_environment = verify_environment_fingerprint(
        expected_environment, stage="simulation child start"
    )

    candidate_spec = job["candidate_spec"]
    candidate_fingerprint = fingerprint(candidate_spec)
    if job.get("candidate_id") != candidate_fingerprint:
        raise ValueError("candidate id does not match the canonical specification")

    multiplier = _sweeps_multiplier(job)
    execution = job.get("execution") or {}
    record_points = int(job.get("record_points", 240))
    n = int(job["n"])
    seed = int(job["seed"])
    proposal_locality = float(execution.get("proposal_locality", 0.0))
    one_shot = execution.get("one_shot")
    if not isinstance(one_shot, dict):
        raise ValueError("the job carries no execution.one_shot policy; every simulation job is one-shot")
    if str(one_shot.get("contract")) not in ONE_SHOT_CONTRACTS:
        raise ValueError(f"unsupported one-shot contract {one_shot.get('contract')!r}")
    one_shot = {**one_shot, "contract": ONE_SHOT_CONTRACT}
    execution_spec_hash = content_hash({
        "kind": "simulation-execution-one-shot",
        "candidate_id": candidate_fingerprint,
        "initial_multiplier": multiplier,
        "one_shot": one_shot,
        "proposal_locality": proposal_locality,
        "n": n, "seed": seed, "record_points": record_points,
        "engine_version": ENGINE_VERSION,
        "engine_sources": engine_sources_digest(),
    })
    engine_name, run, engine_fingerprint = resolve_engine(execution)
    state_path = resume_path(job.get("resume_root"), str(job.get("job_id") or ""))
    resume, resume_note = (load_resume_state(state_path, execution_spec_hash=execution_spec_hash)
                           if state_path is not None else (None, "no saved state"))
    disk_path = resume_path(job.get("disk_resume_root"), str(job.get("job_id") or ""))
    disk_copy_kept = []
    if resume is None and disk_path is not None and disk_path.is_file():
        resume, resume_note = load_resume_state(disk_path, execution_spec_hash=execution_spec_hash)
        if resume is None:
            discard_resume_state(disk_path)
        else:
            disk_copy_kept.append(disk_path)
    moves_before = chain_moves((resume or {}).get("checkpoint"))

    def keep_state(state: dict) -> None:
        let_go_of_its_states(resume)
        if state_path is not None and float(state.get("seconds_spent") or 0.0) >= RESUME_MIN_SECONDS:
            try:
                save_resume_state(state_path, state, execution_spec_hash=execution_spec_hash)
            except ValueError as refused:
                save_resume_state(state_path, without_the_whole_chunk(state, refused),
                                  execution_spec_hash=execution_spec_hash)
            while disk_copy_kept:
                discard_resume_state(disk_copy_kept.pop())

    stop_file = str(stop_file_for(job_file))
    try:
        envelope = run_one_shot(
            candidate_spec, n, seed, one_shot=one_shot, initial_multiplier=multiplier,
            record_points=record_points, proposal_locality=proposal_locality,
            engine_contract_version=ENGINE_VERSION, simulate=run,
            resume=resume, on_chunk=keep_state, stop_file=stop_file,
        )
    except StopRequested:
        return STOPPED_EXIT_CODE
    envelope["engine"] = {"name": engine_name, "implementation_fingerprint": engine_fingerprint}
    RUN_ENGINE.update(envelope["engine"])
    if resume is None and resume_note != "no saved state":
        envelope["resume_refused"] = resume_note
    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_scale = 1024 if sys.platform.startswith("linux") else 1
        envelope["resource_usage"] = {
            "source": "getrusage:RUSAGE_SELF",
            "peak_rss_bytes": int(usage.ru_maxrss * rss_scale),
            "user_cpu_seconds": float(usage.ru_utime),
            "system_cpu_seconds": float(usage.ru_stime),
            "cpu_speed": cpu_speed(envelope, moves_before, float(usage.ru_utime) + float(usage.ru_stime)),
        }
    else:  # pragma: no cover
        process = psutil.Process()
        memory = process.memory_info()
        cpu = process.cpu_times()
        envelope["resource_usage"] = {
            "source": "psutil:self",
            "peak_rss_bytes": int(memory.rss),
            "user_cpu_seconds": float(cpu.user),
            "system_cpu_seconds": float(cpu.system),
        }
    envelope["job_id"] = job.get("job_id")
    envelope["candidate_id"] = job.get("candidate_id")
    envelope["candidate_fingerprint"] = candidate_fingerprint
    envelope["declared_sweeps"] = int(candidate_spec["dynamics"]["sweeps"])
    envelope["execution_spec_hash"] = execution_spec_hash
    verify_runtime_fingerprint(expected_source, stage="simulation child completion")
    verified_provenance = deepcopy(provenance)
    verified_provenance.update({
        "source_fingerprint": observed_source,
        "environment_fingerprint": observed_environment,
        "source_execution_verified": True,
        "source_verification_contract": "child-pre-post-1",
    })
    envelope["provenance"] = verified_provenance
    publish_root = job.get("publish_blob_root")
    if publish_root:
        manifest = publish_envelope_artifacts(
            BlobStore(Path(str(publish_root))), envelope,
            expected_n=n, expected_seed=seed, expected_job_id=str(job.get("job_id")),
            expected_candidate_id=str(job.get("candidate_id")), keep_checkpoint=True,
            compresslevel=int(job.get("publish_compresslevel", 1) or 1),
        )
        manifest["runtime_imports"] = runtime_import_snapshot()
        from graph_scale_dynamics.observability.attempt_cost import snapshot as cost_snapshot
        manifest["child_cost"] = cost_snapshot()
        Path(out_file).write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
    else:
        with open(out_file, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        raise ValueError("expected job file, output file, and optional terminal receipt path")
    receipt = Path(argv[2]) if len(argv) == 3 else None
    enable_fatal_tracebacks()
    try:
        code = _run(argv[:2])
    except DeploymentProvenanceFence as exc:
        write_terminal_receipt(
            receipt, status="failure", stage="simulation_child", exc=exc,
            extra={"error_class": "deployment_provenance_fence", "retryable": True},
        )
        raise
    except BaseException as exc:
        write_terminal_receipt(receipt, status="failure", stage="simulation_child", exc=exc)
        raise
    write_terminal_receipt(receipt, status="success", stage="simulation_child",
                           extra={"engine": dict(RUN_ENGINE)} if RUN_ENGINE else None)
    return code


if __name__ == "__main__":
    from graph_scale_dynamics.observability.child_diagnostics import exit_code_of
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(exit_code_of(lambda: main(sys.argv[1:])))
