from __future__ import annotations

import json

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT, STOP, Policy, Rung, decide
from graph_scale_dynamics.decisions.replay import replay_matches

POLICY = Policy(deep_salt_at_most=Policy().audit_fraction)
NO_FIRST_GATE = Policy(deep_salt_at_most=Policy().audit_fraction, nothing_read_gate=False)


def only(gate: str) -> str:
    return next(f"law-{i}" for i in range(50000) if G.salted(f"law-{i}", gate, POLICY.audit_fraction)
                and not any(G.salted(f"law-{i}", other, POLICY.audit_fraction) for other in G.SALTED_GATES - {gate}))


def rung(n, md=2.5, cf=1.0, d_s=None):
    probes = {"d_s": (d_s, 0.01)} if d_s is not None else {}
    return Rung(n=n, mean_degree=md, connected_fraction=cf, probes=probes, seeds_measured=3)


def replays(law, rungs, decision, policy=POLICY):
    row = json.loads(json.dumps(decision.as_dict() | {"inputs": decision_inputs(law, rungs, policy)}, default=str))
    verdict = replay_matches(dict(row, facts_json=json.dumps(decision.facts, default=str)))
    assert verdict["matches"] and verdict["same_rules"], verdict
    return True


def test_a_salted_empty_law_gets_one_rung_and_stops_where_it_is_still_empty():
    law = only("empty")
    first = decide(law, [rung(64, md=0.0), rung(256, md=0.01)], POLICY)
    assert (first.action, first.rule, first.next_n) == (RUN_NEXT, "base_block", 1024)
    assert first.facts["salted"] == ["empty"] and "salt_spent" not in first.facts
    still = [rung(64, md=0.0), rung(256, md=0.01), rung(1024, md=0.02)]
    spent = decide(law, still, POLICY)
    assert (spent.action, spent.rule) == (STOP, "empty")
    assert spent.facts["salt_spent"] == {"gate": "empty", "salted_at": 256, "held_at": 1024}
    assert "the salt's one rung is spent" in spent.reason
    assert replays(law, still, spent)


def test_a_verdict_whose_reading_changed_at_the_salt_s_rung_lets_the_law_go_on():
    law = only("too_dense")
    assert decide(law, [rung(64, md=17.0), rung(256, md=17.0)], POLICY).facts["salted"] == ["too_dense"]
    thinned = decide(law, [rung(64, md=17.0), rung(256, md=17.0), rung(1024, md=9.0)], POLICY)
    assert (thinned.action, thinned.rule) == (RUN_NEXT, "base_block") and "salt_spent" not in thinned.facts
    assert "salted" not in thinned.facts, "under the cap it is not salted past anything"
    again = decide(law, [rung(64, md=17.0), rung(256, md=17.0), rung(1024, md=9.0), rung(4096, md=18.0)], POLICY)
    assert again.rule != "too_dense" and again.facts["salted"] == ["too_dense"] and "salt_spent" not in again.facts


def test_disconnection_is_judged_the_same_way():
    law = only("disconnected")
    rungs = [rung(64, cf=0.3), rung(256, cf=0.3), rung(1024, cf=0.3)]
    assert decide(law, rungs, POLICY).facts["salted"] == ["disconnected"]
    spent = decide(law, rungs + [rung(4096, cf=0.3)], POLICY)
    assert (spent.action, spent.rule) == (STOP, "disconnected") and spent.facts["salt_spent"]["salted_at"] == 1024
    grew = decide(law, rungs + [rung(4096, cf=0.45)], POLICY)
    assert grew.rule != "disconnected", "a component growing is a reading that changed"


def test_an_unsalted_law_stops_at_the_first_firing_as_before():
    plain = G.unsalted_law("law-", POLICY.audit_fraction)
    assert decide(plain, [rung(64, md=0.0), rung(256, md=0.01)], POLICY).rule == "empty"
    assert decide(plain, [rung(64, md=17.0), rung(256, md=17.0)], POLICY).rule == "too_dense"


def test_a_withholding_gate_s_salt_is_spent_when_the_same_gate_withholds_again():
    law = only("no_reading")
    base = [rung(64), rung(256), rung(1024), rung(4096)]
    gated = decide(law, base, POLICY)
    assert (gated.action, gated.rule) == (STOP, "nothing_read"), "782: a law that read nothing meets the first gate"
    assert gated.facts["refused"]["rule"] == "salted"
    first = decide(law, base, NO_FIRST_GATE)
    assert (first.action, first.rule, first.next_n) == (RUN_NEXT, "salted", 16384)
    assert first.facts["salted_from"]["rule"] == "no_reading"
    spent = decide(law, base + [rung(16384)], NO_FIRST_GATE)
    assert (spent.action, spent.rule) == (STOP, "no_reading") and spent.facts["salt_spent"]["held_at"] == 16384
    assert replays(law, base + [rung(16384)], spent, NO_FIRST_GATE)
    read = decide(law, base + [rung(16384, d_s=1.5)], NO_FIRST_GATE)
    assert (read.action, read.rule) == (STOP, "unsettled_twice") and "salt_spent" not in read.facts


def test_the_gates_say_what_the_salt_buys():
    assert G.gate_of("longer_chain") == "no_reading" and G.gate_of("empty") == "empty"
    assert HOLD == "hold"
