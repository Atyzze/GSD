from __future__ import annotations

from collections.abc import Callable
import json
import os
import subprocess
import sys
import time

import psutil

from graph_scale_dynamics.operations.process_ownership import owned_env
from graph_scale_dynamics import PROJECT_ROOT
from graph_scale_dynamics.observability.chain_mixing import rung_mixing
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.operations.artifact_retention import evict_analyzed_raw_body
from graph_scale_dynamics.db.repo import Repo, retryable_db_error
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.db.write_outcome import analysis_claim_state, rebuild_landed
from graph_scale_dynamics.domain.model import (
    ATTEMPT_CLASS_MEMORY_FLOOR, ATTEMPT_CLASS_MEMORY_RUNAWAY, analysis_id as make_analysis_id, content_hash)
from graph_scale_dynamics.domain.version import DeploymentProvenanceFence
from graph_scale_dynamics.scaleflow.flow import rung_summary, transition_record
from graph_scale_dynamics.scaleflow.equilibration import rung_certified
from graph_scale_dynamics.measurements.analysis import select_best_runs
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.operations.subprocesses import kill_process_group, process_tree
from graph_scale_dynamics.operations.campaign_control import analysis_stop_reason
from graph_scale_dynamics.operations.memory_giveback import analysis_stop_bytes
from graph_scale_dynamics.domain.cadence import TICK_SECONDS
from graph_scale_dynamics.observability.child_diagnostics import (
    NO_SPACE_CLASS, concise_failure, is_no_space, process_diagnostics)
from graph_scale_dynamics.scheduling.memory import (
    RUNAWAY,
    hard_process_limit_bytes,
    locked_admission,
    memory_shed_reason,
    report_returned_claim,
    returned_on_failure,
    TRANSIENT_MEMORY_BACKOFF_SECONDS,
    predicted_claim_peak_bytes,
    reservation_restatement_is_material,
    settled_reservation_bytes,
    evidence_floor_bytes,
    early_reservation_release_bytes,
    EARLY_RESERVATION_SETTLE_SECONDS,
)
from graph_scale_dynamics.scheduling import fleet_halves

ROOT = PROJECT_ROOT
CURRENT_CHILD: subprocess.Popen | None = None
ANALYSIS_LEASE_SECONDS = max(120, int(os.environ.get("GSD_ANALYSIS_LEASE_SECONDS", "180")))
ANALYSIS_LEASE_RENEW_SECONDS = max(20.0, float(os.environ.get("GSD_ANALYSIS_LEASE_RENEW_SECONDS", "60")))
DATABASE_RETRY_SECONDS = 5.0
WRITE_WAIT_SECONDS = float(os.environ.get("GSD_RESULT_COMMIT_WAIT_SECONDS", "600"))


def unless_the_database_is_away(call: Callable[[], object], default=None):
    try:
        return call()
    except DatabaseOperationalError as exc:
        if not exc.transient:
            raise
        return default


def through_the_outage(log: Log, what: str, write: Callable[[], object], *,
                       landed: Callable[[], object] | None = None, keep: Callable[[], object] | None = None,
                       limit: float | None = None, retry_seconds: float | None = None):
    limit = WRITE_WAIT_SECONDS if limit is None else float(limit)
    pause = DATABASE_RETRY_SECONDS if retry_seconds is None else float(retry_seconds)
    started, unknown, said = time.monotonic(), False, False
    while True:
        try:
            if unknown and landed is not None:
                answer = landed()
                if answer is not NOT_LANDED:
                    log.write("analysis_write_read_again", what=what, landed=str(answer)[:120])
                    return answer
                unknown = False
            result = write()
            if said:
                log.write("database_back", what=what, away_seconds=round(time.monotonic() - started, 1))
            return result
        except DatabaseOperationalError as exc:
            if not exc.transient:
                raise
            unknown = unknown or bool(getattr(exc, "outcome_unknown", False))
            if time.monotonic() - started >= limit:
                raise
            if not said:
                said = True
                log.write("database_away", what=what, outcome_unknown=unknown, error=str(exc)[:200])
            if keep is not None and not unknown:
                unless_the_database_is_away(keep)
            time.sleep(pause)


NOT_LANDED = object()


class ClaimThroughAnOutage:
    def __init__(self) -> None:
        self.away_since: float | None = None

    def renew(self, repo: Repo, log: Log, job: dict, owner: str, now: float) -> bool | None:
        try:
            held = bool(repo.renew_analysis_claim(job["campaign_id"], job["result_artifact"], ANALYSIS_VERSION, owner,
                                                  job["analysis_claim_token"], lease_seconds=ANALYSIS_LEASE_SECONDS))
        except DatabaseOperationalError as exc:
            if not exc.transient:
                raise
            if self.away_since is None:
                self.away_since = now
                log.write("database_away", artifact=job["result_artifact"][:16], error=str(exc)[:200])
            return None
        if self.away_since is not None:
            log.write("database_back", artifact=job["result_artifact"][:16],
                      away_seconds=round(now - self.away_since, 1))
            self.away_since = None
        return held


class ClaimWrites:
    def __init__(self, repo: Repo, log: Log, job: dict, owner: str, attempt_id: str) -> None:
        self.repo, self.log, self.owner, self.attempt_id = repo, log, owner, attempt_id
        self.claim = dict(campaign_id=job["campaign_id"], analysis_version=ANALYSIS_VERSION, owner=owner,
                          claim_token=job["analysis_claim_token"])
        self.artifact = job["result_artifact"]

    def _landed(self, read: Callable[[dict | None], object]) -> Callable[[], object]:
        def landed() -> object:
            state = analysis_claim_state(self.repo, self.claim["campaign_id"], self.artifact, ANALYSIS_VERSION,
                                         self.owner, self.claim["claim_token"])
            return NOT_LANDED if state is not None and state["held"] else read(state)
        return landed

    def _positional(self) -> tuple:
        return (self.claim["campaign_id"], self.artifact, ANALYSIS_VERSION, self.owner, self.claim["claim_token"])

    def keep(self) -> object:
        return self.repo.renew_analysis_claim(*self._positional(), lease_seconds=ANALYSIS_LEASE_SECONDS)

    def close(self, **fields) -> None:
        through_the_outage(self.log, "close_analysis_attempt",
                           lambda: self.repo.close_analysis_attempt(self.attempt_id, **fields))

    def commit(self, **fields) -> bool:
        return bool(through_the_outage(
            self.log, "commit_analysis_result",
            lambda: self.repo.commit_analysis_result(input_artifact=self.artifact, **self.claim, **fields),
            landed=self._landed(lambda state: bool(state and state["status"] == "done" and state["measured"])),
            keep=self.keep))

    def release(self) -> bool:
        return bool(through_the_outage(self.log, "release_analysis_claim",
                                       lambda: self.repo.release_analysis_claim(*self._positional()),
                                       landed=self._landed(lambda state: True)))

    def stop_at_boundary(self, *, requeue: bool = False, **fields) -> bool:
        status, error_class = ("queued", ATTEMPT_CLASS_MEMORY_RUNAWAY) if requeue else ("failed", "memory_hard_cap")
        return bool(through_the_outage(
            self.log, "stop_analysis_at_resource_boundary",
            lambda: self.repo.stop_analysis_at_resource_boundary(input_artifact=self.artifact, **self.claim,
                                                                 requeue=requeue, **fields),
            landed=self._landed(lambda state: bool(state and state["status"] == status
                                                   and state["error_class"] == error_class))))

    def fail(self, *, error: str, error_class: str, **fields) -> dict | None:
        def read(state: dict | None) -> dict | None:
            if state is None:
                return None
            if error_class.endswith("no_space_left") and state["status"] == "queued":
                return {"status": "queued", "retry": True, "attempts": 0, "max_attempts": 0}
            if state["status"] in ("queued", "failed") and state["error_class"] == error_class[:100]:
                return {"status": state["status"], "retry": state["status"] == "queued",
                        "attempts": int(state["attempts"] or 0), "max_attempts": int(state["max_attempts"] or 0),
                        "next_attempt_utc": state["next_attempt_utc"], "error_class": error_class,
                        "read_again": True}
            return None
        return through_the_outage(
            self.log, "fail_analysis_claim",
            lambda: self.repo.fail_analysis_claim(*self._positional(), error=error, error_class=error_class, **fields),
            landed=self._landed(read))


def _sample_child_memory_bytes(pid: int) -> dict[str, int]:
    try:
        members = process_tree(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"rss_bytes": 0, "uss_bytes": 0, "pss_bytes": 0, "vms_bytes": 0}
    totals = {"rss_bytes": 0, "uss_bytes": 0, "pss_bytes": 0, "vms_bytes": 0}
    for process in members:
        try:
            info = process.memory_info()
            totals["rss_bytes"] += int(info.rss)
            totals["vms_bytes"] += int(info.vms)
            try:
                full = process.memory_full_info()
                totals["uss_bytes"] += int(getattr(full, "uss", 0) or 0)
                totals["pss_bytes"] += int(getattr(full, "pss", 0) or 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return totals


def _child_rss_bytes(pid: int) -> int:
    return int(_sample_child_memory_bytes(pid)["rss_bytes"])


_DEFAULT_CHILD_RSS_READER = _child_rss_bytes


def _child_memory_bytes(pid: int) -> dict[str, int]:
    sample = _sample_child_memory_bytes(pid)
    if _child_rss_bytes is not _DEFAULT_CHILD_RSS_READER:
        sample["rss_bytes"] = max(0, int(_child_rss_bytes(pid)))
    return sample


def _reservation_observation(peaks: dict[str, int]) -> int:
    return int(peaks.get("pss_bytes") or peaks.get("uss_bytes") or peaks.get("rss_bytes") or 0)


def terminate_current_child() -> None:
    global CURRENT_CHILD
    if CURRENT_CHILD is not None:
        kill_process_group(CURRENT_CHILD)
        CURRENT_CHILD = None


def _rebuild_candidate(repo: Repo, campaign_id: str, candidate_id: str,
                       owner: str, claim_token: str) -> bool:
    last: DatabaseOperationalError | None = None
    unknown = False
    for attempt in range(12):
        if unknown:
            try:
                done = rebuild_landed(repo, campaign_id, candidate_id, ANALYSIS_VERSION, owner, claim_token)
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise
                last = exc
                time.sleep(min(1.0, 0.05 * (2 ** attempt)))
                continue
            if done is not None:
                return done
            unknown = False
        revision = repo.conn.execute(
            "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') newest FROM measurements "
            "WHERE campaign_id=? AND candidate_id=? AND analysis_version=?",
            (campaign_id, candidate_id, ANALYSIS_VERSION),
        ).fetchone()
        revision_key = (int(revision["c"]), revision["newest"])
        canonical_measurements = [
            row for row in repo.measurements(candidate_id, ANALYSIS_VERSION, campaign_id)
            if not (((row.get("metrics") or {}).get("health") or {}).get("sampler") or {})
                   .get("sampler_audit", False)
        ]
        measurements = select_best_runs(canonical_measurements)
        by_n: dict[int, list[dict]] = {}
        for measurement in measurements:
            by_n.setdefault(measurement["n"], []).append(measurement["metrics"])
        summaries = {n: rung_summary(metric_list) for n, metric_list in by_n.items()}
        diagnostics = {n: rung_mixing(metric_list) for n, metric_list in by_n.items()}
        transitions: list[tuple[int, int, dict]] = []
        prior = None
        measured_ladder = sorted(int(n) for n in summaries)
        for lo, hi in zip(measured_ladder, measured_ladder[1:], strict=False):
            record = transition_record(lo, summaries[lo], hi, summaries[hi], prior)
            transitions.append((lo, hi, record))
            prior = record
        certified_rungs = {int(n): rung_certified(metric_list)["certified"] is True
                           for n, metric_list in by_n.items()}
        try:
            result = repo.complete_candidate_evidence_rebuild(
                campaign_id=campaign_id, candidate_id=candidate_id,
                analysis_version=ANALYSIS_VERSION, owner=owner,
                claim_token=claim_token, measurement_count=revision_key[0],
                newest_measurement_utc=revision_key[1], summaries=summaries,
                transitions=transitions, certified_rungs=certified_rungs, diagnostics=diagnostics,
            )
            if result == "done":
                return True
            if result == "fenced":
                return False
            time.sleep(0.02)
        except DatabaseOperationalError as exc:
            if not retryable_db_error(exc):
                raise
            last = exc
            unknown = unknown or bool(getattr(exc, "outcome_unknown", False))
            time.sleep(min(1.0, 0.05 * (2 ** attempt)))
    raise DatabaseOperationalError(
        f"candidate evidence rebuild remained busy or changed after retries: {last}"
    )


def _pause_reason(repo: Repo, campaign_id: str, now: float, last_check: float) -> tuple[str | None, float]:
    if now - last_check < TICK_SECONDS:
        return None, last_check
    def asked() -> str | None:
        if repo.get_flag("paused") == "1":
            return "fleet paused"
        return analysis_stop_reason(repo, campaign_id)

    return unless_the_database_is_away(asked), now


ANALYZER_FAULT = "analyzer_fault"


def _handed_back(exc: BaseException) -> bool:
    return isinstance(exc, (OSError, DatabaseOperationalError, DeploymentProvenanceFence)) or is_no_space(exc)


def _fault(exc: BaseException, writes, log: Log, job: dict, attempt_closed: bool, started: float,
           peak_rss_bytes: int, resource: dict) -> tuple[bool, bool]:
    error = f"analyzer fault: {type(exc).__name__}: {exc}"[:500]
    log.write("analyzer_fault", job=job["job_id"][:16], error=error[:300])
    if not attempt_closed:
        writes.close(exit_code=-1, wall_seconds=time.monotonic() - started, peak_rss_bytes=peak_rss_bytes,
                     error=error, error_class=ANALYZER_FAULT, resource=resource)
    payload = {key: job[key] for key in ("job_id", "campaign_id", "candidate_id")} | {"artifact": job["result_artifact"]}
    disposition = writes.fail(error=error, error_class=ANALYZER_FAULT, retryable=True,
                              terminal_topic="analysis_failed", terminal_payload=payload)
    if disposition is None:
        return False, True
    log.write("analysis_failed", job=job["job_id"], error=error[:300], error_class=ANALYZER_FAULT,
              retry=disposition["retry"], attempts=disposition["attempts"], max_attempts=disposition["max_attempts"])
    return True, False


def run_analysis_job(repo: Repo, blobs: BlobStore, log: Log, owner: str,
                     job: dict, *,
                     stop_requested: Callable[[], bool] | None = None) -> bool:
    artifact = job["result_artifact"]
    claim_token = job["analysis_claim_token"]
    token = content_hash({"owner": owner, "campaign": job["campaign_id"],
                          "artifact": artifact, "claim": claim_token})[:24]
    analysis_attempt_id = content_hash({
        "kind": "analysis-attempt", "campaign": job["campaign_id"],
        "artifact": artifact, "analysis_version": ANALYSIS_VERSION,
        "attempt": int(job.get("analysis_attempt_number") or 1), "claim": claim_token,
    })[:24]
    repo.record_analysis_attempt(
        analysis_attempt_id, campaign_id=job["campaign_id"], input_artifact=artifact,
        analysis_version=ANALYSIS_VERSION,
        attempt_number=int(job.get("analysis_attempt_number") or 1),
        owner=owner, claim_token=claim_token,
    )
    staging = blobs.staging_dir("analysis-" + token)
    out_file = staging / "result.json"
    failure_file = staging / "terminal_receipt.json"
    stdout_file = staging / "stdout.log"
    error_file = staging / "stderr.log"
    env = dict(owned_env(), PYTHONPATH=str(ROOT), GSD_CHILD_KIND="analysis",
               GSD_PROJECT_ROOT=str(ROOT),
               GSD_CHILD_N=str(int(job["n"])), GSD_CHILD_CANDIDATE=str(job.get("candidate_id") or "")[:16],
               GSD_CHILD_CAMPAIGN=str(job.get("campaign_id") or "")[:64])
    started = time.monotonic()
    last_renew = last_shed_check = last_pause_check = started
    global CURRENT_CHILD
    stdout_handle = None
    error_handle = None
    child = None
    preempted = False
    preempt_reason: str | None = None
    claim_lost = False
    claim_finalized = False
    error: str | None = None
    failure: dict | None = None
    peaks = {"rss_bytes": 0, "uss_bytes": 0, "pss_bytes": 0, "vms_bytes": 0}
    peak_rss_bytes = 0
    hard_memory_limit, stop_kind = analysis_stop_bytes(repo, job, artifact)
    held_reservation = max(1, int(job.get("memory_reservation_bytes") or 0) or hard_memory_limit)
    early_reservation_checked = False
    attempt_closed = False
    claim, writes = ClaimThroughAnOutage(), ClaimWrites(repo, log, job, owner, analysis_attempt_id)

    def resource_peaks() -> dict:
        return {
            "peak_uss_bytes": int(peaks["uss_bytes"]),
            "peak_pss_bytes": int(peaks["pss_bytes"]),
            "peak_vms_bytes": int(peaks["vms_bytes"]),
        }

    def captured_process(returncode: int | None) -> dict:
        if stdout_handle is not None and not stdout_handle.closed:
            stdout_handle.flush()
            stdout_handle.close()
        if error_handle is not None and not error_handle.closed:
            error_handle.flush()
            error_handle.close()
        return process_diagnostics(
            returncode=returncode, stdout_path=stdout_file, stderr_path=error_file,
            receipt_path=failure_file,
        )

    try:
        stdout_handle = stdout_file.open("wb")
        error_handle = error_file.open("wb")
        child = subprocess.Popen(
            [sys.executable, "-m", "graph_scale_dynamics.services.analyzer.child", str(blobs.root), artifact,
             str(job["seed"]), str(job["n"]), job["job_id"], job["candidate_id"],
             str(job.get("lease_generation", 0)), str(out_file), str(failure_file)],
            cwd=ROOT, env=env, start_new_session=True,
            stdout=stdout_handle, stderr=error_handle,
        )
        CURRENT_CHILD = child
        while True:
            if stop_requested is not None and stop_requested():
                preempted = True
                preempt_reason = "fleet shutdown"
                terminate_current_child()
                code = child.returncode
                log.write("analysis_preempted", artifact=artifact[:16], reason=preempt_reason)
                break
            code = child.poll()
            if code is not None:
                break
            now = time.monotonic()
            sample = _child_memory_bytes(child.pid)
            for key in peaks:
                peaks[key] = max(int(peaks[key]), int(sample.get(key) or 0))
            peak_rss_bytes = int(peaks["rss_bytes"])
            observed_reservation_bytes = _reservation_observation(peaks)
            if (not early_reservation_checked
                    and now - started >= EARLY_RESERVATION_SETTLE_SECONDS):
                early_reservation_checked = True
                early = unless_the_database_is_away(lambda: early_reservation_release_bytes(
                    job.get("spec") or {}, int(job["n"]), "analysis",
                    observed_reservation_bytes, held_reservation,
                    floor_bytes=evidence_floor_bytes(repo.conn, job.get("spec") or {}, int(job["n"]), "analysis"),
                ))
                if early is not None and unless_the_database_is_away(lambda: repo.settle_analysis_memory_reservation(
                        job["campaign_id"], artifact, ANALYSIS_VERSION, owner,
                        claim_token, early), default=False):
                    log.write("memory_reservation_early_release",
                              artifact=artifact[:16], n=job["n"],
                              observed_rss_bytes=peak_rss_bytes,
                              observed_pss_bytes=peaks["pss_bytes"],
                              observed_uss_bytes=peaks["uss_bytes"],
                              was_bytes=held_reservation, now_bytes=early)
                    held_reservation = early
            if peak_rss_bytes >= hard_memory_limit:
                wall = time.monotonic() - started
                error = (f"supervised RSS boundary reached ({stop_kind}): observed analyzer process-tree RSS "
                         f"{peak_rss_bytes} bytes >= {hard_memory_limit} bytes")
                terminate_current_child()
                diagnostics = captured_process(child.returncode)
                requeue = stop_kind == RUNAWAY
                writes.close(
                    exit_code=child.returncode if child.returncode is not None else -9,
                    wall_seconds=wall, peak_rss_bytes=peak_rss_bytes, error=error,
                    error_class=ATTEMPT_CLASS_MEMORY_RUNAWAY if requeue else "memory_hard_cap",
                    resource=resource_peaks() | {"process_diagnostics": diagnostics},
                )
                attempt_closed = True
                stopped = writes.stop_at_boundary(
                    peak_rss_bytes=peak_rss_bytes, wall_seconds=wall,
                    hard_limit_bytes=hard_memory_limit, error=error,
                    peak_uss_bytes=peaks["uss_bytes"], peak_pss_bytes=peaks["pss_bytes"], requeue=requeue,
                )
                claim_finalized = bool(stopped)
                claim_lost = not stopped
                log.write(
                    ("analysis_memory_runaway_requeued" if requeue else "analysis_memory_hard_stop")
                    if stopped else "stale_analysis_fenced",
                    artifact=artifact[:16], campaign=job["campaign_id"][:17],
                    candidate=job["candidate_id"][:12], n=job["n"],
                    peak_rss_bytes=peak_rss_bytes, hard_limit_bytes=hard_memory_limit,
                )
                return False
            preempt_reason, last_pause_check = _pause_reason(repo, job["campaign_id"], now, last_pause_check)
            if preempt_reason:
                preempted = True
                terminate_current_child()
                code = child.returncode
                log.write("analysis_preempted", artifact=artifact[:16], reason=preempt_reason)
                break
            if now - last_shed_check >= 2.0:
                last_shed_check = now
                preempt_reason = unless_the_database_is_away(
                    lambda: memory_shed_reason(repo.conn, {"job_id": artifact}, kind="analysis"))
                if preempt_reason:
                    preempted = True
                    terminate_current_child()
                    code = child.returncode
                    log.write("analysis_preempted", artifact=artifact[:16], reason=preempt_reason)
                    break
            if now - last_renew > ANALYSIS_LEASE_RENEW_SECONDS:
                held = claim.renew(repo, log, job, owner, now)
                if held is False:
                    claim_lost = True
                    terminate_current_child()
                    code = child.returncode
                    log.write("stale_analysis_fenced", artifact=artifact[:16], phase="renew")
                    break
                if held is None:
                    last_renew = now - ANALYSIS_LEASE_RENEW_SECONDS + DATABASE_RETRY_SECONDS
                    time.sleep(0.25)
                    continue
                settled = unless_the_database_is_away(lambda: settled_reservation_bytes(
                    job.get("spec") or {}, int(job["n"]), "analysis",
                    observed_reservation_bytes, hard_cap_bytes=hard_memory_limit,
                    floor_bytes=evidence_floor_bytes(repo.conn, job.get("spec") or {}, int(job["n"]), "analysis"),
                ))
                if settled is not None and reservation_restatement_is_material(held_reservation, settled):
                    if unless_the_database_is_away(lambda: repo.settle_analysis_memory_reservation(
                        job["campaign_id"], artifact, ANALYSIS_VERSION, owner,
                        claim_token, settled,
                    ), default=False):
                        log.write("memory_reservation_settled", artifact=artifact[:16],
                                  n=job["n"], observed_rss_bytes=peak_rss_bytes,
                                  observed_pss_bytes=peaks["pss_bytes"],
                                  observed_uss_bytes=peaks["uss_bytes"],
                                  was_bytes=held_reservation, now_bytes=settled)
                        held_reservation = settled
                unless_the_database_is_away(lambda: repo.heartbeat(owner, {
                    "artifact": artifact, "n": job["n"], "elapsed": round(now - started, 1),
                    "rss": int(peaks["rss_bytes"]), "pss": int(peaks["pss_bytes"]),
                    "pss_now": int(sample.get("pss_bytes") or sample.get("rss_bytes") or 0),
                    "analysis_attempt": job.get("analysis_attempt_number")}))
                last_renew = now
            time.sleep(0.25)

        diagnostics = captured_process(code)
        if preempted or claim_lost:
            reason = (f"analysis preempted: {preempt_reason or 'operator request'}"
                      if preempted else "analysis claim lost/fenced")
            writes.close(
                exit_code=code if code is not None else -9,
                wall_seconds=time.monotonic() - started, peak_rss_bytes=peak_rss_bytes,
                error=reason, error_class=((preempt_reason if preempt_reason == ATTEMPT_CLASS_MEMORY_FLOOR
                                            else "preempted") if preempted else "claim_lost"),
                resource=resource_peaks() | {"process_diagnostics": diagnostics},
            )
            attempt_closed = True
            return False
        if (error is None and code == 0 and out_file.exists()
                and diagnostics.get("classification") == "success"):
            payload = json.loads(out_file.read_text())
            if payload.get("runtime_imports"):
                repo.publish_runtime_imports("analyzer-child", names=payload.get("runtime_imports"))
            metrics, curves = payload["metrics"], payload["curves"]
            child_usage = payload.get("resource_usage") or {}
            peaks["rss_bytes"] = max(
                peaks["rss_bytes"], int(child_usage.get("peak_rss_bytes", 0) or 0)
            )
            peak_rss_bytes = int(peaks["rss_bytes"])
            provenance_audit = payload.get("provenance_audit") or {
                "status": "unknown", "detail": "analysis child returned no provenance audit"}
            analysis_provenance = payload.get("analysis_provenance") or {}
            provenance_detail = dict(provenance_audit)
            provenance_detail["analysis"] = analysis_provenance
            provenance_detail["analysis_execution_verified"] = bool(
                analysis_provenance.get("source_execution_verified")
            )
            curves_digest, curves_size = blobs.put_json(curves)
            aid = make_analysis_id(artifact, ANALYSIS_VERSION, {})
            committed = writes.commit(
                curves_digest=curves_digest, curves_size=curves_size,
                producer_job=job["job_id"], analysis_id=aid,
                candidate_id=job["candidate_id"], n=job["n"], seed=job["seed"],
                metrics=metrics,
                wall_seconds=time.monotonic() - started,
                peak_rss_bytes=peak_rss_bytes,
                peak_uss_bytes=peaks["uss_bytes"],
                peak_pss_bytes=peaks["pss_bytes"],
                provenance_status=provenance_audit.get("status", "unknown"),
                provenance_detail=provenance_detail,
            )
            if not committed:
                claim_lost = True
                writes.close(
                    exit_code=0, wall_seconds=time.monotonic() - started,
                    peak_rss_bytes=peak_rss_bytes,
                    error="analysis child succeeded but claim was fenced at commit",
                    error_class="claim_lost",
                    resource=resource_peaks() | {"process_diagnostics": diagnostics},
                )
                attempt_closed = True
                log.write("stale_analysis_fenced", artifact=artifact[:16], phase="commit")
                return False
            writes.close(
                exit_code=0, wall_seconds=time.monotonic() - started,
                peak_rss_bytes=peak_rss_bytes,
                resource=resource_peaks() | {"process_diagnostics": diagnostics},
            )
            attempt_closed = True
            claim_finalized = True
            try:
                retention = evict_analyzed_raw_body(repo, blobs, artifact)
                if retention.get("evicted"):
                    log.write("raw_artifact_evicted", artifact=artifact[:16],
                              bytes_released=retention.get("bytes_released", 0),
                              file_removed=retention.get("file_removed", False))
            except Exception as exc:
                log.write("raw_artifact_eviction_deferred", artifact=artifact[:16],
                          error=f"{type(exc).__name__}: {exc}"[:300])
            log.write("measured", candidate=job["candidate_id"][:12], n=job["n"],
                      seed=job["seed"], dh=(metrics.get("d_V") or {}).get("d_V_window"),
                      ds=(metrics.get("d_s") or {}).get("d_s"),
                      analysis_attempt=job.get("analysis_attempt_number"),
                      peak_rss_bytes=peak_rss_bytes,
                      peak_pss_bytes=peaks["pss_bytes"],
                      peak_uss_bytes=peaks["uss_bytes"],
                      wall=round(time.monotonic() - started, 2))
            return True

        if failure is None and diagnostics.get("classification") != NO_SPACE_CLASS:
            receipt = diagnostics.get("terminal_receipt") or {}
            if receipt.get("status") == "failure":
                failure = receipt
        if failure is None:
            failure = {
                "error_class": f"child_process:{diagnostics.get('classification') or 'unclassified'}",
                "retryable": True,
                "stage": "child_process",
            }
        if error is None:
            if code == 0 and not out_file.exists():
                error = "analysis child returned 0 but produced no result artifact; terminal protocol violated"
            else:
                error = concise_failure(diagnostics)
        error_class = str(failure.get("error_class") or "analysis_failure")
        retryable = bool(failure.get("retryable", False))
        writes.close(
            exit_code=code if code is not None else -1,
            wall_seconds=time.monotonic() - started, peak_rss_bytes=peak_rss_bytes,
            error=error, error_class=error_class,
            resource=resource_peaks() | {"process_diagnostics": diagnostics},
        )
        attempt_closed = True
        if error_class == "deployment_provenance_fence":
            released = writes.release()
            if released:
                claim_finalized = True
                repo.emit("deployment_fenced", {
                    "phase": "analysis",
                    "job_id": job["job_id"],
                    "campaign_id": job["campaign_id"],
                    "candidate_id": job["candidate_id"],
                    "artifact": artifact,
                    "error": error,
                })
                log.write("deployment_fenced", job=job["job_id"][:16],
                          artifact=artifact[:16], error=error[:240])
            else:
                claim_lost = True
                log.write("stale_analysis_fenced", artifact=artifact[:16],
                          phase="deployment_fence")
            raise DeploymentProvenanceFence(error)
        integrity_classes = ("artifact_integrity", "envelope_contract", "provenance")
        terminal_topic = ("integrity_failure" if any(
            error_class.startswith(prefix) for prefix in integrity_classes
        ) else "analysis_failed")
        disposition = writes.fail(
            error=error, error_class=error_class, retryable=retryable,
            terminal_topic=terminal_topic,
            terminal_payload={"job_id": job["job_id"],
                              "campaign_id": job["campaign_id"],
                              "candidate_id": job["candidate_id"],
                              "artifact": artifact},
        )
        if disposition is None:
            claim_lost = True
            log.write("stale_analysis_fenced", artifact=artifact[:16], phase="failure")
            return False
        claim_finalized = True
        log.write("analysis_failed", job=job["job_id"], error=error[:300],
                  error_class=error_class, retry=disposition["retry"],
                  attempts=disposition["attempts"],
                  max_attempts=disposition["max_attempts"],
                  next_attempt_utc=disposition.get("next_attempt_utc"))
        return False
    except Exception as exc:
        if claim_finalized or claim_lost or _handed_back(exc):
            raise
        attempt_closed, claim_finalized, claim_lost = True, *_fault(exc, writes, log, job, attempt_closed, started,
                                                                    peak_rss_bytes, resource_peaks())
        return False
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
            try:
                diagnostics = captured_process(
                    child.returncode if child is not None else None
                )
                repo.close_analysis_attempt(
                    analysis_attempt_id,
                    exit_code=(child.returncode if child is not None and child.returncode is not None else -1),
                    wall_seconds=time.monotonic() - started, peak_rss_bytes=peak_rss_bytes,
                    error="analyzer supervisor exited before attempt finalization",
                    error_class="supervisor_interrupted",
                    resource=resource_peaks() | {"process_diagnostics": diagnostics},
                )
            except Exception:
                pass
        if not claim_finalized and not claim_lost:
            try:
                repo.release_analysis_claim(job["campaign_id"], artifact, ANALYSIS_VERSION,
                                            owner, claim_token)
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise
                log.write("analysis_release_deferred", artifact=artifact[:16],
                          error=str(exc)[:200])
        blobs.clear_staging("analysis-" + token)


def claim_analysis_for_owner(repo: Repo, owner: str) -> dict | None:
    extension = {"min_n": fleet_halves.EXTENSION_FROM_N, "order": "oldest"}
    base = {"max_n": fleet_halves.EXTENSION_FROM_N - 1}
    owed_extension = fleet_halves.extension_first(
        repo.analysis_leased_count(min_n=fleet_halves.EXTENSION_FROM_N), repo.analysis_leased_count())
    for half in ((extension, base) if owed_extension else (base, extension)):
        job = repo.claim_analysis_job(owner, ANALYSIS_VERSION, lease_seconds=ANALYSIS_LEASE_SECONDS, **half)
        if job is not None:
            return job
    return None


def process_new(repo: Repo, blobs: BlobStore, log: Log, owner: str,
                *, max_jobs: int = 1,
                stop_requested: Callable[[], bool] | None = None) -> int:
    if ((stop_requested is not None and stop_requested())
            or repo.get_flag("paused") == "1"):
        return 0
    fresh = 0
    for _ in range(max_jobs):
        if ((stop_requested is not None and stop_requested())
                or repo.get_flag("paused") == "1"):
            break
        job = claim_analysis_for_owner(repo, owner)
        if job is not None:
            retention = (repo.artifact_retention(job["result_artifact"])
                         if hasattr(repo, "artifact_retention") else None)
            if retention and str(retention.get("body_state")) == "transient":
                try:
                    blobs.stat(job["result_artifact"])
                except (FileNotFoundError, OSError, ValueError):
                    replayed = repo.replay_missing_transient_result(
                        campaign_id=job["campaign_id"],
                        artifact_hash=job["result_artifact"],
                        analysis_version=ANALYSIS_VERSION, owner=owner,
                        claim_token=job["analysis_claim_token"],
                    )
                    if replayed:
                        try:
                            repo.emit("transient_artifact_replay_queued", {
                                "job_id": job["job_id"],
                                "campaign_id": job["campaign_id"],
                                "candidate_id": job["candidate_id"],
                                "artifact": job["result_artifact"],
                                "reason": "tmpfs raw body unavailable before analysis",
                            })
                        except DatabaseOperationalError:
                            pass
                        log.write(
                            "transient_artifact_replay_queued",
                            job=job["job_id"][:16], artifact=job["result_artifact"][:16],
                        )
                    else:
                        repo.release_analysis_claim(
                            job["campaign_id"], job["result_artifact"], ANALYSIS_VERSION,
                            owner, job["analysis_claim_token"], defer_seconds=5,
                        )
                    job = None
        if job is not None:
            claimed = job
            with returned_on_failure(
                    lambda: repo.release_analysis_claim(
                        claimed["campaign_id"], claimed["result_artifact"], ANALYSIS_VERSION,
                        owner, claimed["analysis_claim_token"]),
                    report=report_returned_claim(repo, "analysis", artifact=claimed["result_artifact"],
                                                 n=int(claimed["n"]))):
                requested = predicted_claim_peak_bytes(
                    repo.conn, kind="analysis", campaign_id=job["campaign_id"],
                    candidate_id=job["candidate_id"], n=int(job["n"]), spec=job["spec"],
                    producer_job=job.get("job_id"),
                )
                reservation = locked_admission(
                    repo, kind="analysis", reservation_bytes=requested,
                    hard_single_job_bytes=hard_process_limit_bytes(job.get("spec") or {}, n=int(job["n"])),
                    campaign_id=job["campaign_id"], artifact=job["result_artifact"],
                    analysis_version=ANALYSIS_VERSION, owner=owner,
                    claim_token=job["analysis_claim_token"],
                )
            if reservation["within_budget"]:
                job["memory_reservation_bytes"] = int(reservation.get("requested") or 0)
            if not reservation["within_budget"]:
                if reservation.get("permanent"):
                    repo.emit("memory_admission_refused", {
                        "campaign_id": job["campaign_id"],
                        "candidate_id": job["candidate_id"], "n": int(job["n"]),
                        "kind": "analysis", "refusal": reservation.get("refusal"),
                        "requested_bytes": int(reservation.get("requested") or 0),
                        "budget_bytes": int(reservation.get("budget") or 0),
                        "hard_single_job_bytes": int(
                            reservation.get("hard_single_job_bytes") or 0),
                    })
                permanent = bool(reservation.get("permanent"))
                repo.release_analysis_claim(
                    job["campaign_id"], job["result_artifact"], ANALYSIS_VERSION,
                    owner, job["analysis_claim_token"],
                    defer_seconds=(None if permanent else TRANSIENT_MEMORY_BACKOFF_SECONDS),
                )
                if permanent:
                    now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    repo.conn.execute(
                        "UPDATE analysis_queue SET status='failed',error=?,error_class=?,updated_utc=? "
                        "WHERE campaign_id=? AND input_artifact=? "
                        "AND analysis_version=? AND status='queued'",
                        (f"memory admission refused permanently ({reservation.get('refusal')}): predicted "
                         f"{int(reservation.get('predicted') or reservation.get('requested') or 0)} bytes",
                         "refused_at_admission", now_utc, job["campaign_id"],
                         job["result_artifact"], ANALYSIS_VERSION),
                    )
                job = None
        if job is not None and stop_requested is not None and stop_requested():
            repo.release_analysis_claim(
                job["campaign_id"], job["result_artifact"], ANALYSIS_VERSION,
                owner, job["analysis_claim_token"],
            )
            job = None
        if job is None:
            break
        if run_analysis_job(repo, blobs, log, owner, job, stop_requested=stop_requested):
            fresh += 1

    for _ in range(max_jobs):
        if ((stop_requested is not None and stop_requested())
                or repo.get_flag("paused") == "1"):
            break
        rebuild = repo.claim_candidate_evidence_rebuild(
            owner, ANALYSIS_VERSION, lease_seconds=180
        )
        if rebuild is None:
            break
        campaign_id = rebuild["campaign_id"]
        candidate_id = rebuild["candidate_id"]
        token = rebuild["rebuild_claim_token"]
        try:
            campaign = repo.campaign(campaign_id)
            if campaign is None:
                repo.release_candidate_evidence_rebuild(
                    campaign_id, candidate_id, ANALYSIS_VERSION, owner, token,
                    "campaign disappeared before evidence rebuild",
                )
                continue
            if _rebuild_candidate(
                repo, campaign_id, candidate_id, owner, token
            ):
                fresh += 1
        except Exception as exc:
            disposition = repo.fail_candidate_evidence_rebuild(
                campaign_id, candidate_id, ANALYSIS_VERSION, owner, token,
                f"{type(exc).__name__}: {exc}",
            )
            log.write("evidence_rebuild_failed", campaign=campaign_id[:17],
                      candidate=candidate_id[:16], error=str(exc)[:300],
                      retry=None if disposition is None else disposition["retry"])
            if disposition is None:
                raise
    return fresh
