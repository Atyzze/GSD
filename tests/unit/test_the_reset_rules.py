from __future__ import annotations

import json
from dataclasses import replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import (
    HOLD, PARKING_RULES, RUN_NEXT, STOP, Policy, Rung, decide)
from graph_scale_dynamics.decisions.replay import replay_matches

POLICY = Policy(promising_bar=False, deep_salt_at_most=Policy().audit_fraction)
PLAIN = G.unsalted_law("law-", POLICY.audit_fraction)
AUDITED = next(f"law-{i}" for i in range(20000) if G.salted(f"law-{i}", "unsettled_twice", POLICY.audit_fraction)
               and not any(G.salted(f"law-{i}", gate, POLICY.audit_fraction)
                           for gate in G.SALTED_GATES - {"unsettled_twice"}))


def ladder(values: dict) -> list:
    out = []
    for n in POLICY.ladder():
        if n > max(values):
            break
        value = values.get(n, 1.5)
        probes = {} if value is None else {"d_s": (value, 0.01)}
        out.append(Rung(n=n, mean_degree=2.5, connected_fraction=1.0, probes=probes, seeds_measured=3))
    return out


def replays(law, rungs, decision):
    row = json.loads(json.dumps(decision.as_dict() | {"inputs": decision_inputs(law, rungs, POLICY)}, default=str))
    verdict = replay_matches(dict(row, facts_json=json.dumps(decision.facts, default=str)))
    assert verdict["matches"] and verdict["same_rules"], verdict
    return True


def test_a_reading_lost_and_regained_is_judged_across_the_gap():
    law_rungs = ladder({16384: 1.5, 65536: None, 262144: 1.5})
    decision = decide(PLAIN, law_rungs, POLICY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "d_s_settled", 1048576)
    assert decision.facts["d_s_across"] == 65536 and decision.facts["plateau"]["d_s_settled_before"]
    assert replays(PLAIN, law_rungs, decision)
    moved = decide(PLAIN, ladder({16384: 1.5, 65536: None, 262144: 2.4}), POLICY)
    assert (moved.action, moved.rule) == (STOP, "no_second_rung"), "across the gap it must still settle"
    assert decide(PLAIN, ladder({16384: 1.5, 65536: None, 262144: 2.4}), replace(POLICY, second_rung=False)).rule == "unsettled"


def test_two_refused_rungs_in_a_row_end_the_comparison():
    decision = decide(PLAIN, ladder({16384: None, 65536: None, 262144: 1.5}), POLICY)
    assert decision.facts["d_s_across"] is None and not decision.facts["d_s_settled"]


def test_unsettled_once_holds_and_unsettled_twice_parks_with_everything_kept():
    legacy = replace(POLICY, second_rung=False)
    once = decide(PLAIN, ladder({4096: 2.3}), legacy)
    assert (once.action, once.rule) == (HOLD, "unsettled")
    law_rungs = ladder({4096: 2.3, 16384: 3.1})
    twice = decide(PLAIN, law_rungs, legacy)
    assert (twice.action, twice.rule, twice.next_n) == (STOP, "unsettled_twice", None)
    assert "unsettled_twice" in PARKING_RULES, "a park, not a stop on a verdict about the law"
    assert twice.facts["unsettled_streak"] == 2 and "parked" in twice.reason
    settled_between = decide(PLAIN, ladder({4096: 2.3, 16384: 2.3, 65536: 3.5}), legacy)
    assert settled_between.rule == "unsettled", "a settled step breaks the run"
    assert decide(PLAIN, law_rungs, replace(POLICY, second_rung=False, unsettled_rungs_to_park=0)).rule == "unsettled"


def test_the_first_look_buys_the_next_rung_and_the_second_parks():
    once = decide(PLAIN, ladder({4096: 2.3}), POLICY)
    assert (once.action, once.rule, once.next_n, once.priority) == (RUN_NEXT, "second_rung", 16384, 2)
    assert once.facts["unsettled_streak"] == 1 and "look before a park" in once.reason
    assert replays(PLAIN, ladder({4096: 2.3}), once)
    law_rungs = ladder({4096: 2.3, 16384: 3.1})
    twice = decide(PLAIN, law_rungs, POLICY)
    assert (twice.action, twice.rule, twice.next_n) == (STOP, "unsettled_twice", None)
    assert twice.facts["unsettled_streak"] == 2 and "parked" in twice.reason
    assert replays(PLAIN, law_rungs, twice)
    settled_between = decide(PLAIN, ladder({4096: 2.3, 16384: 2.3, 65536: 3.5}), POLICY)
    assert (settled_between.rule, settled_between.next_n) == ("no_second_rung", None), "262,144 takes a plateau"
    assert "no_second_rung" in PARKING_RULES
    assert decide(PLAIN, law_rungs, replace(POLICY, unsettled_rungs_to_park=1)).rule == "unsettled_twice"
    assert decide(PLAIN, ladder({4096: 2.3}), replace(POLICY, unsettled_rungs_to_park=1)).rule == "unsettled_twice", \
        "k = 1: the first look parks"


def test_no_reading_at_the_top_two_rungs_parks_and_one_reading_gets_the_look():
    unread = decide(PLAIN, ladder({1024: None, 4096: None}), POLICY)
    assert (unread.action, unread.rule, unread.next_n) == (STOP, "no_reading", None)
    assert "no reading at N=1024 or N=4096" in unread.reason and "no_reading" in PARKING_RULES
    assert replays(PLAIN, ladder({1024: None, 4096: None}), unread)
    top_only = decide(PLAIN, ladder({1024: None, 4096: 1.5, 256: None}), POLICY)
    below_only = decide(PLAIN, ladder({1024: 2.3, 4096: None}), POLICY)
    assert (top_only.rule, below_only.rule) == ("second_rung", "second_rung")
    assert decide(AUDITED, ladder({1024: None, 4096: None}), POLICY).rule == "no_reading", \
        "a law salted past one gate is not salted past another"


def test_the_park_s_salt_buys_one_rung_and_a_park_that_holds_there_stands():
    audited = decide(AUDITED, ladder({4096: 2.3, 16384: 3.1}), POLICY)
    assert (audited.action, audited.rule, audited.next_n) == (RUN_NEXT, "salted", 65536)
    assert audited.facts["salted_from"]["rule"] == "unsettled_twice"
    held = ladder({4096: 2.3, 16384: 3.1, 65536: 4.0})
    spent = decide(AUDITED, held, POLICY)
    assert (spent.action, spent.rule, spent.next_n) == (STOP, "unsettled_twice", None)
    assert spent.facts["salt_spent"] == {"gate": "unsettled_twice", "salted_at": 16384, "held_at": 65536}
    assert "the salt's one rung is spent" in spent.reason
    assert replays(AUDITED, held, spent)
    settled = decide(AUDITED, ladder({4096: 2.3, 16384: 3.1, 65536: 3.1}), POLICY)
    assert (settled.action, settled.rule) == (HOLD, "no_plateau") and "salt_spent" not in settled.facts
