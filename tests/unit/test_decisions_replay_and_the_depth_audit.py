from __future__ import annotations

import json
from dataclasses import replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT, STOP, Policy, Rung, decide
from graph_scale_dynamics.decisions.replay import replay, replay_matches
from tests.unit.test_decider import FakeStore, entry

POLICY = Policy(promising_bar=False, deep_salt_at_most=Policy().audit_fraction)


def _law(salted_at: str | None = None) -> str:
    if salted_at is None:
        return G.unsalted_law("law-", POLICY.audit_fraction)
    return next(f"law-{i}" for i in range(20000) if G.salted(f"law-{i}", salted_at, POLICY.audit_fraction)
                and not any(G.salted(f"law-{i}", gate, POLICY.audit_fraction) for gate in G.SALTED_GATES - {salted_at}))


def _unsettled_rungs(top: int = 4096) -> list:
    return [Rung(n=n, mean_degree=2.5, connected_fraction=1.0,
                 probes={"d_s": (1.0 + 0.4 * i, 0.01)}, seeds_measured=3)
            for i, n in enumerate(POLICY.ladder()) if n <= top]


def test_each_park_draws_its_own_tenth_apart_from_every_other_gate():
    laws = [f"law-{i}" for i in range(20000)]
    for gate in sorted(G.WITHHOLDING_GATES):
        share = sum(G.salted(law, gate, POLICY.audit_fraction) for law in laws) / len(laws)
        assert 0.09 < share < 0.11, gate
    both = sum(G.salted(law, "unsettled_twice", 0.1) and G.salted(law, "no_reading", 0.1) for law in laws) / len(laws)
    assert both < 0.02, "a salted hash per gate: the samples are drawn independently"


def test_a_salted_park_gets_its_next_rung_and_says_what_it_would_have_been():
    plain, twice = _law(), _law("unsettled_twice")
    looked = decide(plain, _unsettled_rungs(), POLICY)
    assert (looked.action, looked.rule, looked.next_n, looked.priority) == (RUN_NEXT, "second_rung", 16384, 2)
    parked = decide(plain, _unsettled_rungs(16384), POLICY)
    assert (parked.action, parked.rule, parked.next_n) == (STOP, "unsettled_twice", None)
    bought = decide(twice, _unsettled_rungs(16384), POLICY)
    assert (bought.action, bought.rule, bought.next_n, bought.priority) == (RUN_NEXT, "salted", 65536, 2)
    assert bought.facts["salted_from"]["rule"] == "unsettled_twice" and bought.facts["salted"] == ["unsettled_twice"]
    legacy = replace(POLICY, second_rung=False)
    held = decide(plain, _unsettled_rungs(), legacy)
    assert (held.action, held.rule, held.next_n) == (HOLD, "unsettled", 16384)
    salted_hold = decide(_law("unsettled"), _unsettled_rungs(), legacy)
    assert (salted_hold.rule, salted_hold.facts["salted_from"]["rule"]) == ("salted", "unsettled")


def test_the_salt_follows_past_the_plateau_rung_and_waits_for_a_full_lane():
    rungs = [Rung(n=n, mean_degree=2.5, connected_fraction=1.0,
                  probes={"d_s": (1.0 if n < 65536 else 1.8, 0.01)}, seeds_measured=3)
             for n in POLICY.ladder() if n <= 65536]
    assert decide(_law(), rungs, POLICY).rule == "no_second_rung"
    law = _law("no_second_rung")
    decision = decide(law, rungs, POLICY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "salted", 262144), decision
    plateau = [Rung(n=n, mean_degree=2.5, connected_fraction=1.0,
                    probes={"d_s": ((1.0 if n < 65536 else 1.8) if n < 262144 else 1.8, 0.01)}, seeds_measured=3)
               for n in POLICY.ladder() if n <= 262144]
    waiting = decide(_law("no_plateau"), plateau, POLICY, deep_lane_in_flight={1048576: 4})
    assert (waiting.action, waiting.rule, waiting.next_n) == (HOLD, "deep_lane_full", 1048576)
    assert waiting.facts["salted"] == ["no_plateau"]


def test_the_salt_is_one_number_for_every_gate_and_a_campaign_can_switch_it_off():
    policy = replace(POLICY, audit_fraction=0.0)
    assert decide(_law("unsettled_twice"), _unsettled_rungs(16384), policy).rule == "unsettled_twice"


def test_every_decision_is_recorded_with_its_inputs_and_context_and_replays_from_them():
    laws = [_law(), _law("unsettled_twice"), "law-new"]
    entries = {laws[0]: {rung.n: entry(2.5, d_s=rung.probes["d_s"][0], se=0.01) for rung in _unsettled_rungs()},
               laws[1]: {rung.n: entry(2.5, d_s=rung.probes["d_s"][0], se=0.01) for rung in _unsettled_rungs(16384)}}
    store = FakeStore(laws, entries=entries, depth=7)
    decide_pass(store, "1", POLICY)
    assert len(store.decisions) == 3
    for row in store.decisions:
        assert row["inputs"]["policy"] and row["inputs"]["rules_revision"] and row["inputs"]["law"] == row["law"]
        assert row["context"]["queue_depth"] >= 7 and "lane_occupancy" in row["context"]
        stored = json.loads(json.dumps(row, default=str))
        verdict = replay_matches(dict(stored, facts_json=json.dumps(row["facts"], default=str)))
        assert verdict["matches"] and verdict["same_rules"], (row["rule"], verdict)
    rules = {row["law"]: row["rule"] for row in store.decisions}
    assert rules == {laws[0]: "second_rung", laws[1]: "salted", "law-new": "start"}


def test_a_replay_says_when_the_record_and_the_rules_disagree():
    store = FakeStore([_law()], entries={_law(): {
        rung.n: entry(2.5, d_s=rung.probes["d_s"][0], se=0.01) for rung in _unsettled_rungs()}})
    decide_pass(store, "1")
    row = json.loads(json.dumps(store.decisions[0], default=str))
    row["inputs"]["policy"]["d_s_sigmas"] = 1000.0
    verdict = replay_matches(dict(row, facts_json=json.dumps(row["facts"])))
    assert verdict["matches"] is False and not verdict["same_rules"]
    assert replay(row["inputs"]).rule == "d_s_settled"
