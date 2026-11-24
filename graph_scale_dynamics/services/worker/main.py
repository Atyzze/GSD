from __future__ import annotations
from collections.abc import Callable
import json
import os
import random
import subprocess
import sys
import time

import psutil
from pathlib import Path
from graph_scale_dynamics.operations.process_ownership import owned_env
from graph_scale_dynamics import PROJECT_ROOT
from graph_scale_dynamics.db.repo import (
    ATTEMPT_CLASS_FLEET_SHUTDOWN, ATTEMPT_CLASS_LEASE_LOST,
    ATTEMPT_CLASS_MEMORY_HARD_STOP, ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED,
    Repo, retryable_db_error,
)
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.db.write_outcome import job_commit_landed
from graph_scale_dynamics.db.lane_yield import lane_yield_reason, release_defer_seconds
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.envelope import RAW_ENVELOPE_SCHEMA
from graph_scale_dynamics.observability import attempt_cost, oom_evidence
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.domain.version import (
    BUILD_NUMBER, DeploymentProvenanceFence, environment_fingerprint, runtime_environment,
    runtime_fingerprint,
)
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.operations.campaign_control import (
    pause_attempt_class, paused_reason,
)
from graph_scale_dynamics.operations.subprocesses import kill_process_group, process_tree
from graph_scale_dynamics.observability.child_diagnostics import (
    NO_SPACE_CLASS, NO_SPACE_COST_FROM, NO_SPACE_STOP, NO_SPACE_STOP_SECONDS, NO_SPACE_STOP_TEXT, concise_failure,
    is_no_space, process_diagnostics)
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.artifact_store.resume_state import (
    STOP_GRACE_SECONDS, discard_resume_state, resume_path, resume_saved_at, stop_file_for)
from graph_scale_dynamics.scheduling import fleet_halves, memory_hold, work_groups
from graph_scale_dynamics.scheduling.memory import (
    RUNAWAY,
    hard_process_limit_bytes,
    process_stop_bytes,
    locked_admission,
    memory_shed_reason,
    report_returned_claim,
    returned_on_failure,
    TRANSIENT_MEMORY_BACKOFF_SECONDS,
    predicted_claim_peak_bytes,
    evidence_floor_bytes,
    reservation_restatement_is_material,
    settled_reservation_bytes,
    early_reservation_release_bytes,
    EARLY_RESERVATION_SETTLE_SECONDS,
)

ROOT = PROJECT_ROOT


def _process_resources(pid: int) -> dict[str, float | int]:
    totals: dict[str, float | int] = {
        "rss_bytes": 0, "uss_bytes": 0, "pss_bytes": 0, "vms_bytes": 0,
        "user_cpu_seconds": 0.0, "system_cpu_seconds": 0.0,
    }
    try:
        members = process_tree(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return totals
    for process in members:
        try:
            info = process.memory_info()
            totals["rss_bytes"] += int(info.rss)
            totals["vms_bytes"] += int(info.vms)
            try:
                full = process.memory_full_info()
                totals["uss_bytes"] += int(getattr(full, "uss", 0) or 0)
                totals["pss_bytes"] += int(getattr(full, "pss", 0) or 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError):
                pass
            cpu = process.cpu_times()
            totals["user_cpu_seconds"] += float(cpu.user)
            totals["system_cpu_seconds"] += float(cpu.system)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return totals


def _update_peaks(peaks: dict[str, float | int], sample: dict[str, float | int]) -> None:
    for key in ("rss_bytes", "uss_bytes", "pss_bytes", "vms_bytes"):
        peaks[key] = max(int(peaks.get(key, 0)), int(sample.get(key, 0)))
    for key in ("user_cpu_seconds", "system_cpu_seconds"):
        peaks[key] = max(float(peaks.get(key, 0.0)), float(sample.get(key, 0.0)))


COMMITTING = "committing"


def say_committing(repo, log, owner: str, job: dict, generation, wall: float, peak_rss: int) -> None:
    try:
        unless_the_database_is_away(lambda: repo.heartbeat(owner, {
            "job": job["job_id"], "phase": COMMITTING, "lease_generation": generation,
            "elapsed": round(float(wall), 1), "rss": int(peak_rss)}, paced=True))
    except Exception as exc:  # noqa: BLE001
        log.write("committing_unsaid", job=str(job.get("job_id"))[:16], error=f"{type(exc).__name__}: {exc}"[:200])


def _renewal_detail(job: dict, peaks: dict, sample: dict, peak_rss: int, generation, elapsed: float) -> dict:
    now_bytes = int(sample.get("pss_bytes") or sample.get("rss_bytes") or 0)
    peaks.setdefault("pss_timeline", []).append([round(float(elapsed), 1), now_bytes])
    return {"job": job["job_id"], "rss": peak_rss, "pss": int(peaks["pss_bytes"]), "pss_now": now_bytes,
            "lease_generation": generation, "elapsed": round(float(elapsed), 1)}


def _resource_record_from_peaks(peaks: dict[str, float | int]) -> dict:
    return {
        "pss_timeline": list(peaks.get("pss_timeline") or []),
        "sample_interval_seconds": 0.25,
        "peak_uss_bytes": int(peaks.get("uss_bytes", 0)),
        "peak_pss_bytes": int(peaks.get("pss_bytes", 0)),
        "peak_vms_bytes": int(peaks.get("vms_bytes", 0)),
        "user_cpu_seconds": float(peaks.get("user_cpu_seconds", 0.0)),
        "system_cpu_seconds": float(peaks.get("system_cpu_seconds", 0.0)),
    }


def _host_cpu_counters() -> tuple[int, int] | None:
    try:
        with open("/proc/stat", encoding="ascii") as handle:
            fields = [int(value) for value in handle.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    if len(fields) < 5:
        return None
    total = sum(fields[:8])
    idle = fields[3] + fields[4]
    return total - idle, total


def load_context(host_start: tuple[int, int] | None, wall_seconds: float,
                 user_cpu_seconds: float, system_cpu_seconds: float) -> dict:
    context: dict = {"cores": os.cpu_count()}
    end = _host_cpu_counters()
    if host_start is not None and end is not None and end[1] > host_start[1]:
        context["host_busy_percent"] = round(100.0 * (end[0] - host_start[0]) / (end[1] - host_start[1]), 1)
    if wall_seconds and wall_seconds > 0:
        context["cpu_over_wall"] = round((float(user_cpu_seconds) + float(system_cpu_seconds))
                                         / float(wall_seconds), 3)
    return context


def _reservation_observation(peaks: dict[str, float | int]) -> int:
    return int(peaks.get("pss_bytes") or peaks.get("uss_bytes") or peaks.get("rss_bytes") or 0)


def commit_completed_result(repo: Repo, log: Log, *, job: dict, owner: str,
                            generation: int, digest: str, size: int, meta: dict,
                            attempt: dict | None = None, retention: dict | None = None,
                            max_wait_seconds: float | None = None) -> tuple[bool, float]:
    limit = float(max_wait_seconds or os.environ.get("GSD_RESULT_COMMIT_WAIT_SECONDS", "600"))
    started = time.monotonic()
    notice_at = 0.0
    retry_index = 0
    unknown = False
    while True:
        waited = time.monotonic() - started
        payload = dict(meta) | {"result_commit_wait_seconds": round(waited, 3)}
        try:
            if unknown:
                landed = job_commit_landed(repo, job["job_id"], owner, generation, digest)
                if landed is not None:
                    log.write("result_commit_read_again", job=job["job_id"][:16], generation=generation,
                              landed=landed, waited=round(waited, 1))
                    return landed, waited
                unknown = False
            attempt_payload = None
            if attempt is not None:
                attempt_payload = dict(attempt)
                attempt_payload["wall_seconds"] = float(attempt.get("wall_seconds", 0.0)) + waited
            return repo.commit_job_result(
                job_id=job["job_id"], owner=owner, lease_generation=generation,
                digest=digest, size=size, media_type="application/json", meta=payload,
                analysis_version=ANALYSIS_VERSION, attempt=attempt_payload, retention=retention,
            ), waited
        except DatabaseOperationalError as exc:
            if not retryable_db_error(exc):
                raise
            unknown = unknown or bool(getattr(exc, "outcome_unknown", False))
            now = time.monotonic()
            if now - started >= limit:
                raise DatabaseOperationalError(
                    f"completed result could not be published within {limit:.0f}s: {exc}",
                    outcome_unknown=unknown,
                ) from exc
            held = None
            try:
                if not unknown:
                    held = repo.renew_lease(job["job_id"], owner, generation, lease_seconds=300)
            except DatabaseOperationalError as renew_exc:
                if not retryable_db_error(renew_exc):
                    raise
                held = None
                log.write("result_lease_renew_wait", job=job["job_id"][:16],
                          generation=generation, error=str(renew_exc)[:200])
            if held is False:
                return False, now - started
            if now >= notice_at:
                log.write("result_commit_wait", job=job["job_id"][:16],
                          generation=generation, waited=round(now - started, 1),
                          backend=repo.backend, error=str(exc)[:200])
                notice_at = now + 10.0
            delay = min(5.0, 0.1 * (2 ** min(retry_index, 6)))
            time.sleep(delay * (0.75 + 0.5 * random.random()))
            retry_index += 1


def done_and_state_let_go(repo: Repo, blobs: BlobStore, job: dict, digest: str, generation: int,
                          waited: float) -> None:
    repo.begin_transaction()
    try:
        repo.emit("job_done", {"job_id": job["job_id"], "candidate_id": job["candidate_id"],
                               "campaign_id": job["campaign_id"], "artifact": digest,
                               "lease_generation": generation, "result_commit_wait_seconds": round(waited, 3)})
        repo.commit_durably()
    except BaseException:
        repo.conn.rollback_if_open()
        raise
    for root in (blobs.volatile_root, blobs.root):
        discard_resume_state(resume_path(root, str(job["job_id"])))


def simulation_child_payload(job: dict, owner: str, generation: int) -> dict:
    return {
        "job_id": job["job_id"],
        "candidate_id": job["candidate_id"],
        "candidate_spec": job["spec"]["candidate_spec"],
        "engine_version": job["spec"].get("engine_version"),
        "execution": job["spec"].get("execution", {}),
        "n": job["n"],
        "seed": job["seed"],
        "record_points": job["spec"].get("record_points", 240),
        "execution_provenance": {
            "build_number": BUILD_NUMBER,
            "source_fingerprint": runtime_fingerprint(),
            "environment_fingerprint": environment_fingerprint(),
            "environment": runtime_environment(),
            "lease_generation": generation,
            "worker_owner": owner,
        },
    }


def publication_roots(blobs: BlobStore) -> dict:
    return {"publish_blob_root": str(blobs.root), "publish_compresslevel": 1,
            "resume_root": str(blobs.volatile_root),
            "disk_resume_root": str(blobs.root)}


def run_one(repo: Repo, blobs: BlobStore, log: Log, owner: str, job: dict, *,
            stop_requested: Callable[[], bool] | None = None) -> None:
    generation = int(job["lease_generation"])
    cost_start = attempt_cost.snapshot()
    attempt_id = content_hash({"job": job["job_id"], "attempt": job["attempt_number"],
                               "lease_generation": generation})[:24]
    repo.record_attempt(attempt_id, job["job_id"], job["attempt_number"], owner)
    staging = blobs.staging_dir(attempt_id)
    job_file = staging / "job.json"
    out_file = staging / "result.json"
    stdout_file = staging / "stdout.log"
    error_file = staging / "stderr.log"
    receipt_file = staging / "child_terminal.json"
    child_payload = simulation_child_payload(job, owner, generation)
    child_payload.update(publication_roots(blobs))
    env = dict(owned_env(), PYTHONPATH=str(ROOT), GSD_CHILD_KIND="simulation",
               GSD_PROJECT_ROOT=str(ROOT),
               GSD_CHILD_N=str(int(job["n"])), GSD_CHILD_CANDIDATE=str(job.get("candidate_id") or "")[:16],
               GSD_CHILD_CAMPAIGN=str(job.get("campaign_id") or "")[:64])
    started = time.monotonic()
    host_start = _host_cpu_counters()
    global CURRENT_CHILD
    stdout_handle = None
    error_handle = None
    child = None
    resource_peaks: dict[str, float | int] = {
        "rss_bytes": 0, "uss_bytes": 0, "pss_bytes": 0, "vms_bytes": 0,
        "user_cpu_seconds": 0.0, "system_cpu_seconds": 0.0,
    }
    peak_rss = 0
    hard_memory_limit, stop_kind = process_stop_bytes(job["spec"], int(job["n"]), job.get("memory_reservation_bytes"))
    held_reservation = max(1, int(job.get("memory_reservation_bytes") or 0) or hard_memory_limit)
    last_renew = time.monotonic()
    last_preempt_check = time.monotonic()
    lease = LeaseThroughAnOutage()
    early_reservation_checked = False
    error = failure = None
    attempt_closed = False
    sample: dict = {}

    def captured_resource(returncode: int | None) -> tuple[dict, dict]:
        if stdout_handle is not None and not stdout_handle.closed:
            stdout_handle.flush()
            stdout_handle.close()
        if error_handle is not None and not error_handle.closed:
            error_handle.flush()
            error_handle.close()
        diagnostics = process_diagnostics(
            returncode=returncode, stdout_path=stdout_file, stderr_path=error_file,
            receipt_path=receipt_file,
        )
        resource = _resource_record_from_peaks(resource_peaks)
        resource["process_diagnostics"] = diagnostics
        resource["load_context"] = load_context(
            host_start, time.monotonic() - started,
            resource["user_cpu_seconds"], resource["system_cpu_seconds"])
        return resource, diagnostics

    def interrupted(fallback: str, ended, resource: dict) -> str:
        verdict = oom_evidence.judge(oom_before, pid=child.pid, returncode=child.returncode,
                                     ended_on_its_own=bool(ended), peak_rss_bytes=peak_rss,
                                     reservation_bytes=held_reservation)
        resource.update({"oom_evidence": verdict} if verdict else {})
        return oom_evidence.attempt_class(fallback, verdict)

    try:
        job_file.write_text(json.dumps(child_payload), encoding="utf-8")
        stdout_handle, error_handle = stdout_file.open("wb"), error_file.open("wb")
        work_groups.pin_to_work(repo)
        child = subprocess.Popen(
            [sys.executable, "-m", "graph_scale_dynamics.services.worker.child", str(job_file), str(out_file),
             str(receipt_file)],
            cwd=ROOT, env=env, start_new_session=True,
            stdout=stdout_handle, stderr=error_handle,
        )
        CURRENT_CHILD, oom_before = child, oom_evidence.counters(child.pid)
        pinned = work_groups.Pinned(repo, child.pid)
        while True:
            pinned.keep()
            if stop_requested is not None and stop_requested():
                ended = stop_current_child(staging)
                if child.returncode == 0:
                    code = 0
                    break
                wall = time.monotonic() - started
                resource, _ = captured_resource(child.returncode)
                repo.close_attempt(
                    attempt_id, child.returncode if child.returncode is not None else -9,
                    peak_rss, wall, "preempted: fleet shutdown", resource,
                    error_class=interrupted(ATTEMPT_CLASS_FLEET_SHUTDOWN, ended, resource),
                )
                attempt_closed = True
                released = repo.release_job(job["job_id"], owner, generation)
                log.write(
                    "job_preempted" if released else "stale_worker_fenced",
                    job=job["job_id"][:16], n=job["n"],
                    campaign=job["campaign_id"][:17], generation=generation,
                    reason="fleet shutdown",
                )
                return
            code = child.poll()
            if code is not None:
                break
            oom_evidence.refresh(oom_before)
            now = time.monotonic()
            if now - last_renew > SIM_LEASE_RENEW_SECONDS:
                held = lease.renew(repo, log, job, owner, generation, now, staging)
                if held is False:
                    ended = child.poll() is not None
                    terminate_current_child()
                    wall = time.monotonic() - started
                    resource, _ = captured_resource(child.returncode)
                    repo.close_attempt(attempt_id, -9, peak_rss, wall,
                                       "lease generation lost before renewal", resource,
                                       error_class=interrupted(ATTEMPT_CLASS_LEASE_LOST, ended, resource))
                    attempt_closed = True
                    log.write("stale_worker_fenced", job=job["job_id"][:16],
                              generation=generation, phase="renew")
                    return
                if held:
                    held_reservation = restate_reservation(repo, log, job, owner, generation, resource_peaks,
                                                           peak_rss, held_reservation, early=False)
                    unless_the_database_is_away(lambda: repo.heartbeat(
                        owner, _renewal_detail(job, resource_peaks, sample, peak_rss, generation, now - started)))
                last_renew = now if held else now - SIM_LEASE_RENEW_SECONDS + DATABASE_RETRY_SECONDS
            if now - last_preempt_check > 2.0:
                last_preempt_check = now
                stop_reason = unless_the_database_is_away(
                    lambda: paused_reason(repo, job.get("campaign_id")) or lane_yield_reason(repo, job))
                stopped = stop_reason is not None
                preempt = None if stopped else unless_the_database_is_away(
                    lambda: repo.preempt_reason(job) or memory_shed_reason(repo.conn, job, saved_at=lambda jid: resume_saved_at(blobs.volatile_root, jid)))
                if stopped or preempt is not None:
                    ended = child.poll() is not None
                    ended = (stop_current_child(staging) if stopped else terminate_current_child()) or ended
                    if child.returncode == 0:
                        code = 0
                        break
                    wall = time.monotonic() - started
                    released = repo.release_job(job["job_id"], owner, generation,
                                                defer_seconds=release_defer_seconds(stop_reason))
                    resource, _ = captured_resource(child.returncode)
                    repo.close_attempt(attempt_id, -9, peak_rss, wall,
                                       f"preempted: {stop_reason or preempt}", resource,
                                       error_class=interrupted(pause_attempt_class(stop_reason) or preempt, ended,
                                                               resource))
                    attempt_closed = True
                    if released:
                        repo.emit("job_preempted", {"job_id": job["job_id"],
                                                    "campaign_id": job["campaign_id"],
                                                    "candidate_id": job["candidate_id"]})
                    log.write("job_preempted" if released else "stale_worker_fenced",
                              job=job["job_id"][:16], n=job["n"],
                              campaign=job["campaign_id"][:17], generation=generation)
                    return
            sample = _process_resources(child.pid)
            _update_peaks(resource_peaks, sample)
            peak_rss = int(resource_peaks["rss_bytes"])
            if (not early_reservation_checked
                    and now - started >= EARLY_RESERVATION_SETTLE_SECONDS):
                early_reservation_checked = True
                held_reservation = restate_reservation(repo, log, job, owner, generation, resource_peaks, peak_rss,
                                                       held_reservation, early=True)
            if peak_rss >= hard_memory_limit:
                wall = time.monotonic() - started
                error = (f"supervised RSS boundary reached ({stop_kind}): observed process-tree RSS "
                         f"{peak_rss} bytes >= {hard_memory_limit} bytes")
                terminate_current_child()
                resource, _ = captured_resource(child.returncode)
                requeue = stop_kind == RUNAWAY
                stopped = repo.stop_job_at_resource_boundary(
                    job_id=job["job_id"], owner=owner, lease_generation=generation,
                    attempt_id=attempt_id, peak_rss_bytes=peak_rss,
                    wall_seconds=wall, hard_limit_bytes=hard_memory_limit,
                    error=error, resource=resource, requeue=requeue,
                )
                if stopped:
                    attempt_closed = True
                else:
                    repo.close_attempt(
                        attempt_id, -9, peak_rss, wall,
                        error + "; lease was already fenced", resource,
                        error_class=ATTEMPT_CLASS_MEMORY_HARD_STOP,
                    )
                    attempt_closed = True
                log.write(
                    ("memory_runaway_requeued" if requeue else "memory_hard_stop") if stopped else "stale_worker_fenced",
                    job=job["job_id"][:16], campaign=job["campaign_id"][:17],
                    candidate=job["candidate_id"][:12], n=job["n"],
                    peak_rss_bytes=peak_rss, hard_limit_bytes=hard_memory_limit,
                    generation=generation,
                )
                return
            time.sleep(0.25)
        wall = time.monotonic() - started
        _, diagnostics = captured_resource(code)
        if (error is None and code == 0 and out_file.exists()
                and diagnostics.get("classification") == "success"):
            say_committing(repo, log, owner, job, generation, wall, peak_rss)
            if out_file.stat().st_size > 4 * 1024 * 1024:
                receipt = {}
            else:
                with out_file.open(encoding="utf-8") as handle:
                    receipt = json.load(handle)
            if receipt.get("runtime_imports"):
                repo.publish_runtime_imports("worker-child", names=receipt.get("runtime_imports"))
            if receipt.get("artifact_manifest_contract") == "simulation-artifact-manifest-v1":
                extracted = receipt
                raw_uncompressed_size = int(receipt.get("raw_uncompressed_size") or 0)
                digest = str(receipt["raw_digest"])
                size = int(receipt.get("raw_size") or 0)
            else:
                raise RuntimeError(
                    "simulation child returned no artifact manifest receipt "
                    f"(got {receipt.get('artifact_manifest_contract')!r})"
                )
            child_usage = extracted.get("resource_usage") or {}
            final = extracted.get("final") or {}
            peak_edges = int(extracted.get("peak_edge_count") or 0)
            peak_rss = max(peak_rss, int(child_usage.get("peak_rss_bytes", 0) or 0))
            resource_record = {
                "engine": ((diagnostics.get("terminal_receipt") or {}).get("engine")
                           if isinstance((diagnostics.get("terminal_receipt") or {}).get("engine"), dict)
                           else None),
                "sample_interval_seconds": 0.25, "pss_timeline": list(resource_peaks.get("pss_timeline") or []),
                "supervisor_peak_rss_bytes": int(resource_peaks["rss_bytes"]),
                "child_peak_rss_bytes": int(child_usage.get("peak_rss_bytes", 0) or 0),
                "peak_uss_bytes": int(resource_peaks["uss_bytes"]),
                "peak_pss_bytes": int(resource_peaks["pss_bytes"]),
                "peak_vms_bytes": int(resource_peaks["vms_bytes"]),
                "user_cpu_seconds": float(child_usage.get(
                    "user_cpu_seconds", resource_peaks["user_cpu_seconds"]
                ) or 0.0),
                "system_cpu_seconds": float(child_usage.get(
                    "system_cpu_seconds", resource_peaks["system_cpu_seconds"]
                ) or 0.0),
                "peak_edge_count": peak_edges,
                "final_edge_count": int(final.get("edge_count", 0) or 0),
                "final_mean_degree": float(final.get("mean_degree", 0.0) or 0.0),
                "trajectory_diagnostics": extracted.get("trajectory_diagnostics") or {},
                "process_diagnostics": diagnostics, "cpu_speed": child_usage.get("cpu_speed"),
            }
            resource_record["load_context"] = load_context(
                host_start, wall, resource_record["user_cpu_seconds"],
                resource_record["system_cpu_seconds"])
            compact_digest = str(extracted["compact_digest"])
            compact_size = int(extracted["compact_size"] or 0)
            record_digest, record_size = extracted.get("record_digest"), int(extracted.get("record_size") or 0)
            checkpoint_digest = str(extracted["checkpoint_digest"])
            checkpoint_size = int(extracted["checkpoint_size"] or 0)
            raw_body_state = str(extracted.get("raw_body_state") or "present")
            checkpoint_body_state = str(extracted.get("checkpoint_body_state") or "present")
            raw_encoding = str(extracted.get("raw_encoding") or "gzip-1")
            checkpoint_encoding = str(extracted.get("checkpoint_encoding") or "gzip-1")
            resource_record["artifact_bytes"] = int(size)
            resource_record["artifact_uncompressed_bytes"] = raw_uncompressed_size
            resource_record["artifact_storage_ratio"] = (
                float(size) / raw_uncompressed_size if raw_uncompressed_size else None
            )
            resource_record.update(cost=attempt_cost.record(extracted.get("child_cost"), cost_start),
                                   compact_artifact_bytes=int(compact_size), record_artifact_bytes=record_size)
            resource_record["checkpoint_artifact_bytes"] = int(checkpoint_size)
            resource_record["transient_raw_artifact_bytes"] = (
                int(size) if raw_body_state == "transient" else 0
            )
            resource_record["transient_checkpoint_artifact_bytes"] = (
                int(checkpoint_size) if checkpoint_body_state == "transient" else 0
            )
            resource_record["durable_simulation_artifact_bytes"] = (
                int(compact_size) + record_size
                + (int(checkpoint_size) if checkpoint_body_state == "present" else 0)
                + (int(size) if raw_body_state == "present" else 0)
            )
            resource_record["avoided_raw_durable_write_bytes"] = (
                int(size) if raw_body_state == "transient" else 0
            )
            resource_record["avoided_checkpoint_durable_write_bytes"] = (
                int(checkpoint_size) if checkpoint_body_state == "transient" else 0
            )
            resource_record["avoided_simulation_durable_write_bytes"] = (
                resource_record["avoided_raw_durable_write_bytes"]
                + resource_record["avoided_checkpoint_durable_write_bytes"]
            )
            committed, commit_wait = commit_completed_result(
                repo, log, job=job, owner=owner, generation=generation,
                digest=digest, size=size,
                meta={"schema": RAW_ENVELOPE_SCHEMA, "n": job["n"],
                      "seed": job["seed"], "lease_generation": generation,
                      "storage_encoding": raw_encoding,
                      "storage_tier": ("tmpfs-transient" if raw_body_state == "transient" else "durable"),
                      "sweeps_multiplier": int((job["spec"].get("execution") or {})
                                                .get("sweeps_multiplier", 1)),
                      "build_number": BUILD_NUMBER,
                      "source_fingerprint": runtime_fingerprint(),
                      "environment_fingerprint": environment_fingerprint(),
                      "environment": runtime_environment(),
                      "simulation_wall_seconds": round(wall, 3),
                      "resource_usage": resource_record},
                attempt={
                    "attempt_id": attempt_id, "exit_code": 0,
                    "peak_rss_bytes": peak_rss, "wall_seconds": wall,
                    **resource_record, "resource": resource_record,
                },
                retention={
                    "encoding": raw_encoding,
                    "body_state": raw_body_state,
                    "detail": {
                        "storage_tier": ("tmpfs" if raw_body_state == "transient" else "durable"),
                        "replay_on_transient_loss": bool(raw_body_state == "transient"),
                        "avoided_raw_durable_write_bytes": (int(size) if raw_body_state == "transient" else 0),
                    },
                    "compact": {"digest": compact_digest, "size": compact_size, "encoding": "gzip-1"},
                    **({"record": {"digest": str(record_digest), "size": record_size, "encoding": "xz"}}
                       if record_digest else {}),
                    "checkpoint": {
                        "digest": checkpoint_digest, "size": checkpoint_size,
                        "encoding": checkpoint_encoding, "body_state": checkpoint_body_state,
                        "detail": {
                            "storage_tier": ("tmpfs" if checkpoint_body_state == "transient" else "durable"),
                            "clean_restart_on_transient_loss": bool(checkpoint_body_state == "transient"),
                        },
                    },
                },
            )
            if committed:
                attempt_closed = True
                try:
                    done_and_state_let_go(repo, blobs, job, digest, generation, commit_wait)
                except DatabaseOperationalError as exc:
                    if not retryable_db_error(exc):
                        raise
                    log.write("job_done_event_deferred", job=job["job_id"][:16], error=str(exc)[:200])
                log.write("job_done", job=job["job_id"], n=job["n"], seed=job["seed"],
                          wall=round(wall, 2), commit_wait=round(commit_wait, 2), generation=generation)
            else:
                repo.close_attempt(attempt_id, 0, peak_rss, wall,
                                   "successful child result fenced: lease no longer owned",
                                   resource_record, error_class=ATTEMPT_CLASS_LEASE_LOST)
                attempt_closed = True
                log.write("stale_worker_fenced", job=job["job_id"][:16],
                          generation=generation, phase="commit", artifact=digest[:16])
        else:
            if error is None:
                if code == 0 and not out_file.exists():
                    error = "child returned 0 but produced no result artifact; terminal protocol violated"
                else:
                    error = concise_failure(diagnostics)
            resource_record, diagnostics = captured_resource(code)
            engine_stamp = (diagnostics.get("terminal_receipt") or {}).get("engine")
            if isinstance(engine_stamp, dict):
                resource_record["engine"] = engine_stamp
            receipt = diagnostics.get("terminal_receipt") or {}
            if receipt.get("error_class") == "deployment_provenance_fence":
                released = repo.release_job(job["job_id"], owner, generation)
                repo.close_attempt(
                    attempt_id, code if code is not None else -1, peak_rss, wall,
                    error, resource_record, error_class="provenance_fence",
                )
                attempt_closed = True
                if released:
                    repo.emit("deployment_fenced", {
                        "phase": "simulation",
                        "job_id": job["job_id"],
                        "campaign_id": job["campaign_id"],
                        "candidate_id": job["candidate_id"],
                        "error": error,
                        "lease_generation": generation,
                    })
                    log.write("deployment_fenced", job=job["job_id"][:16],
                              candidate=job["candidate_id"][:12], error=error[:240])
                else:
                    log.write("stale_worker_fenced", job=job["job_id"][:16],
                              generation=generation, phase="deployment_fence")
                raise DeploymentProvenanceFence(error)
            from graph_scale_dynamics.observability.child_diagnostics import (
                failure_class, same_reason_exhausted,
            )
            campaign = repo.campaign(job["campaign_id"])
            reason_class = failure_class(diagnostics)
            prior_classes = repo.job_failure_classes(job["job_id"]) + [reason_class]
            exhausted_class = same_reason_exhausted(prior_classes)
            max_attempts = int(job["spec"].get("max_attempts", 0) or 0)
            count_capped = bool(max_attempts > 0 and job["attempt_number"] >= max_attempts)
            spent_on_space = no_space_seconds(repo, job["job_id"], wall) if reason_class == NO_SPACE_CLASS else 0.0
            space_stop = no_space_stop(prior_classes, reason_class, spent_on_space)
            retry_eligible = bool(campaign and campaign["status"] == "active"
                                  and exhausted_class is None and not count_capped and not space_stop)
            retry = retry_eligible
            if exhausted_class is not None:
                error = f"{error} [stopped: {len(prior_classes)} attempts, third failure with reason {exhausted_class!r}]"
            if space_stop:
                error = f"{error} [stopped: {space_stop}; its output does not fit the scratch]"
            status = ("queued" if retry
                      else ("failed" if campaign and campaign["status"] == "active" else "cancelled"))
            defer, error = no_space_deferral(log, job, prior_classes, reason_class, status, error)
            finished = repo.finish_job(job["job_id"], owner, generation, status, error=error,
                                       spent=reason_class != NO_SPACE_CLASS, defer_seconds=defer)
            repo.close_attempt(attempt_id, code if code is not None else -1, peak_rss, wall,
                               error, resource_record, error_class=reason_class)
            attempt_closed = True
            if finished:
                repo.emit("job_failed", {"job_id": job["job_id"], "campaign_id": job["campaign_id"],
                                         "candidate_id": job["candidate_id"], "retry": retry,
                                         "status": status, "error": error,
                                         "process_classification": diagnostics.get("classification"),
                                         "process_returncode": diagnostics.get("returncode"),
                                         "process_signal": diagnostics.get("signal_name"),
                                         "lease_generation": generation})
                log.write("job_failed", job=job["job_id"], error=error[:200], retry=retry)
            else:
                log.write("stale_worker_fenced", job=job["job_id"][:16],
                          generation=generation, phase="failure")
    except Exception as exc:
        if isinstance(exc, (OSError, DatabaseOperationalError, DeploymentProvenanceFence)) or is_no_space(exc):
            raise
        failure = exc
        log.write("worker_fault", job=job["job_id"][:16], error=f"{type(exc).__name__}: {exc}"[:300])
    finally:
        if stdout_handle is not None and not stdout_handle.closed:
            stdout_handle.close()
        if error_handle is not None and not error_handle.closed:
            error_handle.close()
        if child is not None:
            if child.poll() is None:
                terminate_current_child()
            else:
                child.wait()
        CURRENT_CHILD = None
        if not attempt_closed:
            close_unfinished_attempt(repo, log, job, owner, attempt_id, failure, peak_rss, time.monotonic() - started,
                                     lambda: captured_resource(child.returncode if child is not None else None)[0])
        blobs.clear_staging(attempt_id)


ATTEMPT_CLASS_WORKER_FAULT = "worker_fault"


def close_unfinished_attempt(repo: Repo, log: Log, job: dict, owner: str, attempt_id: str, failure,
                             peak_rss: int, wall: float, resource: Callable[[], dict]) -> None:
    from graph_scale_dynamics.observability.child_diagnostics import same_reason_exhausted
    generation, done = int(job["lease_generation"]), False
    error = f"worker fault: {type(failure).__name__}: {failure}"[:500] if failure is not None else None
    try:
        if failure is None:
            done = repo.release_job(job["job_id"], owner, generation)
        else:
            stop = same_reason_exhausted(repo.job_failure_classes(job["job_id"]) + [ATTEMPT_CLASS_WORKER_FAULT])
            active = (repo.campaign(job["campaign_id"]) or {}).get("status") == "active"
            status = "queued" if active and stop is None else ("failed" if active else "cancelled")
            done = repo.finish_job(job["job_id"], owner, generation, status, error=error, spent=True)
            log.write("job_failed", job=job["job_id"], error=error[:200], retry=status == "queued")
    except Exception as exc:
        log.write("shutdown_release_deferred", job=job["job_id"][:16],
                  generation=generation, error=f"{type(exc).__name__}: {exc}"[:200])
    try:
        repo.close_attempt(
            attempt_id, -1, peak_rss, wall,
            error or ("worker supervisor interrupted; lease released" if done
                      else "worker supervisor exited before attempt close"), resource(),
            error_class=ATTEMPT_CLASS_WORKER_FAULT if failure is not None else ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED,
        )
    except Exception:
        pass


CURRENT_CHILD = None


def stop_current_child(staging: Path, grace: float = STOP_GRACE_SECONDS) -> bool:
    child = CURRENT_CHILD
    if child is None:
        return False
    try:
        stop_file_for(Path(staging) / "job.json").touch()
    except OSError:
        ended = child.poll() is not None
        terminate_current_child()
        return ended
    limit = time.monotonic() + max(0.0, float(grace))
    while child.poll() is None and time.monotonic() < limit:
        time.sleep(0.25)
    ended = child.poll() is not None
    terminate_current_child()
    return ended


def terminate_current_child() -> None:
    global CURRENT_CHILD
    if CURRENT_CHILD is not None:
        kill_process_group(CURRENT_CHILD)
        CURRENT_CHILD = None


SMALL_RUNG_MAX_N = int(os.environ.get("GSD_SMALL_RUNG_MAX_N", "1024"))
SIM_LEASE_SECONDS = max(90, int(os.environ.get("GSD_SIM_LEASE_SECONDS", "180")))
SIM_LEASE_RENEW_SECONDS = max(20.0, float(os.environ.get("GSD_SIM_LEASE_RENEW_SECONDS", "60")))
NO_SPACE_BACKOFF_SECONDS = 60.0
NO_SPACE_BACKOFF_MAX_SECONDS = 3600.0


def no_space_in_a_row(classes: list[str]) -> int:
    count = 0
    for cls in reversed(classes):
        if cls != NO_SPACE_CLASS:
            break
        count += 1
    return count


def no_space_backoff_seconds(in_a_row: int) -> float:
    if in_a_row <= 0:
        return 0.0
    return min(NO_SPACE_BACKOFF_MAX_SECONDS, NO_SPACE_BACKOFF_SECONDS * 2 ** (in_a_row - 1))


def no_space_seconds(repo, job_id: str, this_wall: float) -> float:
    rows = repo.conn.execute(
        "SELECT error_class,wall_seconds FROM attempts WHERE job_id=? AND finished_utc IS NOT NULL "
        "AND error IS NOT NULL ORDER BY started_utc, number", (job_id,)).fetchall()
    total = float(this_wall or 0.0)
    for row in reversed(rows):
        if str(row["error_class"] or "unknown") != NO_SPACE_CLASS:
            break
        total += float(row["wall_seconds"] or 0.0)
    return total


def no_space_stop(prior_classes: list[str], reason_class: str | None, seconds: float = 0.0) -> str:
    in_a_row = no_space_in_a_row(prior_classes) if reason_class == NO_SPACE_CLASS else 0
    if in_a_row >= NO_SPACE_STOP:
        return f"{in_a_row} {NO_SPACE_STOP_TEXT}"
    if in_a_row >= NO_SPACE_COST_FROM and float(seconds or 0.0) >= NO_SPACE_STOP_SECONDS:
        return (f"{in_a_row} {NO_SPACE_STOP_TEXT}, {float(seconds) / 3600:.0f} h of tries, past the "
                f"{NO_SPACE_STOP_SECONDS / 3600:.0f} h bound")
    return ""


def no_space_deferral(log: Log, job: dict, prior_classes: list[str], reason_class: str | None, status: str,
                      error: str) -> tuple[float | None, str]:
    in_a_row = no_space_in_a_row(prior_classes) if reason_class == NO_SPACE_CLASS else 0
    if not in_a_row or status != "queued":
        return None, error
    defer = no_space_backoff_seconds(in_a_row)
    log.write("no_space_backoff", job=job["job_id"][:16], n=job["n"], in_a_row=in_a_row, defer_seconds=defer)
    return defer, f"{error} [no space {in_a_row} time(s) in a row; claimed again in {defer:.0f} s]"


def unless_the_database_is_away(call: Callable[[], object], default=None):
    try:
        return call()
    except DatabaseOperationalError as exc:
        if not exc.transient:
            raise
        return default


def restate_reservation(repo: Repo, log: Log, job: dict, owner: str, generation: int, peaks: dict, peak_rss: int,
                        held: int, *, early: bool) -> int:
    def restated() -> int | None:
        floor = evidence_floor_bytes(repo.conn, job["spec"], job["n"], "simulation")
        observed = _reservation_observation(peaks)
        if early:
            return early_reservation_release_bytes(job["spec"], job["n"], "simulation", observed, held,
                                                   floor_bytes=floor)
        settled = settled_reservation_bytes(job["spec"], job["n"], "simulation", observed, floor_bytes=floor)
        return settled if reservation_restatement_is_material(held, settled) else None

    now_bytes = unless_the_database_is_away(restated)
    if now_bytes is None or not unless_the_database_is_away(
            lambda: repo.settle_memory_reservation(job["job_id"], owner, generation, now_bytes), default=False):
        return held
    log.write("memory_reservation_early_release" if early else "memory_reservation_settled",
              job=job["job_id"][:16], n=job["n"], observed_rss_bytes=peak_rss,
              observed_pss_bytes=int(peaks["pss_bytes"]), observed_uss_bytes=int(peaks["uss_bytes"]),
              was_bytes=held, now_bytes=now_bytes)
    return now_bytes


class LeaseThroughAnOutage:
    def __init__(self) -> None:
        self.until = time.monotonic() + SIM_LEASE_SECONDS
        self.away_since: float | None = None

    def renew(self, repo: Repo, log: Log, job: dict, owner: str, generation: int, now: float,
              staging: Path) -> bool | None:
        try:
            held = bool(repo.renew_lease(job["job_id"], owner, generation, lease_seconds=SIM_LEASE_SECONDS))
        except DatabaseOperationalError as exc:
            if not exc.transient:
                raise
            if self.away_since is None:
                self.away_since = now
                log.write("database_away", job=job["job_id"][:16], error=str(exc)[:200])
            if now >= self.until - LEASE_SAVE_MARGIN_SECONDS:
                stop_current_child(staging)
                raise DatabaseOperationalError(
                    "the lease could not be renewed while the database was away; the child saved its state and the "
                    "lease is left to lapse", transient=True) from exc
            return None
        if self.away_since is not None:
            log.write("database_back", job=job["job_id"][:16], away_seconds=round(now - self.away_since, 1))
            self.away_since = None
        self.until = now + SIM_LEASE_SECONDS
        return held


DATABASE_RETRY_SECONDS = 5.0
LEASE_SAVE_MARGIN_SECONDS = 45.0
SMALL_RESERVED_WORKERS = int(os.environ.get("GSD_SMALL_RESERVED_WORKERS", "2"))

EXTENSION_MIN_N = int(os.environ.get("GSD_EXTENSION_MIN_N", "32768"))
EXTENSION_RESERVED_WORKERS = int(os.environ.get("GSD_EXTENSION_RESERVED_WORKERS", "2"))
LANE_MIN_N = int(os.environ.get("GSD_LANE_MIN_N", "1048576"))
LANE_RESERVED_WORKERS = int(os.environ.get("GSD_LANE_RESERVED_WORKERS", "3"))
EXTENSION_FROM_N = fleet_halves.EXTENSION_FROM_N


def allowed_campaigns(allocation: list[dict], shares: dict | None = None) -> tuple[str, ...] | None:
    if not allocation:
        return ()
    grouped = work_groups.in_shares(allocation, shares or {})
    if grouped is not None:
        found = allowed_campaigns(grouped)
        return tuple(str(row["campaign_id"]) for row in grouped) if found is None else found
    with_work = [row for row in allocation if int(row["queued"] or 0) > 0 and row["workers_target"] != 0]
    if len(with_work) < 2 and all(row["workers_target"] is None for row in allocation):
        return None
    equal = (sum(int(row["leased"] or 0) for row in allocation) + 1) // max(1, len(with_work))
    eligible: list[tuple[int, str]] = []
    for row in allocation:
        target = row["workers_target"]
        campaign_id = str(row["campaign_id"])
        leased = int(row["leased"] or 0)
        queued = int(row["queued"] or 0) > 0
        if target is None:
            eligible.append((max(0, equal - leased) if queued else 0, campaign_id))
        elif leased < int(target):
            behind = int(target) - leased if queued else 0
            eligible.append((behind, campaign_id))
    if not eligible:
        return ()
    furthest = max(behind for behind, _ in eligible)
    if furthest <= 0:
        if all(row["workers_target"] is None for row in allocation):
            return None
        return tuple(campaign_id for _, campaign_id in eligible)
    return tuple(campaign_id for behind, campaign_id in eligible if behind == furthest)


def _claim(repo, owner: str, campaigns: tuple[str, ...] | None, below: int | None, *,
           min_n: int | None = None, max_n: int | None = None, order: str | None = None) -> dict | None:
    if below is not None:
        if min_n is not None and int(min_n) >= int(below):
            return None
        max_n = int(below) - 1 if max_n is None else min(int(max_n), int(below) - 1)
    bounds = {key: value for key, value in (("min_n", min_n), ("max_n", max_n), ("order", order)) if value is not None}
    return repo.claim_job(owner, ("simulate",), lease_seconds=SIM_LEASE_SECONDS, campaigns=campaigns, **bounds)


def _claim_extension(repo, owner: str, campaigns: tuple[str, ...] | None, below: int | None = None) -> dict | None:
    job = None
    if LANE_RESERVED_WORKERS > 0 and repo.leased_count(min_n=LANE_MIN_N) < LANE_RESERVED_WORKERS:
        job = _claim(repo, owner, campaigns, below, min_n=LANE_MIN_N, order="deepest")
    if (job is None and EXTENSION_RESERVED_WORKERS > 0
            and repo.leased_count(min_n=EXTENSION_MIN_N) < EXTENSION_RESERVED_WORKERS):
        job = _claim(repo, owner, campaigns, below, min_n=EXTENSION_MIN_N, order="deepest")
    if job is None:
        job = _claim(repo, owner, campaigns, below, min_n=EXTENSION_FROM_N, max_n=LANE_MIN_N - 1, order="oldest")
    return job


def _claim_base(repo, owner: str, campaigns: tuple[str, ...] | None, below: int | None = None) -> dict | None:
    job = None
    if repo.leased_count(max_n=SMALL_RUNG_MAX_N) < SMALL_RESERVED_WORKERS:
        job = _claim(repo, owner, campaigns, below, max_n=SMALL_RUNG_MAX_N)
    if job is None:
        job = _claim(repo, owner, campaigns, below, max_n=EXTENSION_FROM_N - 1, order="priority_random")
    return job


def _claim_by_reserve(repo, owner: str, campaigns: tuple[str, ...] | None, below: int | None = None) -> dict | None:
    owed_extension = fleet_halves.extension_first(repo.leased_count(min_n=EXTENSION_FROM_N), repo.leased_count())
    job = None
    for half in ((_claim_extension, _claim_base) if owed_extension else (_claim_base, _claim_extension)):
        if job is None:
            job = half(repo, owner, campaigns, below)
    if job is None:
        job = _claim(repo, owner, campaigns, below, min_n=LANE_MIN_N, order="priority_random")
    return job


def claim_simulation_for_owner(repo: Repo, owner: str) -> dict | None:
    campaigns = allowed_campaigns(repo.worker_allocation(claimable=True), work_groups.shares(repo))
    held = memory_hold.active(getattr(repo, "conn", None))
    below = None
    while True:
        job = None
        if held is not None and below is None:
            job = repo.claim_job(owner, ("simulate",), lease_seconds=SIM_LEASE_SECONDS, job_id=str(held["job_id"]))
        for offered in ((campaigns, None) if campaigns else (None,)):
            if job is None:
                job = _claim_by_reserve(repo, owner, offered, below)
        if job is None:
            return None
        if below is not None and int(job["n"]) >= below:
            repo.release_job(job["job_id"], owner, int(job["lease_generation"]))
            return None
        if _admitted(repo, owner, job, held):
            return job
        below = int(job["n"])


def _admitted(repo: Repo, owner: str, job: dict, held: dict | None) -> bool:
    with returned_on_failure(
            lambda: repo.release_job(job["job_id"], owner, int(job["lease_generation"])),
            report=report_returned_claim(repo, "simulation", job_id=job["job_id"], n=int(job["n"]))):
        requested = predicted_claim_peak_bytes(
            repo.conn, kind="simulation", campaign_id=job["campaign_id"],
            candidate_id=job["candidate_id"], n=int(job["n"]), spec=job["spec"],
        )
        hard_cap = hard_process_limit_bytes(job["spec"], n=int(job["n"]))
        reservation = locked_admission(
            repo, kind="simulation", reservation_bytes=requested, hard_single_job_bytes=hard_cap,
            job_id=job["job_id"], owner=owner, lease_generation=int(job["lease_generation"]),
        )
    if not reservation["within_budget"]:
        if reservation.get("permanent"):
            repo.emit("memory_admission_refused", {
                "job_id": job["job_id"], "campaign_id": job["campaign_id"],
                "candidate_id": job["candidate_id"], "n": int(job["n"]),
                "kind": "simulation", "refusal": reservation.get("refusal"),
                "requested_bytes": int(reservation.get("requested") or 0),
                "budget_bytes": int(reservation.get("budget") or 0),
                "hard_single_job_bytes": int(reservation.get("hard_single_job_bytes") or 0),
            })
            repo.finish_job(
                job["job_id"], owner, int(job["lease_generation"]), "failed",
                error=(
                    "memory admission refused permanently ("
                    + str(reservation.get("refusal"))
                    + "): predicted "
                    + str(int(reservation.get("requested") or 0))
                    + " bytes against a "
                    + str(int(reservation.get("hard_single_job_bytes") or 0))
                    + " byte single-job cap"
                ),
            )
        else:
            repo.emit("memory_admission_deferred", {
                "job_id": job["job_id"], "campaign_id": job["campaign_id"],
                "candidate_id": job["candidate_id"], "n": int(job["n"]),
                "requested_bytes": int(reservation.get("requested") or 0),
                "budget_bytes": int(reservation.get("budget") or 0),
                "proposed_bytes": int(reservation.get("proposed_total") or 0),
                "held_bytes": int(reservation.get("held_bytes") or 0),
                "refusal": reservation.get("refusal"),
                "defer_seconds": TRANSIENT_MEMORY_BACKOFF_SECONDS,
            })
            repo.release_job(
                job["job_id"], owner, int(job["lease_generation"]),
                defer_seconds=TRANSIENT_MEMORY_BACKOFF_SECONDS,
            )
            if reservation.get("refusal") in memory_hold.HOLDING_REFUSALS:
                _hold_for_lane(repo, job, int(reservation.get("requested") or 0))
        return False
    job["memory_reservation_bytes"] = int(reservation.get("requested") or 0)
    if held is not None and str(job["job_id"]) == str(held["job_id"]):
        try:
            memory_hold.end(repo.conn, str(job["job_id"]), "admitted")
        except DatabaseOperationalError:
            pass
    return True


def _hold_for_lane(repo, job: dict, requested_bytes: int) -> None:
    if int(job["n"]) < LANE_MIN_N or requested_bytes <= 0:
        return
    try:
        memory_hold.start(repo.conn, job_id=str(job["job_id"]), campaign_id=str(job["campaign_id"]),
                          n=int(job["n"]), requested_bytes=requested_bytes, reach=lambda: memory_hold.reach(repo.conn))
    except DatabaseOperationalError:
        pass
