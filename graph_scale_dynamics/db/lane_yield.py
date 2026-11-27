from __future__ import annotations

import calendar
import time

from graph_scale_dynamics.domain.model import LANE_YIELD_REASON, MODE_YIELD_REASON

PARKED_UNTIL = "2999-12-31T00:00:00Z"
PARKED_FROM = "2999-01-01T00:00:00Z"


def parked_sql(alias: str = "j") -> str:
    return f"({alias}.status='queued' AND {alias}.next_attempt_utc IS NOT NULL AND {alias}.next_attempt_utc>='{PARKED_FROM}')"


def park_seconds(now: float | None = None) -> int:
    until = calendar.timegm(time.strptime(PARKED_UNTIL, "%Y-%m-%dT%H:%M:%SZ"))
    return max(1, int(until - (time.time() if now is None else float(now))))


YIELDED_SQL = ("SELECT 1 FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=? AND action='hold' "
               "AND next_n=? AND facts_json LIKE '%\"yielded\"%' LIMIT 1")


def lane_yield_reason(repo, job: dict) -> str | None:
    if str(job.get("kind") or "simulate") != "simulate" or job.get("n") is None or not job.get("campaign_id"):
        return None
    row = repo.conn.execute(YIELDED_SQL, (str(job["campaign_id"]), str(job.get("candidate_id")),
                                          int(job["n"]))).fetchone()
    return LANE_YIELD_REASON if row is not None else None


def mode_yield_reason(repo, job: dict) -> str | None:
    from graph_scale_dynamics.operations import modes
    from graph_scale_dynamics.scheduling.fleet_halves import EXTENSION_FROM_N
    if str(job.get("kind") or "simulate") != "simulate" or job.get("n") is None:
        return None
    mode = modes.here(repo)
    if mode is None:
        return None
    if str(job.get("campaign_id")) not in {str(c) for c in mode["campaigns"]}:
        return MODE_YIELD_REASON
    if mode["mode"] != modes.PUSH:
        return None
    laws, law = [str(x) for x in mode.get("laws") or []], str(job.get("candidate_id"))
    if not laws or law == laws[0] or (law in laws and int(job["n"]) < EXTENSION_FROM_N):
        return None
    return MODE_YIELD_REASON


def release_defer_seconds(stop_reason: str | None) -> int | None:
    return park_seconds() if stop_reason == LANE_YIELD_REASON else None
