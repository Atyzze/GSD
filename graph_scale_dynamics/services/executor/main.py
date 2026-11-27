from __future__ import annotations

import argparse
import os
import signal
import threading
import time

from graph_scale_dynamics.observability.child_diagnostics import is_no_space
from graph_scale_dynamics.operations.scratch_relief import room as scratch_room

from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.services.analyzer import main as analyzer
from graph_scale_dynamics.services.worker import main as worker
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.db.repo import Repo, retryable_db_error
from graph_scale_dynamics.db.write_outcome import give_back_unseen_claims
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.domain.version import DEPLOYMENT_FENCE_EXIT_CODE, DeploymentProvenanceFence
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.scheduling import worker_count


_STOP_REQUESTED = threading.Event()
DEPTH_ROLE = worker_count.DEPTH_ROLE


def _terminate_children() -> None:
    worker.terminate_current_child()
    analyzer.terminate_current_child()


def _request_stop(signum, frame) -> None:
    _STOP_REQUESTED.set()


_SCRATCH_NOTED = [0.0]


def _scratch_short(log: Log, kind: str, reason: str | None) -> None:
    now = time.monotonic()
    if now - _SCRATCH_NOTED[0] >= 60.0:
        _SCRATCH_NOTED[0] = now
        log.write("scratch_short", kind=kind, reason=str(reason or "")[:200])


def _run_simulation_once(repo: Repo, blobs: BlobStore, log: Log, owner: str, claim=None) -> bool:
    fits, reason = scratch_room(blobs.volatile_root, kind="simulation")
    if not fits:
        _scratch_short(log, "simulation", reason)
        return False
    job = (claim or worker.claim_simulation_for_owner)(repo, owner)
    if job is None:
        return False
    if _STOP_REQUESTED.is_set():
        repo.release_job(job["job_id"], owner, int(job["lease_generation"]))
        return False
    try:
        worker.run_one(repo, blobs, log, owner, job, stop_requested=_STOP_REQUESTED.is_set)
    except OSError as exc:
        if not is_no_space(exc):
            raise
        repo.release_job(job["job_id"], owner, int(job["lease_generation"]))
        _scratch_short(log, "simulation", f"{type(exc).__name__}: {exc}")
        return False
    return True


def _analysis_once(repo: Repo, blobs: BlobStore, log: Log, owner: str) -> bool:
    fits, reason = scratch_room(blobs.volatile_root, kind="analysis")
    if not fits:
        _scratch_short(log, "analysis", reason)
        return False
    return bool(analyzer.process_new(repo, blobs, log, owner, max_jobs=1, stop_requested=_STOP_REQUESTED.is_set))


def _depth_once(repo: Repo, blobs: BlobStore, log: Log, owner: str) -> bool:
    from graph_scale_dynamics.operations import push
    if push.holds_host(repo) is not None:
        return False
    if _run_simulation_once(repo, blobs, log, owner, claim=worker.claim_depth_for_owner):
        return True
    order = push.order_here(repo)
    if order is None:
        return False
    fits, reason = scratch_room(blobs.volatile_root, kind="analysis")
    if not fits:
        _scratch_short(log, "analysis", reason)
        return False
    return bool(analyzer.process_new(repo, blobs, log, owner, max_jobs=1, stop_requested=_STOP_REQUESTED.is_set,
                                     claim=analyzer.claim_analysis_in(str(order["campaign"]))))


def _depth_slot(repo: Repo) -> int | None:
    getter = getattr(repo, "get_flag", None)
    raw = str(getter(worker_count.MOST_FLAG, "") or "") if callable(getter) else ""
    return int(raw) if raw.isdigit() else None


def _role(snapshot: dict, slot: int, depth_slot: int | None = None) -> str | None:
    if snapshot.get("paused"):
        return None
    if depth_slot is not None and slot == depth_slot:
        return DEPTH_ROLE
    analysis_slots = int(snapshot.get("analysis_slots", 0))
    simulation_slots = int(snapshot.get("simulation_slots", 0))
    if slot < analysis_slots:
        return "analysis"
    if slot < analysis_slots + simulation_slots:
        return "simulation"
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--blobs", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--var", default="var")
    parser.add_argument("--poll", type=float, default=ticks(1))
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--total-slots", type=int, required=True)
    parser.add_argument("--max-analyzers", type=int, required=True)
    args = parser.parse_args(argv)

    _STOP_REQUESTED.clear()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    owner = f"executor-{args.slot}-{os.getpid()}"
    repo = Repo(args.db)
    blobs = BlobStore(args.blobs)
    log = Log(args.var, owner)
    log.write("start", slot=args.slot, total_slots=args.total_slots,
              max_analyzers=args.max_analyzers, analysis_version=ANALYSIS_VERSION)

    unseen = False
    depth_slot = _depth_slot(repo)
    try:
        while not _STOP_REQUESTED.is_set():
            try:
                if unseen:
                    given = give_back_unseen_claims(repo, owner)
                    unseen = False
                    if any(given.values()):
                        log.write("unseen_claims_given_back", **given)
                snapshot = repo.scheduler_snapshot()
                if snapshot is None:
                    repo.wait_for_work(0.5)
                    continue
                role = _role(snapshot, args.slot, depth_slot)
                did_work = False
                detail = {"slot": args.slot, "role": role or "idle",
                          "allocation": snapshot}

                detail["memory_reservation"] = "aggregate-leased-rss"
                if role == "analysis":
                    did_work = _analysis_once(repo, blobs, log, owner)
                    if not did_work and int(snapshot.get("queued_simulations", 0)) > 0:
                        did_work = _run_simulation_once(repo, blobs, log, owner)
                elif role == DEPTH_ROLE:
                    did_work = _depth_once(repo, blobs, log, owner)
                elif role == "simulation":
                    did_work = _run_simulation_once(repo, blobs, log, owner)
                    if not did_work and int(snapshot.get("analysis_backlog", 0)) > 0:
                        did_work = _analysis_once(repo, blobs, log, owner)

                if _STOP_REQUESTED.is_set():
                    break
                repo.heartbeat(owner, detail | {"worked": did_work})
                if not repo.fleet_has_work(ANALYSIS_VERSION):
                    log.write("exit", reason="no active campaigns, analysis backlog, or control events remain")
                    return 0
                if not did_work:
                    repo.wait_for_work(max(0.1, args.poll))
            except DeploymentProvenanceFence as exc:
                log.write("exit", reason="deployment provenance fence", error=str(exc)[:300])
                return DEPLOYMENT_FENCE_EXIT_CODE
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise
                unseen = unseen or bool(getattr(exc, "outcome_unknown", False))
                log.write("database_retry", error=str(exc)[:240], outcome_unknown=bool(unseen))
                time.sleep(0.5)
            except OSError as exc:
                if not is_no_space(exc):
                    raise
                _scratch_short(log, "any", f"{type(exc).__name__}: {exc}")
                time.sleep(max(1.0, args.poll))
    finally:
        _terminate_children()
        repo.close()


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
