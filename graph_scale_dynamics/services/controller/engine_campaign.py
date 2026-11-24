from __future__ import annotations

from graph_scale_dynamics.db.decision_store import DecisionStore
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.observability import kappa_seconds, score_board
from graph_scale_dynamics.decisions.engine import STOP, Decision
from graph_scale_dynamics.domain.model import CandidateState
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scheduling.admission import (
    laws_in_their_base_block, note_waiting_to_learn, waiting_to_learn, without_the_waiting,
)

PENDING = (CandidateState.PROPOSED.value, CandidateState.VALIDATING.value)
RUNNING = CandidateState.BASE_BLOCK_RUNNING.value


def _stop(store: DecisionStore, campaign_id: str, law: str, rule: str, reason: str, facts: dict) -> None:
    decision = Decision(law=law, action=STOP, rule=rule, reason=reason, at_n=None, next_n=None, facts=facts)
    with store.one_transaction():
        changed = store.set_law_state(campaign_id, law, "STOPPED", rule=rule, next_n=None)
        store.record_decision(campaign_id, decision.as_dict() | {"jobs_created": 0, "rows_changed": changed,
                                                                 "queue_order": None, "released_hold": False})


def admit_proposed(repo, log, campaign: dict, store: DecisionStore) -> int:
    spec = campaign.get("spec") or {}
    campaign_id = str(campaign["campaign_id"])
    max_active = int(spec.get("max_active_candidates", 6))
    live = without_the_waiting(repo.live_laws_latest_decision(campaign_id), waiting_to_learn(repo, campaign_id))
    active = laws_in_their_base_block(live, store.policy.base_sizes[-1])
    capacity = max(0, max_active - active)
    if capacity == 0:
        return 0
    admitted = 0
    for candidate in repo.candidates_in_states(campaign_id, PENDING, limit=max(capacity * 2, capacity + 4)):
        if active >= max_active:
            break
        law = str(candidate["candidate_id"])
        problems = dsl.validate(candidate["spec"], complexity_budget=spec.get("complexity_budget", 6),
                                operator_whitelist=spec.get("operator_whitelist"))
        if problems:
            _stop(store, campaign_id, law, "invalid_spec", "; ".join(problems)[:500], {"problems": problems})
            log.write("law_invalid", candidate=law[:12], problems=problems[:5])
            continue
        repo.set_candidate_state(law, RUNNING, "admitted; the decider starts it", campaign_id)
        active += 1
        admitted += 1
    return admitted


def run_engine_campaign(repo, log, campaign: dict) -> dict:
    store = DecisionStore(repo, log, campaign)
    admitted = admit_proposed(repo, log, campaign, store)
    tally = decide_pass(store, str(campaign["campaign_id"]), store.policy)
    if store.learning or waiting_to_learn(repo, str(campaign["campaign_id"])):
        note_waiting_to_learn(repo, str(campaign["campaign_id"]), store.learning,
                              repo.live_laws_latest_decision(str(campaign["campaign_id"])),
                              store.policy.base_sizes[-1], store.policy.learn_in_batches_of)
    counts = {f"{action}:{rule}": count for (action, rule), count in sorted(tally.items())}
    if tally or admitted:
        log.write("engine_pass", campaign=str(campaign["campaign_id"])[:17], admitted=admitted, decisions=counts)
    try:
        kappa_seconds.scan(repo, str(campaign["campaign_id"]))
    except Exception as exc:  # noqa: BLE001
        log.write("kappa_seconds_scan_failed", campaign=str(campaign["campaign_id"])[:17],
                  error=f"{type(exc).__name__}: {exc}")
    campaign_id = str(campaign["campaign_id"])
    try:
        score_board.keep(repo, campaign_id, store.scored)
        score_board.scan(repo, campaign_id, lambda law: store.law_score(campaign_id, law))
    except Exception as exc:  # noqa: BLE001
        log.write("score_board_failed", campaign=campaign_id[:17], error=f"{type(exc).__name__}: {exc}")
    return {"admitted": admitted, "decisions": counts}
