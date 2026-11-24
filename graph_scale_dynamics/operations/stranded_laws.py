from __future__ import annotations

import json

from graph_scale_dynamics.db.decision_store import LAW_IDLE_SQL as _IDLE
from graph_scale_dynamics.db.decision_store import REDECIDE_MARK
from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES, utc_now

STRANDED_CONTRACT = "gsd-stranded-laws-1"

LASTING_SECONDS = 3600
NAMED = 8


def _live_states() -> tuple[str, ...]:
    return tuple(sorted(RUNNING_CANDIDATE_STATES))


def stranded(repo) -> list[dict]:
    states = _live_states()
    rows = repo.conn.execute(
        "SELECT c.campaign_id,c.candidate_id,c.state,c.updated_utc,d.decision_id,d.action,d.rule,d.at_n,d.created_utc "
        "FROM campaign_candidates c JOIN engine_decisions_latest d ON d.campaign_id=c.campaign_id "
        "AND d.candidate_id=c.candidate_id "
        f"WHERE c.state IN ({','.join('?' for _ in states)}) AND d.action IN ('stop','done') AND {_IDLE} "
        "ORDER BY c.campaign_id,c.candidate_id", states).fetchall()
    return [dict(r) for r in rows]


def lasting(repo, *, now_utc: str | None = None) -> list[dict]:
    from datetime import datetime, timedelta
    now = datetime.fromisoformat(str(now_utc or utc_now()).replace("Z", "+00:00"))
    before = (now - timedelta(seconds=LASTING_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    states = _live_states()
    rows = repo.conn.execute(
        "SELECT c.campaign_id,c.candidate_id,c.state,d.decision_id,d.action,d.rule,d.at_n,d.next_n,d.created_utc "
        "FROM campaign_candidates c JOIN engine_decisions_latest d ON d.campaign_id=c.campaign_id "
        "AND d.candidate_id=c.candidate_id "
        f"WHERE c.state IN ({','.join('?' for _ in states)}) AND d.action NOT IN ('stop','done','hold') "
        f"AND d.created_utc < ? AND {_IDLE} ORDER BY d.created_utc", (*states, before)).fetchall()
    return [dict(r) for r in rows]


def survey(repo) -> dict:
    return {"contract": STRANDED_CONTRACT, "stranded": stranded(repo), "lasting": lasting(repo)}


def repair(repo) -> dict:
    repo.begin_transaction(attempts=12)
    try:
        laws = stranded(repo)
        taken = {(str(x["campaign_id"]), str(x["candidate_id"])) for x in laws}
        waited = [x for x in lasting(repo) if (str(x["campaign_id"]), str(x["candidate_id"])) not in taken]
        for law in laws + waited:
            repo.conn.execute("UPDATE engine_decisions_latest SET jobs_seen=? WHERE campaign_id=? AND "
                              "candidate_id=? AND decision_id=?",
                              (f"{REDECIDE_MARK}{utc_now()}", law["campaign_id"], law["candidate_id"],
                               law["decision_id"]))
            repo.conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                              ("law_redecided", json.dumps({"contract": STRANDED_CONTRACT, **law}, default=str),
                               utc_now()))
        repo.conn.execute("COMMIT")
    except Exception:
        repo.conn.rollback_if_open()
        raise
    marked = taken | {(str(x["campaign_id"]), str(x["candidate_id"])) for x in waited}
    return {"contract": STRANDED_CONTRACT, "redecided": [_name(x) for x in laws],
            "waited": [_name(x) for x in waited],
            "lasting": [_name(x) for x in lasting(repo) if (str(x["campaign_id"]), str(x["candidate_id"])) not in marked]}


def _name(row: dict) -> dict:
    return {"campaign_id": str(row["campaign_id"]), "law": str(row["candidate_id"])[:10], "state": row.get("state"),
            "rule": row.get("rule"), "at_n": row.get("at_n"), "since": row.get("created_utc")}


def _named(laws: list[dict]) -> str:
    shown = ", ".join(f"{e['law']} (campaign {e['campaign_id']}, {e['rule']} at N={e['at_n']})" for e in laws[:NAMED])
    return shown + (f" and {len(laws) - NAMED} more" if len(laws) > NAMED else "")


def render(result: dict) -> list[str]:
    lines = []
    if result.get("redecided"):
        lines.append(f"repair: {len(result['redecided'])} law(s) running with no work under a stop are decided again "
                     f"by the engine: {_named(result['redecided'])}")
    if result.get("waited"):
        lines.append(f"repair: {len(result['waited'])} law(s) that awaited their decision for over an hour with no "
                     f"work are decided again by the engine: {_named(result['waited'])}")
    if result.get("lasting"):
        lines.append(f"repair: {len(result['lasting'])} law(s) have awaited their decision for over an hour: "
                     f"{_named(result['lasting'])}")
    return lines
