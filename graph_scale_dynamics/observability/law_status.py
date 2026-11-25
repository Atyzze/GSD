from __future__ import annotations

from graph_scale_dynamics.domain.model import CandidateState as S

WAITING, SETTLED, RUNNING, NOT_RUN = "waiting to be extended", "settled", "running", "not started"
GATE, BUDGET, CONDITION, LADDER = "a gate", "its budget", "a condition", "the top of its ladder"
REASON_PREFIX = "decision engine: "
NOT_RUN_STATES = frozenset({S.PROPOSED.value, S.VALIDATING.value, S.PILOT_QUEUED.value})
RUNNING_STATES = frozenset({S.PILOT_RUNNING.value, S.BASE_BLOCK_RUNNING.value, S.EXTENDING.value,
                            S.DISCOVERY_ACTIVE.value, S.ROBUSTNESS_ACTIVE.value})
SETTLED_STATES = frozenset({S.PARKED.value, S.STOPPED.value, S.QUARANTINE.value, S.REJECTED_HEALTH.value,
                            S.REJECTED_SCALING.value, S.REJECTED_STATIC.value})
OVER_BUDGET = "over_budget"


def rule_of(state_reason) -> str | None:
    text = str(state_reason or "")
    if not text.startswith(REASON_PREFIX):
        return None
    rule = text[len(REASON_PREFIX):].strip()
    return rule or None


def settled_by(rule) -> str:
    from graph_scale_dynamics.decisions import gates as G
    if rule is None:
        return CONDITION
    if str(rule) == OVER_BUDGET:
        return BUDGET
    return GATE if G.today(str(rule)) in G.BY_NAME else CONDITION


def _n(value) -> str:
    return f"N={int(value):,}"


def status(state, *, rule=None, at_n=None, next_n=None, region=None) -> dict:
    state = str(state or "")
    at = int(at_n) if at_n is not None else None
    if state == S.DONE.value:
        text = (f"waiting to be extended: read to {_n(at)}, the top of its ladder" if at is not None
                else "waiting to be extended: read to the top of its ladder")
        return {"word": WAITING, "by": LADDER, "rule": rule, "at_n": at, "text": text}
    if state == S.HELD.value:
        text = (f"waiting to be extended: read to {_n(at)}, {_n(next_n)} when a place frees"
                if at is not None and next_n is not None else "waiting to be extended: its next size when a place frees")
        return {"word": WAITING, "by": None, "rule": rule, "at_n": at, "text": text}
    if state in RUNNING_STATES:
        text = (f"running: read to {_n(at)}, {_n(next_n)} under way" if at is not None and next_n is not None
                else f"running: {_n(next_n)} under way" if next_n is not None else "running")
        return {"word": RUNNING, "by": None, "rule": rule, "at_n": at, "text": text}
    if state in NOT_RUN_STATES or not state:
        return {"word": NOT_RUN, "by": None, "rule": None, "at_n": None, "text": NOT_RUN}
    by = f"region {region}" if region else settled_by(rule)
    if at is None:
        word = SETTLED
        text = f"settled by {by}" + (f" ({rule})" if rule else f" ({state.lower()})") + " before any size was read"
    else:
        word = f"settled at {_n(at)}"
        text = (f"settled by {by}" + (f" ({rule})" if rule else "") + f", its highest reading {_n(at)}; "
                "it waits to be extended past it")
    return {"word": word, "by": by, "rule": rule, "at_n": at, "text": text}


def of_row(row: dict) -> dict:
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    rule = decision.get("rule") or rule_of(row.get("state_reason"))
    at_n = decision.get("at_n")
    if at_n is None:
        at_n = row.get("decision_at_n", row.get("largest_n", row.get("top_n")))
    return status(row.get("state"), rule=rule, at_n=at_n, next_n=decision.get("next_n", row.get("next_n")),
                  region=row.get("region_name"))


def of_law(repo, campaign_id: str, candidate: dict) -> dict:
    found = repo.conn.execute(
        "SELECT rule, at_n, next_n FROM engine_decisions_latest WHERE campaign_id=? AND candidate_id=?",
        (str(campaign_id), str(candidate["candidate_id"]))).fetchone()
    if found is None:
        return of_row(dict(candidate))
    return status(candidate.get("state"), rule=found["rule"], at_n=found["at_n"], next_n=found["next_n"])


__all__ = ["BUDGET", "CONDITION", "GATE", "LADDER", "NOT_RUN", "RUNNING", "SETTLED", "WAITING", "of_law", "of_row",
           "rule_of", "settled_by", "status"]
