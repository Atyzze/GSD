from __future__ import annotations

import json
import math
try:
    import resource
except ImportError:  # pragma: no cover
    resource = None
import sys

import psutil
from pathlib import Path

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.envelope import (
    classify_raw_envelope_provenance,
    validate_raw_envelope,
)
from graph_scale_dynamics.measurements.analysis import analyze_envelope
from graph_scale_dynamics.observability.chain_mixing import seed_chain_moments
from graph_scale_dynamics.observability.chains_course import seed_chains_course
from graph_scale_dynamics.observability.meeting_reading import seed_more_meeting_readings, seed_meeting_reading
from graph_scale_dynamics.scaleflow.one_shot import analyze_one_shot_envelope
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.domain.version import (
    BUILD_NUMBER, DeploymentProvenanceFence, environment_fingerprint, runtime_environment,
    runtime_fingerprint, verify_runtime_fingerprint,
)
from graph_scale_dynamics.observability.child_diagnostics import enable_fatal_tracebacks, write_terminal_receipt


def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _failure(path: Path | None, stage: str, exc: BaseException, *, retryable: bool) -> None:
    deployment_fence = isinstance(exc, DeploymentProvenanceFence)
    write_terminal_receipt(
        path, status="failure", stage=stage, exc=exc,
        extra={
            "error_class": ("deployment_provenance_fence" if deployment_fence
                            else f"{stage}:{type(exc).__name__}"),
            "retryable": bool(retryable or deployment_fence),
        },
    )


def main(argv: list[str]) -> int:
    if len(argv) not in (8, 9):
        raise ValueError("expected 8 or 9 analyzer child arguments")
    (blobs_root, artifact, seed, expected_n, expected_job_id, expected_candidate_id,
     expected_lease_generation, out_file, *failure_arg) = argv
    failure_file = Path(failure_arg[0]) if failure_arg else None
    enable_fatal_tracebacks()
    expected_source = runtime_fingerprint()
    try:
        observed_source = verify_runtime_fingerprint(
            expected_source, stage="analysis child start"
        )
    except Exception as exc:
        _failure(failure_file, "analysis_provenance", exc, retryable=False)
        raise

    try:
        envelope = BlobStore(blobs_root).get_json(artifact, verify=True)
    except Exception as exc:
        _failure(failure_file, "artifact_integrity", exc, retryable=False)
        raise
    try:
        validate_raw_envelope(
            envelope,
            expected_n=int(expected_n),
            expected_seed=int(seed),
            expected_job_id=expected_job_id,
            expected_candidate_id=expected_candidate_id,
        )
    except Exception as exc:
        _failure(failure_file, "envelope_contract", exc, retryable=False)
        raise
    try:
        provenance_audit = classify_raw_envelope_provenance(
            envelope, expected_candidate_id=expected_candidate_id,
            expected_lease_generation=int(expected_lease_generation),
        )
    except Exception as exc:
        _failure(failure_file, "provenance", exc, retryable=False)
        raise
    try:
        metrics, curves = analyze_one_shot_envelope(envelope, seed=int(seed), analyzer=analyze_envelope)
        metrics["chain_mixing"] = seed_chain_moments(envelope)
        metrics["meeting_reading"] = seed_meeting_reading(envelope, metrics.get("census"))
        more_readings = seed_more_meeting_readings(envelope, metrics.get("census"))
        if more_readings is not None:
            metrics["more_meeting_readings"] = more_readings
        metrics["chains_course"] = seed_chains_course(envelope)
    except Exception as exc:
        _failure(failure_file, "analysis_exception", exc, retryable=False)
        raise
    try:
        verify_runtime_fingerprint(expected_source, stage="analysis child completion")
        payload = {
            "metrics": metrics,
            "curves": curves,
            "provenance_audit": provenance_audit,
            "analysis_provenance": {
                "build_number": BUILD_NUMBER,
                "analysis_version": ANALYSIS_VERSION,
                "source_fingerprint": observed_source,
                "environment_fingerprint": environment_fingerprint(),
                "environment": runtime_environment(),
                "source_execution_verified": True,
                "source_verification_contract": "child-pre-post-1",
            },
        }
        payload = _json_safe(payload)
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except Exception as exc:
        _failure(failure_file, "payload_contract", exc, retryable=False)
        raise
    try:
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss_scale = 1024 if sys.platform.startswith("linux") else 1
            payload["resource_usage"] = {
                "source": "getrusage:RUSAGE_SELF",
                "peak_rss_bytes": int(usage.ru_maxrss * rss_scale),
            }
        else:  # pragma: no cover
            payload["resource_usage"] = {
                "source": "psutil:self",
                "peak_rss_bytes": int(psutil.Process().memory_info().rss),
            }
        from graph_scale_dynamics.observability.evidence_sources import runtime_import_snapshot
        payload["runtime_imports"] = runtime_import_snapshot()
        Path(out_file).write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except Exception as exc:
        _failure(failure_file, "staging_io", exc, retryable=True)
        raise
    write_terminal_receipt(failure_file, status="success", stage="analysis_child")
    return 0


if __name__ == "__main__":
    from graph_scale_dynamics.observability.child_diagnostics import exit_code_of
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(exit_code_of(lambda: main(sys.argv[1:])))
