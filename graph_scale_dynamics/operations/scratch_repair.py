from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, CandidateState, utc_now
from graph_scale_dynamics.observability.child_diagnostics import NO_SPACE_STOP_TEXT

SCRATCH_REPAIR_CONTRACT = "gsd-scratch-repair-1"
REINSTATED_RULE = "reinstated"
NO_SPACE_TEXT = ("No space left on device", "Errno 28", "no_space_left", "staging_io")
_NEVER_CLOSED_NOTE = ("never closed: its worker died before its child reported "
                      f"(closed when the fleet started, {SCRATCH_REPAIR_CONTRACT})")


def _no_space_sql(error: str, error_class: str | None = None) -> str:
    texts = [f"COALESCE({error},'') ILIKE '%{t}%'" for t in NO_SPACE_TEXT]
    if error_class:
        texts += [f"COALESCE({error_class},'') ILIKE '%{t}%'" for t in NO_SPACE_TEXT]
    return "(" + " OR ".join(texts) + ")"


_ACTIVE = "EXISTS (SELECT 1 FROM campaigns c WHERE c.campaign_id=j.campaign_id AND c.status='active')"
_LOST_UNREPORTED = ("j.status='lost' AND EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.job_id) "
                    "AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.job_id AND a.finished_utc IS NOT NULL "
                    f"AND COALESCE(a.error,'') <> '{_NEVER_CLOSED_NOTE}')")
_FAILED_NO_SPACE = ("j.status='failed' AND EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.job_id AND "
                    + _no_space_sql("a.error", "a.error_class") + " AND NOT EXISTS (SELECT 1 FROM attempts b WHERE "
                    "b.job_id=j.job_id AND (b.started_utc,b.number)>(a.started_utc,a.number))) "
                    f"AND COALESCE(j.error,'') NOT ILIKE '%{NO_SPACE_STOP_TEXT}%'")


def _repairable_jobs(repo) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT j.job_id,j.campaign_id,j.candidate_id,j.n,j.seed,j.status FROM jobs j "
        f"WHERE j.kind='simulate' AND {_ACTIVE} AND (({_LOST_UNREPORTED}) OR ({_FAILED_NO_SPACE}))").fetchall()
    return [dict(row) for row in rows]


def _repairable_analyses(repo) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT q.campaign_id,q.input_artifact,q.analysis_version,q.candidate_id,q.n FROM analysis_queue q "
        "WHERE q.status='failed' AND EXISTS (SELECT 1 FROM campaigns c WHERE c.campaign_id=q.campaign_id "
        "AND c.status='active') AND " + _no_space_sql("q.error", "q.error_class")).fetchall()
    return [dict(row) for row in rows]


def _other_failures(repo) -> dict:
    rows = repo.conn.execute(
        "SELECT 'simulation' kind,COALESCE(LEFT(j.error,80),'') reason,COUNT(*) c FROM jobs j "
        f"WHERE j.kind='simulate' AND j.status IN ('failed','lost') AND {_ACTIVE} "
        f"AND NOT (({_LOST_UNREPORTED}) OR ({_FAILED_NO_SPACE})) GROUP BY 2 "
        "UNION ALL SELECT 'analysis',COALESCE(q.error_class,''),COUNT(*) FROM analysis_queue q "
        "WHERE q.status='failed' AND NOT " + _no_space_sql("q.error", "q.error_class") + " AND EXISTS ("
        "SELECT 1 FROM campaigns c WHERE c.campaign_id=q.campaign_id AND c.status='active') GROUP BY 2"
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        out.setdefault(str(row["kind"]), {})[str(row["reason"])] = int(row["c"])
    return out


def survey(repo) -> dict:
    never_closed = repo.conn.execute(
        "SELECT COUNT(*) c,MIN(started_utc) first,MAX(started_utc) last FROM attempts WHERE finished_utc IS NULL"
    ).fetchone()
    jobs, analyses = _repairable_jobs(repo), _repairable_analyses(repo)
    laws = _laws(repo, jobs, analyses)
    return {"contract": SCRATCH_REPAIR_CONTRACT,
            "attempts_never_closed": {"count": int(never_closed["c"] or 0), "first": never_closed["first"],
                                      "last": never_closed["last"]},
            "jobs": len(jobs), "analyses": len(analyses),
            "laws_to_reinstate": [law["candidate_id"] for law in laws["reinstate"]],
            "laws_running": len(laws["running"]), "laws_left_stopped": len(laws["left"]),
            "other_failures": _other_failures(repo)}


def _laws(repo, jobs: list[dict], analyses: list[dict]) -> dict:
    touched: dict[tuple[str, str], dict] = {}
    for job in jobs:
        touched.setdefault((job["campaign_id"], job["candidate_id"]), {"jobs": [], "analyses": []})["jobs"].append(job)
    for item in analyses:
        key = (item["campaign_id"], item["candidate_id"])
        touched.setdefault(key, {"jobs": [], "analyses": []})["analyses"].append(item)
    out = {"running": [], "reinstate": [], "left": []}
    before = given_back(repo, (SCRATCH_REPAIR_CONTRACT,)) if touched else set()
    for (campaign_id, law), work in sorted(touched.items()):
        row = repo.conn.execute(
            "SELECT c.state,d.rule,d.at_n,d.reason,d.decision_id,d.created_utc FROM campaign_candidates c LEFT JOIN "
            "engine_decisions_latest d ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
            "WHERE c.campaign_id=? AND c.candidate_id=?", (campaign_id, law)).fetchone()
        entry = {"campaign_id": campaign_id, "candidate_id": law, **work,
                 "state": None if row is None else row["state"],
                 "stop": None if row is None else {"rule": row["rule"], "at_n": row["at_n"], "reason": row["reason"],
                                                    "decision_id": row["decision_id"], "utc": row["created_utc"]}}
        if row is None:
            out["left"].append(entry)
        elif row["state"] != CandidateState.STOPPED.value:
            out["running" if row["state"] not in TERMINAL_CANDIDATE_STATES else "left"].append(entry)
        elif (row["rule"] == "failed" and _only_these(repo, campaign_id, law, work)
              and (campaign_id, law, rung(row["at_n"]), SCRATCH_REPAIR_CONTRACT) not in before):
            out["reinstate"].append(entry)
        else:
            out["left"].append(entry)
    return out


def rung(at_n) -> str:
    return "" if at_n is None else str(int(at_n))


def given_back(repo, contracts: tuple[str, ...]) -> set[tuple[str, str, str, str]]:
    out = set()
    for row in repo.conn.execute("SELECT payload_json FROM events WHERE topic='law_reinstated'").fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("contract") in contracts:
            out.add((str(payload.get("campaign_id")), str(payload.get("candidate_id")), rung(payload.get("at_n")),
                     str(payload.get("contract"))))
    return out


def _only_these(repo, campaign_id: str, law: str, work: dict) -> bool:
    failed = {str(r["job_id"]) for r in repo.conn.execute(
        "SELECT job_id FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
        "AND status IN ('failed','lost')", (campaign_id, law)).fetchall()}
    unanalysed = {str(r["input_artifact"]) for r in repo.conn.execute(
        "SELECT a.input_artifact FROM analysis_queue a WHERE a.campaign_id=? AND a.candidate_id=? "
        "AND a.status='failed' AND NOT EXISTS (SELECT 1 FROM analysis_queue b WHERE b.campaign_id=a.campaign_id "
        "AND b.candidate_id=a.candidate_id AND b.analysis_version=a.analysis_version AND b.n=a.n AND b.seed=a.seed "
        "AND b.status='done')", (campaign_id, law)).fetchall()}
    mine = {str(j["job_id"]) for j in work["jobs"]}
    theirs = {str(a["input_artifact"]) for a in work["analyses"]}
    return bool(failed or unanalysed) and failed <= mine and unanalysed <= theirs


def _requeue_jobs(repo, job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    return int(repo.conn.execute(
        "UPDATE jobs SET status='queued',attempts=0,lease_owner=NULL,lease_expires_utc=NULL,"
        "memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,updated_utc=? "
        "WHERE job_id IN (" + ",".join("?" for _ in job_ids) + ") AND status IN ('failed','lost','cancelled')",
        (utc_now(), *job_ids)).rowcount or 0)


def _requeue_analyses(repo, rows: list[dict]) -> int:
    changed = 0
    for item in rows:
        changed += int(repo.conn.execute(
            "UPDATE analysis_queue SET status='queued',attempts=0,lease_owner=NULL,claim_token=NULL,"
            "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,error_class=NULL,"
            "updated_utc=? WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
            "AND status IN ('failed','cancelled')",
            (utc_now(), item["campaign_id"], item["input_artifact"], item["analysis_version"])).rowcount or 0)
    return changed


def _close_never_closed(repo) -> dict:
    counts = {str(r["job_id"]): int(r["c"]) for r in repo.conn.execute(
        "SELECT job_id,COUNT(*) c FROM attempts WHERE finished_utc IS NULL GROUP BY job_id").fetchall()}
    if counts:
        repo.conn.execute(
            "UPDATE attempts SET finished_utc=?,exit_code=COALESCE(exit_code,-1),error=?,"
            "error_class='supervisor_interrupted' WHERE finished_utc IS NULL", (utc_now(), _NEVER_CLOSED_NOTE))
        for job_id, count in counts.items():
            repo.conn.execute("UPDATE jobs SET attempts=GREATEST(0,attempts-?) WHERE job_id=? "
                              "AND status IN ('queued','leased')", (count, job_id))
    ended = int(repo.conn.execute(
        "UPDATE jobs SET status='queued',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
        "next_attempt_utc=NULL,updated_utc=? WHERE status='leased'", (utc_now(),)).rowcount or 0)
    return {"attempts": sum(counts.values()), "jobs": len(counts), "leases_ended": ended}


def _minutes_before(stamp: str | None, minutes: int) -> str:
    from datetime import datetime, timedelta, timezone
    try:
        moment = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "9999"
    return (moment - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reinstate(repo, entry: dict, *, why: str | None = None, contract: str = SCRATCH_REPAIR_CONTRACT) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    campaign_id, law, stop = entry["campaign_id"], entry["candidate_id"], entry["stop"] or {}
    since = _minutes_before(stop.get("utc"), 5)
    cancelled = [str(r["job_id"]) for r in repo.conn.execute(
        "SELECT job_id FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND status='cancelled' "
        "AND updated_utc>=?", (campaign_id, law, since)).fetchall()]
    jobs = _requeue_jobs(repo, [str(j["job_id"]) for j in entry["jobs"]] + cancelled)
    cancelled_analyses = [dict(r) for r in repo.conn.execute(
        "SELECT campaign_id,input_artifact,analysis_version FROM analysis_queue WHERE campaign_id=? "
        "AND candidate_id=? AND status='cancelled' AND updated_utc>=?", (campaign_id, law, since)).fetchall()]
    analyses = _requeue_analyses(repo, entry["analyses"] + cancelled_analyses)
    campaign = repo.campaign(campaign_id) or {}
    policy = Policy.from_spec(campaign.get("spec") or {})
    at_n = stop.get("at_n")
    running = (CandidateState.EXTENDING.value if at_n is not None and int(at_n) > int(policy.base_sizes[-1])
               else CandidateState.BASE_BLOCK_RUNNING.value)
    reason = (f"{REINSTATED_RULE}: stopped by `{stop.get('rule')}` at N={at_n} "
              f"{why or 'for seeds that never ran or could not be written, the RAM scratch being full'} ({contract})")
    repo.conn.execute("UPDATE campaign_candidates SET state=?,state_reason=?,updated_utc=? WHERE campaign_id=? "
                      "AND candidate_id=?", (running, reason[:500], utc_now(), campaign_id, law))
    repo.conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                      ("law_reinstated", json.dumps({"campaign_id": campaign_id, "candidate_id": law, "at_n": at_n,
                                                     "undid": stop, "state": running, "requeued_jobs": jobs,
                                                     "requeued_analyses": analyses, "reason": reason,
                                                     "contract": contract}), utc_now()))
    return {"jobs": jobs, "analyses": analyses}


def repair(repo) -> dict:
    repo.begin_transaction(attempts=12)
    try:
        closed = _close_never_closed(repo)
        jobs, analyses = _repairable_jobs(repo), _repairable_analyses(repo)
        laws = _laws(repo, jobs, analyses)
        requeued_jobs = requeued_analyses = 0
        for entry in laws["running"]:
            requeued_jobs += _requeue_jobs(repo, [str(j["job_id"]) for j in entry["jobs"]])
            requeued_analyses += _requeue_analyses(repo, entry["analyses"])
        reinstated: dict[str, int] = {}
        for entry in laws["reinstate"]:
            done = _reinstate(repo, entry)
            requeued_jobs += done["jobs"]
            requeued_analyses += done["analyses"]
            reinstated[entry["campaign_id"]] = reinstated.get(entry["campaign_id"], 0) + 1
        repo.conn.execute("COMMIT")
    except Exception:
        repo.conn.rollback_if_open()
        raise
    return {"contract": SCRATCH_REPAIR_CONTRACT, "attempts_closed": closed, "jobs_requeued": requeued_jobs,
            "analyses_requeued": requeued_analyses, "laws_reinstated": reinstated,
            "laws_left_stopped": len(laws["left"]), "other_failures": _other_failures(repo)}


def render(result: dict) -> list[str]:
    closed = result.get("attempts_closed") or {}
    lines = []
    if closed.get("attempts"):
        lines.append(f"repair: closed {closed['attempts']:,} attempt(s) whose worker died before its child reported "
                     f"({closed['jobs']:,} job(s)); they no longer count against those jobs")
    if closed.get("leases_ended"):
        lines.append(f"repair: {closed['leases_ended']:,} seed(s) the last fleet still held queued again at once, "
                     "each from its saved state; none waits for its lease to run out or counts against its law")
    if result.get("jobs_requeued") or result.get("analyses_requeued"):
        lines.append(f"repair: queued again {result['jobs_requeued']:,} seed(s) and {result['analyses_requeued']:,} "
                     "analysis(es) that the full scratch lost or failed")
    reinstated = result.get("laws_reinstated") or {}
    if reinstated:
        by = ", ".join(f"campaign {c}: {n}" for c, n in sorted(reinstated.items()))
        lines.append(f"repair: {sum(reinstated.values())} law(s) stopped only for those are running again ({by})")
    return lines
