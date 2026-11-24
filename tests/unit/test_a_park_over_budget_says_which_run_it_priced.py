from __future__ import annotations

from graph_scale_dynamics.decisions.engine import OVER_BUDGET, over_budget_reason
from graph_scale_dynamics.decisions.replay import reason_in_today_s_words

CHUNK = {"from_n": 4096, "seeds": 3, "units_a_move": 1.5, "multiplier": 8, "predicted": 9_000_000_000,
         "budget": 6_000_000_000, "fits": False}


def test_a_longer_chain_at_the_size_it_is_at_is_said_so():
    reason = over_budget_reason(4096, CHUNK, "longer_chain")
    assert reason.startswith("a longer chain at the size it is at, N=4,096, 8 times the moves")
    assert "first chunk at N=4,096" not in reason and "more than the size's budget of 6,000,000,000" in reason
    up = over_budget_reason(16384, CHUNK, "salted")
    assert up.startswith("its first chunk at N=16,384 is predicted at 9,000,000,000 units of work from its own "
                         "seeds at N=4,096"), "the next size reads as before"
    assert over_budget_reason(16384, CHUNK, "salted", former=True) == up


def test_a_park_recorded_in_the_former_words_replays_in_today_s():
    facts = {"first_chunk": CHUNK, "refused": {"action": "run_next", "rule": "longer_chain", "next_n": 4096,
                                               "priority": 3}}
    row = {"rule": OVER_BUDGET, "reason": over_budget_reason(4096, CHUNK, "longer_chain", former=True)}
    assert reason_in_today_s_words(row, facts) == over_budget_reason(4096, CHUNK, "longer_chain")
    other = dict(row, reason="something else")
    assert reason_in_today_s_words(other, facts) == "something else", "only the exact former wording is read anew"
    assert reason_in_today_s_words({"rule": "empty", "reason": "x"}, facts) == "x"
