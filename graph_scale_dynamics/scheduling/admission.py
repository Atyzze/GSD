from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import CandidateState

LEARNING_WAITS = "learning_waits:"

SLOT_PROPOSED = "proposed"
SLOT_BASE_BLOCK = "base_block"
SLOT_HELD = "held"
SLOT_ABOVE_BASE_BLOCK = "above_base_block"
SLOT_FINISHING = "finishing"
SLOTS = (SLOT_PROPOSED, SLOT_BASE_BLOCK, SLOT_HELD, SLOT_ABOVE_BASE_BLOCK, SLOT_FINISHING)


def admission_slot(state: str, latest_action: str | None, latest_next_n: int | None, top_base_n: int) -> str:
    if state == CandidateState.PROPOSED.value:
        return SLOT_PROPOSED
    if latest_action == "hold":
        return SLOT_HELD
    if latest_action in ("stop", "done"):
        return SLOT_FINISHING
    if latest_action == "run_next" and latest_next_n is not None and int(latest_next_n) > int(top_base_n):
        return SLOT_ABOVE_BASE_BLOCK
    return SLOT_BASE_BLOCK


def laws_in_their_base_block(live_laws: list[dict], top_base_n: int) -> int:
    return sum(1 for row in live_laws or []
               if admission_slot(str(row.get("state")), row.get("action"), row.get("next_n"),
                                 top_base_n) == SLOT_BASE_BLOCK)


def waiting_to_learn(repo, campaign_id: str) -> set:
    raw = str(repo.get_flag(f"{LEARNING_WAITS}{campaign_id}", "") or "")
    try:
        return {str(law) for law in json.loads(raw)} if raw else set()
    except ValueError:
        return set()


def without_the_waiting(live_laws: list, waiting: set) -> list:
    return [row for row in live_laws or [] if str(row.get("candidate_id")) not in waiting]


def note_waiting_to_learn(repo, campaign_id: str, laws, live_laws: list, top_base_n: int, most: int) -> list:
    base = {str(row.get("candidate_id")) for row in live_laws or []
            if admission_slot(str(row.get("state")), row.get("action"), row.get("next_n"), top_base_n)
            == SLOT_BASE_BLOCK}
    waiting = sorted(str(law) for law in laws or () if str(law) in base)[:max(0, int(most))]
    value = json.dumps(waiting, separators=(",", ":")) if waiting else ""
    key = f"{LEARNING_WAITS}{campaign_id}"
    if str(repo.get_flag(key, "") or "") != value:
        repo.set_flag(key, value)
    return waiting
