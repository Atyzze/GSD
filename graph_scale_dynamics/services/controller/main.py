from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.db.repo import Repo, retryable_db_error
from graph_scale_dynamics.domain.cadence import idle_backoff, ticks
from graph_scale_dynamics.decisions.engine import is_engine_campaign
from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, utc_now
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.operations import auto_extend, focus, study_map
from graph_scale_dynamics.services.controller.engine_campaign import run_engine_campaign

TERMINAL = TERMINAL_CANDIDATE_STATES
IDLE_REST_CEILING_SECONDS = ticks(4)


_FINISHED = {"done", "failed", "cancelled", "lost"}
_DECISION_TABLES = {"jobs", "analysis_queue", "candidate_evidence_rebuilds"}


def decision_relevant(payload: str | None) -> bool:
    try:
        note = json.loads(payload or "{}")
    except ValueError:
        return True
    if not isinstance(note, dict):
        return True
    if note.get("key") == "paused":
        return True
    return note.get("table") in _DECISION_TABLES and note.get("status") in _FINISHED


def campaign_complete(repo: Repo, campaign: dict) -> bool:
    candidates = repo.candidates(campaign["campaign_id"])
    if not candidates or any(candidate["state"] not in TERMINAL for candidate in candidates):
        return False
    return not repo.campaign_pending_work(campaign["campaign_id"])


def _completion(repo: Repo, log: Log, campaign: dict) -> None:
    stored = campaign["spec"]
    campaign_id = str(campaign["campaign_id"])
    if stored.get("mode", "bounded") == "continuous" or not campaign_complete(repo, campaign):
        return
    if auto_extend.holds(repo, campaign_id):
        return
    repo.set_campaign_status(campaign_id, "completed")
    repo.emit("campaign_closed", {"campaign_id": campaign_id, "reason": "all candidates terminal"})
    log.write("campaign_complete", campaign=campaign_id[:17])


def dex_pass(repo: Repo, log: Log, root: Path | None, blobs: Path | None) -> None:
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.operations import dex, dex_check, imports
    if root is None:
        return
    try:
        for found in dex.absorb(repo, root / imports.FOLDER):
            log.write("dex_read_in", bundle=str(found.get("bundle"))[:80], laws=found.get("laws_added"),
                      standing=found.get("laws_standing"), refused=found.get("refused"))
        checked = dex_check.keep(repo, root, blobs=blobs)
        if checked and (checked["checked"] or checked["chosen"] or checked["none"]):
            log.write("dex_checked", checked=checked["checked"], owed=checked["owed"], zone=checked["chosen"],
                      no_zone=checked["none"])
        written = dex.keep(repo, root, blobs=blobs, build=BUILD_NUMBER)
        if written is not None:
            log.write("dex_written", path=str(written), why=str(dex.written(repo).get("why"))[:200])
    except Exception as exc:  # noqa: BLE001
        try:
            repo.conn.rollback_if_open()
        except Exception:  # noqa: BLE001
            pass
        log.write("dex_failed", error=f"{type(exc).__name__}: {exc}"[:400])


def finish_pass(repo: Repo, log: Log, active: list[dict], *, root: Path | None = None,
                blobs: Path | None = None) -> dict | None:
    for campaign in active:
        if is_engine_campaign(campaign["spec"]):
            _completion(repo, log, campaign)
    extended = auto_extend.extend_if_all_finished(repo)
    if extended:
        log.write("study_auto_extended", laws=extended["laws"], campaigns=sorted(extended["campaigns"]))
    mapped = study_map.step(repo)
    if mapped and (mapped["added"] or mapped["entered"]):
        log.write("study_map", added=mapped["added"], entered=mapped["entered"], mapping=mapped["mapping"],
                  known=mapped["known"])
    try:
        focused = focus.step(repo)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        log.write("study_focus_failed", error=f"{type(exc).__name__}: {exc}"[:400])
        focused = None
    if focused and focused["added"]:
        log.write("study_focus", law=focused["label"], stage=focused["stage"], added=focused["added"])
    dex_pass(repo, log, root, blobs)
    return extended


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--blobs")
    parser.add_argument("--var", default="var")
    parser.add_argument("--poll", type=float, default=ticks(1))
    args = parser.parse_args(argv)
    repo = Repo(args.db)
    service = "controller"
    log = Log(args.var, service)
    lock_name = "gsd:controller"
    while not repo.acquire_service_lock(lock_name):
        log.write("standby", reason="another PostgreSQL controller holds the advisory lock")
        repo.wait_for_work(max(1.0, args.poll))
    log.write("start", home=args.campaign, backend=repo.backend)
    from graph_scale_dynamics.operations.study import make_import_folder
    make_import_folder(args.var)
    refused: set[str] = set()
    rest = max(0.1, args.poll)
    wakes = {"notified": 0, "rest_ran_out": 0}
    passes_total = passes_idle = 0
    last_work: dict = {}
    try:
        while True:
            try:
                if repo.get_flag("paused", "0") == "1":
                    repo.heartbeat(service, {"paused": True})
                    repo.wait_for_work(30.0)
                    continue
                active = repo.active_campaigns()
                passes = {}
                started = time.monotonic()
                for campaign in active:
                    campaign_id = str(campaign["campaign_id"])
                    if not is_engine_campaign(campaign["spec"]):
                        if campaign_id not in refused:
                            refused.add(campaign_id)
                            log.write("campaign_refused", campaign=campaign_id[:17],
                                      reason="its spec declares no decision engine, the only mechanism that decides "
                                             "which laws get compute")
                        continue
                    passes[campaign_id] = run_engine_campaign(repo, log, campaign)
                did_work = any(p.get("admitted") or p.get("decisions") for p in passes.values())
                passes_total += 1
                passes_idle += 0 if did_work else 1
                if did_work:
                    last_work = {"utc": utc_now(), "passes": passes}
                rest = idle_backoff(rest, did_work, floor=max(0.1, args.poll),
                                    ceiling=IDLE_REST_CEILING_SECONDS)
                repo.heartbeat(service, {"active_campaigns": len(active), "refused_campaigns": sorted(refused),
                                         "engine_passes": passes,
                                         "pass_seconds": round(time.monotonic() - started, 3),
                                         "rest_seconds": rest, "wakes": dict(wakes),
                                         "passes_total": passes_total, "passes_idle": passes_idle,
                                         "last_working_pass": last_work})
                finish_pass(repo, log, active, root=Path(args.var).resolve().parent,
                            blobs=Path(args.blobs) if args.blobs else None)
                if not repo.fleet_has_work(ANALYSIS_VERSION):
                    log.write("exit", reason="no active campaigns, analysis backlog, or control events remain")
                    return 0
                wakes["notified" if repo.wait_for_work(rest, decision_relevant) else "rest_ran_out"] += 1
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise
                log.write("database_busy", error=str(exc)[:200])
                try:
                    repo.conn.rollback_if_open()
                except Exception:  # noqa: BLE001
                    pass
                repo.wait_for_work(max(1.0, args.poll))
    finally:
        repo.release_service_lock(lock_name)
        repo.close()


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
