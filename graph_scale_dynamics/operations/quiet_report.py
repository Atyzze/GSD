from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import utc_now

QUIET_REPORT_KEY = "report_quiet_bundle_json"
QUIET_REPORT_CONTRACT = "quiet-report-1"

PAUSING, DRAINING, REPORTING, RESUMING, DONE = "pausing", "draining", "reporting", "resuming", "done"
BUNDLING = "bundling"
MAINTAINING = "maintaining"
ACTIVE_STAGES = (PAUSING, DRAINING, REPORTING, MAINTAINING, RESUMING, BUNDLING)

DRAIN_TIMEOUT_SECONDS = ticks(450)
REPORT_TIMEOUT_SECONDS = ticks(5400)
HOLDING_STAGES = (PAUSING, DRAINING, REPORTING, MAINTAINING)
RUNNER_FAILURES_BEFORE_RESUMING = 15
STUDY_SCOPE = "study"
_REPORT_FINISHED = frozenset({"complete", "complete_with_errors", "error", "unchanged"})


def beside_the_push(repo) -> list[str]:
    from graph_scale_dynamics.operations.push_ladder import is_push
    return sorted((str(row["campaign_id"]) for row in repo.active_campaigns() if is_push(row.get("spec") or {})),
                  key=_campaign_order)


def work_in_flight(repo, now: str | None = None, *, beside: list[str] | None = None) -> dict:
    now = now or utc_now()
    left = {str(c) for c in beside or []}
    by_campaign: dict[str, dict[str, int]] = {}
    rows = repo.conn.execute(
        "SELECT campaign_id,kind,COUNT(*) AS c FROM jobs WHERE status='leased' "
        "AND lease_expires_utc>=? GROUP BY campaign_id,kind", (now,)).fetchall()
    for row in rows:
        bucket = by_campaign.setdefault(str(row["campaign_id"]), {})
        bucket[str(row["kind"])] = bucket.get(str(row["kind"]), 0) + int(row["c"] or 0)
    rows = repo.conn.execute(
        "SELECT campaign_id,COUNT(*) AS c FROM analysis_queue WHERE status='leased' "
        "AND lease_expires_utc>=? GROUP BY campaign_id", (now,)).fetchall()
    for row in rows:
        bucket = by_campaign.setdefault(str(row["campaign_id"]), {})
        bucket["analysis_queue"] = bucket.get("analysis_queue", 0) + int(row["c"] or 0)
    running_beside = {cid: kinds for cid, kinds in by_campaign.items() if cid in left}
    by_campaign = {cid: kinds for cid, kinds in by_campaign.items() if cid not in left}
    total = sum(sum(kinds.values()) for kinds in by_campaign.values())
    parts = [f"campaign {cid}: " + ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items()))
             for cid, kinds in sorted(by_campaign.items())]
    return {"total": int(total), "by_campaign": by_campaign, "beside": running_beside,
            "reading": ("nothing is in flight" if not total
                        else f"{total} unit(s) of work in flight ({'; '.join(parts)})")}


def quiet_problem(repo) -> dict | None:
    flight = work_in_flight(repo, beside=beside_the_push(repo))
    if not flight["total"]:
        return None
    return {"error": ("reports run only while no work is in flight, so a cycle never "
                      "shares the host with the chains whose wall-clock it would skew; "
                      + flight["reading"]),
            "in_flight": flight,
            "hint": "pause everything and make the bundle (action 'quiet'): every running "
                    "campaign is paused with its rungs saved, the bundle is made, and "
                    "exactly those campaigns are resumed"}


def state(repo) -> dict | None:
    raw = repo.get_flag(QUIET_REPORT_KEY, "")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def in_progress(repo) -> bool:
    record = state(repo)
    return bool(record) and record.get("stage") in ACTIVE_STAGES


def holding(repo) -> str | None:
    record = state(repo)
    if not record or record.get("stage") not in HOLDING_STAGES or record.get("only"):
        return None
    return (f"a quiet report holds the fleet quiet while its reports run (stage {record['stage']}, request "
            f"{record.get('request_id')}); it resumes the campaigns it paused itself when they are done")


def _save(repo, record: dict) -> dict:
    repo.set_flag(QUIET_REPORT_KEY, json.dumps(record, sort_keys=True))
    return record


def _advance(record: dict, stage: str, note: str) -> dict:
    record["stage"] = stage
    record["stage_utc"] = utc_now()
    record.setdefault("history", []).append({"stage": stage, "utc": record["stage_utc"], "note": note})
    return record


def _age_seconds(stamp: str | None) -> float:
    if not stamp:
        return 0.0
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds())


def _campaign_order(campaign_id: str):
    return (0, int(campaign_id), "") if campaign_id.isdigit() else (1, 0, campaign_id)


def reportable(repo) -> list[str]:
    from graph_scale_dynamics.operations import campaign_control as control
    return sorted((str(row["campaign_id"]) for row in repo.active_campaigns()
                   if control.focus_problem(repo, row) is None), key=_campaign_order)


def start(repo, campaign_id: str | None = None, *, report_base=None, db: str | None = None,
          api_base: str | None = None, only: bool = False) -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    campaign_id = str(campaign_id or "").strip()
    if campaign_id and repo.campaign(campaign_id) is None:
        return {"ok": False, "code": 404, "problem": f"unknown campaign {campaign_id!r}"}
    current = state(repo)
    if current and current.get("stage") in ACTIVE_STAGES:
        return {"ok": False, "code": 409,
                "problem": (f"a quiet report for campaign {current.get('campaign_id')} is already "
                            f"{current.get('stage')}; it resumes the fleet when it finishes")}
    if not (report_base and db):
        return {"ok": False, "code": 409, "problem": ("a report cycle needs the report folder and the database, which "
                                                      "the fleet's API passes; this caller has neither")}
    campaigns = [campaign_id] if only and campaign_id else reportable(repo)
    if not campaigns:
        return {"ok": False, "code": 409,
                "problem": "no campaign to report on: reporting follows an active continuous campaign"}
    beside = beside_the_push(repo)
    running = [] if only else [str(row["campaign_id"]) for row in repo.active_campaigns()
                               if control.derived_state(row) not in (control.PAUSED, control.PAUSING)
                               and str(row["campaign_id"]) not in beside]
    record = {"contract": QUIET_REPORT_CONTRACT, "request_id": uuid.uuid4().hex,
              "campaign_id": campaigns[0], "campaigns": campaigns, "index": 0, "reported": [],
              "selected": campaign_id or None, "report_base": str(report_base) if report_base else None,
              "study_bundle": None, "paused": running, "beside": beside, "resumed": [],
              "started_utc": utc_now(), "report_request_id": None, "error": None,
              "outcome": None,
              "study_run": True, "db": db, "api_base": api_base, "only": bool(only)}
    if only:
        _advance(record, DRAINING, f"one report cycle for campaign {campaigns[0]}, by the study runner")
    else:
        _advance(record, PAUSING, f"pausing {len(running)} running campaign(s)"
                                  + (f", the N-push's campaign {', '.join(beside)} left running" if beside else "")
                                  + f"; then a report cycle for each of {len(campaigns)} campaign(s)")
    return {"ok": True, "code": 202, "state": _save(repo, record)}


def _join(first: str | None, second: str) -> str:
    return f"{first}; {second}" if first else second


def step(repo) -> dict | None:
    from graph_scale_dynamics.operations import campaign_control as control
    record = state(repo)
    if not record or record.get("stage") not in ACTIVE_STAGES:
        return record
    stage = record["stage"]
    if stage == PAUSING:
        failures = []
        for campaign_id in record.get("paused") or []:
            outcome = control.pause(repo, campaign_id, reason="paused for a quiet report bundle")
            if not outcome.get("ok"):
                failures.append(f"{campaign_id}: {outcome.get('problem')}")
        if failures:
            record["error"] = "could not pause " + "; ".join(failures)
            return _save(repo, _advance(record, RESUMING, "a pause was refused; resuming"))
        return _save(repo, _advance(record, DRAINING, "waiting for the chains to save and stop"))
    if stage == DRAINING and record.get("only"):
        return _save(repo, _start_reports(record, ""))
    if stage == DRAINING:
        flight = work_in_flight(repo, beside=record.get("beside") or [])
        record["in_flight"] = flight
        if flight["total"]:
            if _age_seconds(record.get("stage_utc")) > DRAIN_TIMEOUT_SECONDS:
                record["error"] = (f"work still in flight after {DRAIN_TIMEOUT_SECONDS / 60:.0f} "
                                   f"minutes: {flight['reading']}")
                return _save(repo, _advance(record, RESUMING, "gave up waiting; resuming"))
            return _save(repo, record)
        return _save(repo, _start_reports(record, "the fleet is quiet; "))
    if stage == REPORTING:
        return _save(repo, _study_step(record))
    if stage == MAINTAINING:
        if record.get("only"):
            return _save(repo, _advance(record, RESUMING, "one campaign's cycle; nothing paused to resume"))
        record["maintenance"] = maintain(repo, record)
        return _save(repo, _advance(record, RESUMING, record["maintenance"]["note"]))
    if stage == RESUMING:
        resumed, left = [], []
        for campaign_id in record.get("paused") or []:
            outcome = control.resume(repo, campaign_id, reason="resumed after the quiet report bundle")
            (resumed if outcome.get("ok") else left).append(campaign_id)
        record["resumed"] = resumed
        if left:
            record["error"] = _join(record.get("error"), "could not resume " + ", ".join(left))
        if record.get("selected") in (record.get("campaigns") or []):
            control.set_reporting_focus(repo, record["selected"])
        if _bundled(record) and record.get("report_base") and not record.get("only") and not record.get("cancelled"):
            return _save(repo, _advance(record, BUNDLING, f"resumed {len(resumed)} campaign(s); one study "
                                                          f"bundle of {len(_bundled(record))} campaign(s)"))
        record["finished_utc"] = utc_now()
        return _save(repo, _advance(record, DONE, f"resumed {len(resumed)} campaign(s)"))
    if stage == BUNDLING:
        from pathlib import Path

        from graph_scale_dynamics.reporting import study_bundle
        try:
            entry = study_bundle.build(Path(record["report_base"]), repo, record.get("campaigns") or _bundled(record),
                                       request_id=record.get("request_id"), reporting_seconds=_reporting_seconds(record),
                                       finished=_bundled(record), resumed_utc=_resumed_utc(record))
            record["study_bundle"] = {key: entry.get(key) for key in (
                "filename", "svg", "bytes", "built_utc", "study_id", "campaigns", "missing")}
            note = f"study bundle {entry['filename']}"
        except Exception as exc:
            record["error"] = _join(record.get("error"), f"the study bundle failed: {type(exc).__name__}: {exc}")
            note = "the study bundle failed"
        record["finished_utc"] = utc_now()
        return _save(repo, _advance(record, DONE, note))
    return record


def maintain(repo, record: dict) -> dict:
    from pathlib import Path

    from graph_scale_dynamics.operations import failure_repair
    out: dict = {"failures": None, "relief": None, "errors": []}
    started = time.monotonic()
    try:
        repaired = failure_repair.repair(repo)
        out["failures"] = {"lines": failure_repair.render(repaired),
                           **{k: repaired.get(k) for k in ("jobs_requeued", "analyses_requeued", "memory_given_back")},
                           "laws_reinstated": len(repaired.get("laws_reinstated") or [])}
    except Exception as exc:  # noqa: BLE001
        repo.conn.rollback_if_open()
        out["errors"].append(f"repair: {type(exc).__name__}: {str(exc)[:200]}")
    try:
        from graph_scale_dynamics.operations import stranded_laws
        again = stranded_laws.repair(repo)
        out["stranded"] = {"lines": stranded_laws.render(again), "redecided": len(again["redecided"]),
                           "waited": len(again["waited"]), "lasting": len(again["lasting"])}
    except Exception as exc:  # noqa: BLE001
        repo.conn.rollback_if_open()
        out["errors"].append(f"stranded: {type(exc).__name__}: {str(exc)[:200]}")
    base = record.get("report_base")
    if base:
        try:
            from graph_scale_dynamics.artifact_store.blobstore import BlobStore
            from graph_scale_dynamics.operations import scratch_relief
            relief = scratch_relief.relieve(repo, BlobStore(Path(base).parent / "blobs"), at_start=True)
            out["relief"] = scratch_relief.brief(relief)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"relief: {type(exc).__name__}: {str(exc)[:200]}")
    out["seconds"] = round(time.monotonic() - started, 1)
    failures = out["failures"] or {}
    out["note"] = (f"maintenance: {failures.get('laws_reinstated', 0)} law(s) and "
                   f"{failures.get('analyses_requeued', 0) or 0} analysis(es) given back"
                   + (f", {failures['memory_given_back']} of them stopped at the memory ceiling"
                      if failures.get("memory_given_back") else "")
                   + ("; the scratch relieved" if out["relief"] else "")
                   + (f"; {'; '.join(out['errors'])}" if out["errors"] else "") + "; resuming")
    return out


def start_study_run(record: dict) -> str:
    from pathlib import Path

    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations.process_ownership import owned_env, popen_owned
    base = Path(record["report_base"])
    folder = base / "study" / "runs" / str(record["request_id"])
    folder.mkdir(parents=True, exist_ok=True)
    progress = folder / "progress.json"
    campaigns = record.get("campaigns") or [record["campaign_id"]]
    cmd = [sys.executable, "-m", "graph_scale_dynamics.services.reporter.study_run", "--db", str(record["db"]),
           "--base", str(base), "--campaigns", ",".join(campaigns), "--progress", str(progress),
           "--request-id", str(record["request_id"])]
    token = base.parent / "run" / "internal-api-token"
    if record.get("api_base") and token.is_file():
        cmd += ["--api-base", str(record["api_base"]), "--token-file", str(token)]
    if record.get("only"):
        cmd.append("--gentle")
    with open(folder / "runner.log", "ab") as log:
        process = popen_owned(cmd, cwd=str(PROJECT_ROOT), stdout=log, stderr=log, env=owned_env(),
                              start_new_session=True)
    record["study_process"] = {"pid": process.pid, "progress": str(progress), "started_utc": utc_now()}
    if record.get("only"):
        return f"campaign {campaigns[0]}'s report cycle, by the study runner, one report at a time"
    return f"every campaign's report cycle at once ({len(campaigns)}), by the study runner"


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    try:
        return os.waitpid(int(pid), os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def _study_step(record: dict) -> dict:
    from pathlib import Path
    process = record.get("study_process") or {}
    try:
        progress = json.loads(Path(process.get("progress") or "").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        progress = {}
    campaigns = progress.get("campaigns") or {}
    record["study_progress"] = {c: {k: v.get(k) for k in ("state", "stage", "seconds", "report_pool", "started_utc")
                                    if v.get(k) is not None} for c, v in campaigns.items()}
    record["study_layout"] = {k: progress.get(k) for k in ("at_once", "report_workers_each", "why") if k in progress}
    done = {str(r["campaign_id"]) for r in record.get("reported") or []}
    for campaign, entry in campaigns.items():
        if entry.get("state") in _REPORT_FINISHED and campaign not in done:
            outcome = str(entry["state"])
            record.setdefault("reported", []).append({
                "campaign_id": campaign, "outcome": outcome, "finished_utc": utc_now(), "seconds": entry.get("seconds"),
                "error": (entry.get("error") or "the report cycle failed") if outcome == "error" else None})
            if outcome == "error":
                record["error"] = _join(record.get("error"), f"campaign {campaign}: {entry.get('error')}")
    open_ones = [c for c in record.get("campaigns") or [] if c not in {str(r["campaign_id"]) for r in record.get("reported") or []}]
    record["index"] = len(record.get("campaigns") or []) - len(open_ones)
    if open_ones:
        record["campaign_id"] = open_ones[0]
    if progress.get("finished"):
        return _advance(record, MAINTAINING, f"every campaign reported in {progress.get('seconds')} s, "
                                             f"{progress.get('at_once')} at once; the maintenance before resuming")
    if not _alive(process.get("pid")) and _age_seconds(process.get("started_utc")) > 30:
        record["error"] = _join(record.get("error"), "the study runner stopped before every campaign reported: "
                                                     + ", ".join(open_ones))
        return _advance(record, MAINTAINING, "the study runner stopped; the maintenance before resuming")
    if _age_seconds(record.get("stage_utc")) > REPORT_TIMEOUT_SECONDS:
        try:
            os.killpg(int(process.get("pid")), signal.SIGTERM)
        except (OSError, TypeError, ValueError):
            pass
        record["error"] = _join(record.get("error"), f"the study's reports did not finish within "
                                                     f"{REPORT_TIMEOUT_SECONDS / 3600:.0f} hours")
        return _advance(record, MAINTAINING, "report timed out; the maintenance before resuming")
    return record


def _reporting_seconds(record: dict) -> float | None:
    from datetime import datetime
    marks = [(h.get("stage"), h.get("utc")) for h in record.get("history") or []]
    begun = next((utc for stage, utc in marks if stage == REPORTING), None)
    ended = next((utc for stage, utc in marks if begun and utc >= begun and stage not in (REPORTING,)), None)
    try:
        spans = [datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in (begun, ended)]
        return round((spans[1] - spans[0]).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


def _start_reports(record: dict, said: str) -> dict:
    try:
        return _advance(record, REPORTING, said + start_study_run(record))
    except Exception as exc:  # noqa: BLE001
        record["error"] = _join(record.get("error"), f"the study runner could not start: {type(exc).__name__}: {exc}")
        return _advance(record, RESUMING, "the study runner could not start; resuming")


def _resumed_utc(record: dict) -> str | None:
    return next((h.get("utc") for h in reversed(record.get("history") or []) if h.get("stage") == BUNDLING), None)


def _bundled(record: dict) -> list[str]:
    return [str(r["campaign_id"]) for r in record.get("reported") or []
            if r.get("outcome") in ("complete", "complete_with_errors", "unchanged")]


def request(repo, campaign_id: str, action: str = "start", *, report_base=None, report_root=None,
            db: str | None = None, api_base: str | None = None, api_port: int | None = None) -> tuple[dict, int]:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations.report_home import base_of
    if report_base is None and report_root is not None:
        from pathlib import Path
        report_base = base_of(Path(report_root))
    if api_base is None and api_port:
        api_base = f"http://127.0.0.1:{int(api_port)}"
    campaign_id = str(campaign_id or "").strip()
    action = str(action or "start").strip().lower()
    if campaign_id == STUDY_SCOPE:
        if action in {"start", "trigger", "refresh"}:
            return {"error": "one campaign's report cycle needs one campaign: choose its card in The study now"}, 400
        if action == "quiet":
            campaign_id = ""
    if action == "quiet":
        current = state(repo)
        if current and current.get("stage") in ACTIVE_STAGES and not current.get("only"):
            return {"quiet_report": current, "already": True,
                    "note": ("the study bundle is already being made; a second ask joins it "
                             "rather than starting another")}, 202
        outcome = start(repo, campaign_id, report_base=report_base, db=db, api_base=api_base)
        if not outcome["ok"]:
            return {"error": outcome["problem"]}, outcome["code"]
        return {"quiet_report": outcome["state"]}, 202
    if action == "cancel":
        return cancel(repo)
    if action not in {"start", "trigger", "refresh"}:
        return {"error": "action must be start, quiet or cancel"}, 400
    campaign = repo.campaign(campaign_id) if campaign_id else None
    if campaign is None:
        return {"error": f"unknown campaign {campaign_id!r}"}, 404
    problem = control.focus_problem(repo, campaign)
    if problem:
        return {"error": problem}, 409
    if in_progress(repo):
        current = state(repo) or {}
        return {"error": (f"a quiet report for campaign {current.get('campaign_id')} is "
                          f"{current.get('stage')}; it makes its bundle and resumes the fleet"),
                "quiet_report": current}, 409
    refusal = quiet_problem(repo)
    if refusal:
        return refusal, 409
    outcome = start(repo, campaign_id, report_base=report_base, db=db, api_base=api_base, only=True)
    if not outcome["ok"]:
        return {"error": outcome["problem"]}, outcome["code"]
    control.set_reporting_focus(repo, campaign_id)
    return {"quiet_report": outcome["state"], "reporting_campaign_id": campaign_id}, 202


def cancel(repo) -> tuple[dict, int]:
    record = state(repo)
    if not record or record.get("stage") not in ACTIVE_STAGES:
        return {"error": "no quiet report is in progress"}, 409
    if record["stage"] not in HOLDING_STAGES:
        return {"error": f"the quiet report is {record['stage']}; it finishes on its own", "quiet_report": record}, 409
    pid = (record.get("study_process") or {}).get("pid")
    if record["stage"] == REPORTING and _alive(pid):
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except (OSError, TypeError, ValueError):
            pass
    record["cancelled"] = True
    record["error"] = _join(record.get("error"), f"cancelled at {record['stage']}")
    return {"quiet_report": _save(repo, _advance(record, RESUMING, "cancelled; resuming what it paused"))}, 202


def _runner_failed(open_repo, exc: BaseException, failures: int) -> None:
    text = f"{type(exc).__name__}: {exc}"[:300]
    print(f"quiet report runner, failure {failures}: {text}", file=sys.stderr, flush=True)
    try:
        with open_repo() as repo:
            record = state(repo)
            if not record or record.get("stage") not in ACTIVE_STAGES:
                return
            record["runner_failures"], record["runner_error"] = failures, text
            if failures >= RUNNER_FAILURES_BEFORE_RESUMING and record["stage"] in HOLDING_STAGES:
                record["cancelled"] = True
                record["error"] = _join(record.get("error"), f"its runner failed {failures} times in a row: {text}")
                _advance(record, RESUMING, "the runner kept failing; resuming what it paused")
            _save(repo, record)
    except Exception as again:  # noqa: BLE001
        print(f"quiet report runner could not record it: {type(again).__name__}: {again}"[:300], file=sys.stderr,
              flush=True)


_RUNNER_LOCK = threading.Lock()
_RUNNER: dict[str, threading.Thread | None] = {"thread": None}


def ensure_runner(open_repo, *, tick_seconds: float | None = None) -> bool:
    interval = float(tick_seconds if tick_seconds is not None else ticks(1))
    with _RUNNER_LOCK:
        thread = _RUNNER["thread"]
        if thread is not None and thread.is_alive():
            return False

        def run() -> None:
            failures = 0
            while True:
                try:
                    with open_repo() as repo:
                        record = step(repo)
                    failures = 0
                    if not record or record.get("stage") not in ACTIVE_STAGES:
                        return
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    _runner_failed(open_repo, exc, failures)
                time.sleep(interval)

        thread = threading.Thread(target=run, name="gsd-quiet-report", daemon=True)
        _RUNNER["thread"] = thread
        thread.start()
        return True
