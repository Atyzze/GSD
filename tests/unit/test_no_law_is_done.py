from __future__ import annotations

from graph_scale_dynamics.domain.model import CandidateState as S
from graph_scale_dynamics.observability import law_status as L


def test_a_law_at_the_top_of_its_ladder_waits_to_be_extended_and_says_how_far_it_was_read():
    found = L.status(S.DONE.value, rule="ladder_complete", at_n=65536)
    assert found["word"] == L.WAITING and found["by"] == L.LADDER
    assert "N=65,536" in found["text"] and "done" not in found["text"].lower()


def test_a_settled_law_names_what_settled_it_and_its_highest_reading():
    cases = {("starts_alike", 16384): L.GATE, ("empty", 1024): L.GATE, ("over_budget", 256): L.BUDGET,
             ("no_such_rule", 4096): L.CONDITION}
    for (rule, at_n), by in cases.items():
        for state in (S.PARKED.value, S.STOPPED.value):
            found = L.status(state, rule=rule, at_n=at_n)
            assert found["by"] == by and found["at_n"] == at_n
            assert found["word"] == f"settled at N={at_n:,}" and f"({rule})" in found["text"]
            assert "waits to be extended" in found["text"]
    region = L.status(S.PARKED.value, rule="starts_alike", at_n=16384, region="GG#3")
    assert region["by"] == "region GG#3"


def test_every_state_has_words_and_none_of_them_is_done():
    for state in S:
        found = L.status(state.value, rule="starts_alike", at_n=4096, next_n=16384)
        assert found["word"] and found["text"]
        assert "done" not in (found["word"] + " " + found["text"]).lower(), state


def test_a_row_without_its_decision_reads_the_rule_from_its_reason_and_its_size_from_its_largest_rung():
    found = L.of_row({"state": "PARKED", "state_reason": "decision engine: starts_alike", "largest_n": 16384})
    assert (found["rule"], found["at_n"], found["by"]) == ("starts_alike", 16384, L.GATE)
    assert L.rule_of("something else") is None
