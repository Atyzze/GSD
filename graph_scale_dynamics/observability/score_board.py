from __future__ import annotations

import json
import time

from graph_scale_dynamics.observability import law_score as L

FLAG_PREFIX = "law_scores:"
CONTRACT = "gsd-score-board-1"
SCAN_INTERVAL_SECONDS = 30.0
SCAN_LIMIT = 100
SCAN_SECONDS = 1.0
_LAST_SCAN: dict[str, float] = {}


def _key(campaign_id: str) -> str:
    return FLAG_PREFIX + str(campaign_id)


def load(repo, campaign_id: str) -> dict:
    try:
        state = json.loads(repo.get_flag(_key(campaign_id), "") or "{}")
    except (TypeError, ValueError):
        state = {}
    if state.get("contract") != CONTRACT or state.get("score_contract") != L.CONTRACT:
        state = {"contract": CONTRACT, "score_contract": L.CONTRACT, "scores": {}, "zeros": [], "after": "",
                 "complete": False}
    return state


def _save(repo, campaign_id: str, state: dict) -> None:
    repo.set_flag(_key(campaign_id), json.dumps(state, sort_keys=True, separators=(",", ":")))


def _put(state: dict, law: str, found: dict) -> None:
    if int(found.get("score") or 0) > 0:
        state["scores"][str(law)] = found
        if str(law) in state["zeros"]:
            state["zeros"].remove(str(law))
    else:
        state["scores"].pop(str(law), None)
        if not state["complete"] and str(law) > str(state["after"]) and str(law) not in state["zeros"]:
            state["zeros"].append(str(law))


def keep(repo, campaign_id: str, scored: dict) -> int:
    if not scored:
        return 0
    state = load(repo, campaign_id)
    for law, found in scored.items():
        _put(state, law, found)
    _save(repo, campaign_id, state)
    return len(scored)


def scan(repo, campaign_id: str, score_of, *, now: float | None = None, limit: int = SCAN_LIMIT,
         seconds: float = SCAN_SECONDS) -> int:
    clock = time.monotonic() if now is None else float(now)
    if clock - _LAST_SCAN.get(str(campaign_id), -1e18) < SCAN_INTERVAL_SECONDS:
        return 0
    _LAST_SCAN[str(campaign_id)] = clock
    state = load(repo, campaign_id)
    if state["complete"]:
        return 0
    rows = repo.conn.execute(
        "SELECT DISTINCT candidate_id FROM measurements WHERE campaign_id=? AND n>=? AND candidate_id>? "
        "ORDER BY candidate_id LIMIT ?", (str(campaign_id), int(L.LADDER[0]), str(state["after"]), int(limit))).fetchall()
    started, done = time.monotonic(), 0
    for row in rows:
        law = str(row["candidate_id"])
        _put(state, law, score_of(law))
        state["after"], done = law, done + 1
        if time.monotonic() - started > seconds:
            break
    if not rows or (done == len(rows) and len(rows) < int(limit)):
        state["complete"], state["zeros"] = True, []
    elif state["zeros"]:
        state["zeros"] = [law for law in state["zeros"] if law > state["after"]]
    _save(repo, campaign_id, state)
    return done


def board(repo, campaign_id: str) -> dict:
    state = load(repo, campaign_id)
    return {"scores": state["scores"], "zeros": state["zeros"], "after": state["after"], "complete": state["complete"]}


def of(found: dict, law: str) -> dict | None:
    law = str(law)
    if law in found["scores"]:
        return found["scores"][law]
    if found["complete"] or law <= str(found["after"]) or law in found["zeros"]:
        return L.zero()
    return None
