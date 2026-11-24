from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.operations.liveness import liveness_findings
from graph_scale_dynamics.artifact_store.resume_state import prune_resume_states
from graph_scale_dynamics.domain.cadence import idle_backoff, ticks
from graph_scale_dynamics.operations.artifact_retention import online_retention_tick
from graph_scale_dynamics.operations.maintenance import unless_maintenance
from graph_scale_dynamics.operations import scratch_relief


CHECKPOINT_SWEEP_FLOOR_SECONDS = ticks(1)
CHECKPOINT_SWEEP_CEILING_SECONDS = ticks(75)


def reap_stale_staging(staging_root: Path, active_names: set[str], *,
                       now: float | None = None, minimum_age_seconds: float = 3600.0) -> int:
    import shutil

    current = time.time() if now is None else float(now)
    removed = 0
    for entry in staging_root.glob("*"):
        if entry.name in active_names:
            continue
        try:
            if current - entry.stat().st_mtime <= minimum_age_seconds:
                continue
            if entry.is_symlink() or entry.is_file():
                entry.unlink(missing_ok=True)
            else:
                shutil.rmtree(entry)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--blobs", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--var", default="var")
    parser.add_argument("--poll", type=float, default=ticks(1))
    parser.add_argument("--total-slots", type=int, required=True)
    parser.add_argument("--max-analyzers", type=int, required=True)
    args = parser.parse_args(argv)
    repo = Repo(args.db)
    blobs = BlobStore(args.blobs)
    service = f"maintenance-{os.getpid()}"
    log = Log(args.var, service)
    log.write("start", total_slots=args.total_slots, max_analyzers=args.max_analyzers)
    next_integrity_sample = 0.0
    next_liveness_check = 0.0
    next_evidence_reconciliation = 0.0
    next_stale_analysis_cleanup = 0.0
    next_artifact_retention = 0.0
    next_scratch_relief = 0.0
    scratch_state = None
    scratch_relieving = False
    refused_for_memory_at = None
    scratch_alerts: list | None = None
    retention_cursor: dict = {}
    next_checkpoint_sweep = 0.0
    checkpoint_rest = CHECKPOINT_SWEEP_FLOOR_SECONDS
    try:
        while True:
            if repo.get_flag("paused", "0") == "1":
                repo.heartbeat(service, {"paused": True, "allocation": {"paused": True}})
                repo.wait_for_work(30.0)
                continue
            reclaimed = repo.reclaim_expired()
            if reclaimed:
                log.write("leases_reclaimed", count=reclaimed)
            now = time.monotonic()
            reconciled_evidence = 0
            if now >= next_evidence_reconciliation:
                reconciled_evidence = repo.ensure_candidate_evidence_rebuilds(ANALYSIS_VERSION)
                if reconciled_evidence:
                    log.write("evidence_work_reconciled", rows=reconciled_evidence)
                next_evidence_reconciliation = now + ticks(15)

            if now >= next_stale_analysis_cleanup:
                stale_analysis = repo.cancel_unclaimable_analysis_work()
                if stale_analysis:
                    log.write("stale_analysis_fenced", count=stale_analysis)
                try:
                    pruned = prune_resume_states(repo.conn, blobs.volatile_root)
                    on_disk = prune_resume_states(repo.conn, blobs.root)
                    pruned = {key: pruned[key] + on_disk.get(key, 0) for key in pruned}
                    if pruned["removed"]:
                        log.write("resume_states_pruned", **pruned)
                except Exception as exc:
                    log.write("resume_state_prune_deferred", error=f"{type(exc).__name__}: {exc}"[:300])
                next_stale_analysis_cleanup = now + ticks(8)

            retention_tick = None
            if now >= next_artifact_retention:
                try:
                    sweep_checkpoints = now >= next_checkpoint_sweep
                    with unless_maintenance(repo) as free:
                        retention_tick = (online_retention_tick(repo, blobs, raw_limit=8, checkpoint_limit=16,
                                                                cursor=retention_cursor,
                                                                checkpoints=sweep_checkpoints)
                                          if free else {"deferred": "a backup, a restore or a GC holds the "
                                                                    "maintenance lock"})
                    if sweep_checkpoints:
                        evicted = (retention_tick.get("checkpoint_cleanup") or {}).get(
                            "checkpoint_bodies_evicted")
                        checkpoint_rest = idle_backoff(checkpoint_rest, bool(evicted),
                                                       floor=CHECKPOINT_SWEEP_FLOOR_SECONDS,
                                                       ceiling=CHECKPOINT_SWEEP_CEILING_SECONDS)
                        next_checkpoint_sweep = time.monotonic() + checkpoint_rest
                    if (retention_tick.get("raw_bodies_evicted")
                            or (retention_tick.get("transient_completed_cleanup") or {}).get("evicted")
                            or (retention_tick.get("checkpoint_cleanup") or {}).get("checkpoint_bodies_evicted")
                            or (retention_tick.get("lingering_cleanup") or {}).get("evicted_files_cleaned")
                            or (retention_tick.get("transient_orphan_cleanup") or {}).get("removed")):
                        log.write("artifact_retention", **retention_tick)
                except Exception as exc:
                    log.write("artifact_retention_deferred",
                              error=f"{type(exc).__name__}: {exc}"[:300])
                next_artifact_retention = time.monotonic() + ticks(1)

            if now >= next_scratch_relief:
                try:
                    short = scratch_relief.shortage(repo.conn, refused_for_memory_at)
                    refused_for_memory_at = short["deferred_at"]
                    relief = scratch_relief.relieve(repo, blobs, relieving=scratch_relieving, pressed=short["why"])
                    scratch_relieving = bool(relief.get("relieving"))
                    scratch_state = scratch_relief.brief(relief)
                    if scratch_state["moved_bytes"] or scratch_state["logs_removed"] or scratch_state["refused"]:
                        log.write("scratch_relief", **scratch_state)
                    found = scratch_relief.findings(relief)
                    if [f["key"] for f in found] != scratch_alerts:
                        repo.sync_operational_alerts("scratch", found)
                        scratch_alerts = [f["key"] for f in found]
                    scratch_relief.publish(repo, blobs, relief)
                except Exception as exc:
                    log.write("scratch_relief_deferred", error=f"{type(exc).__name__}: {exc}"[:300])
                next_scratch_relief = time.monotonic() + ticks(1)

            active_raw = repo.get_flag("compute_active_slots")
            active_slots = args.total_slots if active_raw in (None, "") else int(active_raw)
            active_slots = max(0, min(int(args.total_slots), active_slots))
            allocation = repo.refresh_scheduler_state(
                analysis_version=ANALYSIS_VERSION,
                total_slots=active_slots,
                max_analyzers=min(args.max_analyzers, active_slots),
                analysis_weight=float(os.environ.get("GSD_ANALYSIS_WEIGHT", "2.0")),
            )

            staging_root = blobs.staging_root
            now = time.monotonic()
            active_staging = repo.active_staging_names()
            removed_staging = reap_stale_staging(staging_root, active_staging)
            if removed_staging:
                log.write("staging_reclaimed", count=removed_staging)

            if now >= next_liveness_check:
                findings = liveness_findings(
                    repo.conn,
                    queue_age_seconds=int(os.environ.get("GSD_QUEUE_ALERT_SECONDS", "600")),
                    heartbeat_age_seconds=int(os.environ.get("GSD_HEARTBEAT_ALERT_SECONDS", str(int(ticks(24))))),
                    scheduler_age_seconds=int(os.environ.get("GSD_SCHEDULER_ALERT_SECONDS", str(int(ticks(8))))),
                )
                repo.sync_operational_alerts("liveness", findings)
                if findings:
                    log.write("operational_alerts", count=len(findings),
                              keys=[finding["key"] for finding in findings])
                next_liveness_check = now + ticks(4)

            if now >= next_integrity_sample:
                rows = repo.conn.execute(
                    "SELECT a.artifact_hash FROM artifacts a LEFT JOIN artifact_retention ar "
                    "ON ar.artifact_hash=a.artifact_hash "
                    "WHERE COALESCE(ar.body_state,'present')='present' "
                    "ORDER BY RANDOM() LIMIT 3"
                ).fetchall()
                for row in rows:
                    artifact = row["artifact_hash"]
                    if not blobs.verify(artifact):
                        base = {"artifact": artifact,
                                "error": "content hash verification failed"}
                        contexts = repo.job_contexts_for_artifact(artifact)
                        if contexts:
                            seen: set[tuple[str, str]] = set()
                            for context in contexts:
                                key = (context["campaign_id"], context["candidate_id"])
                                if key in seen:
                                    continue
                                seen.add(key)
                                repo.emit("integrity_failure", base | context)
                        else:
                            repo.emit("integrity_failure", base)
                        log.write("artifact_corrupt", artifact=artifact,
                                  affected_contexts=len(contexts))
                next_integrity_sample = now + ticks(15)

            active = repo.active_campaigns()
            repo.heartbeat(service, {
                "reclaimed": reclaimed,
                "reconciled_evidence": reconciled_evidence,
                "active_campaigns": len(active),
                "allocation": allocation,
                "artifact_retention": retention_tick,
                "scratch": scratch_state,
            })
            if not repo.fleet_has_work(ANALYSIS_VERSION):
                log.write("exit", reason="no active campaigns, analysis backlog, or control events remain")
                return 0
            repo.wait_for_work(max(0.1, args.poll))
    finally:
        repo.close()


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
