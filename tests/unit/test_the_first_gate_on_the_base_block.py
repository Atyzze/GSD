from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import every_chain as EC
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import nothing_read as NR
from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import (
    PARKING_RULES, RUN_NEXT, STOP, Decision, Policy, Rung, decide, policy_fingerprint)
from graph_scale_dynamics.decisions.replay import replay_matches

GATED = Policy(every_chain=True, nothing_read_gate=True, audit_fraction=0.5)
BASE = (64, 256, 1024, 4096)


def rung(n, probes=None, md=3.0):
    return Rung(n=n, mean_degree=md, connected_fraction=1.0, probes=dict(probes or {}), seeds_measured=3)


def chain(read_at=None, probe="d_V", upto=4096):
    return [rung(n, {probe: (2.0, 0.05)} if n == read_at else {}) for n in (*BASE, 16384) if n <= upto]


def law_of(salted: bool, start: int = 0) -> str:
    i = start
    while G.salted(f"law-{i}", NR.GATE, GATED.salt_share(NR.GATE, 4096)) != salted:
        i += 1
    return f"law-{i}"


def apart(*sizes) -> dict:
    names = ["empty", "random", "square", "cubic"]
    return {"class": "remembers", "at_n": sizes[-1], "top_n": sizes[-1], "top_dense": False,
            "by_n": {str(n): ["remembers", [names]] for n in sizes}, "fates": {}, "references": True}


APART = apart(1024, 4096)


def chains_of(*read_ats, upto=4096):
    names = ["empty", "random", "square", "cubic"]
    return {name: chain(read_at, upto=upto) for name, read_at in zip(names, read_ats, strict=True)}


def test_a_law_no_chain_of_which_read_anything_is_parked_at_the_top_of_the_base_block():
    law = law_of(False)
    bought = EC.decide_every_chain(law, chains_of(None, None, None, None), replace(GATED, nothing_read_gate=False),
                                   starts_reading=APART)
    assert bought.action == RUN_NEXT and bought.rule == "starts_apart" and bought.next_n == 16384
    decision = EC.decide_every_chain(law, chains_of(None, None, None, None), GATED, starts_reading=APART)
    assert decision.action == STOP and decision.rule == NR.GATE and decision.rule in PARKING_RULES
    assert decision.at_n == 4096 and decision.next_n is None
    facts = decision.facts["nothing_read"]
    assert facts["from_n"] == 64 and facts["sizes"] == list(BASE) and facts["chains"] == ["cubic", "empty", "random", "square"]
    assert decision.facts["refused"]["next_n"] == 16384, "what the other rules would have bought is kept"


def test_one_reading_on_any_chain_at_any_size_of_the_base_block_lets_the_law_go_on_as_the_rules_say():
    law = law_of(False)
    off = EC.decide_every_chain(law, chains_of(None, None, None, 64), replace(GATED, nothing_read_gate=False),
                                starts_reading=APART)
    for read_at in BASE:
        on = EC.decide_every_chain(law, chains_of(None, None, None, read_at), GATED, starts_reading=APART)
        assert on.rule == "starts_apart" and "nothing_read" not in on.facts
    assert EC.decide_every_chain(law, chains_of(None, 256, None, None), GATED, starts_reading=APART).rule == off.rule


def test_from_n_leaves_the_small_sizes_out_when_a_design_says_so():
    law = law_of(False)
    from_1024 = replace(GATED, nothing_read_from_n=1024)
    assert EC.decide_every_chain(law, chains_of(None, None, 256, None), from_1024, starts_reading=APART).rule == NR.GATE
    assert EC.decide_every_chain(law, chains_of(None, None, 1024, None), from_1024, starts_reading=APART).rule != NR.GATE


def test_the_gate_is_on_unless_a_design_turns_it_off():
    from graph_scale_dynamics.decisions.replay import policy_from_inputs
    law = law_of(False)
    assert Policy().nothing_read_gate is True and Policy().nothing_read_from_n == 64
    off = Policy(every_chain=True, audit_fraction=0.5, nothing_read_gate=False)
    assert EC.decide_every_chain(law, chains_of(None, None, None, None), off, starts_reading=APART).rule != NR.GATE
    assert policy_fingerprint(off) != policy_fingerprint(GATED)
    assert policy_from_inputs({"nothing_read_gate": True}).nothing_read_gate is True


def test_the_let_through_goes_one_rung_on_and_parks_where_it_reads_nothing_again():
    law = law_of(True)
    through = EC.decide_every_chain(law, chains_of(None, None, None, None), GATED, starts_reading=APART)
    assert through.action == RUN_NEXT and through.rule == "starts_apart" and through.next_n == 16384
    assert NR.GATE in through.facts["salted"] and through.facts["nothing_read"]["salted"] is True
    deeper = chains_of(None, None, None, None, upto=16384)
    buys = Decision(law=law, action=RUN_NEXT, rule="starts_shape", reason="a shape", at_n=16384, next_n=65536,
                    priority=1)
    again = NR.gate(law, buys, deeper, GATED)
    assert again.action == STOP and again.rule == NR.GATE
    assert again.facts["salt_spent"] == {"gate": NR.GATE, "salted_at": 4096, "held_at": 16384}
    deeper["cubic"] = [*deeper["cubic"][:-1], rung(16384, {"d_s": (3.0, 0.05)})]
    assert NR.gate(law, buys, deeper, GATED) is buys, "a reading at 16,384 is what the let-through finds"


def test_the_let_through_draws_with_the_gate_s_own_name():
    shares = [GATED.salt_share(NR.GATE, 4096)] * 400
    ours = [G.salted(f"law-{i}", NR.GATE, share) for i, share in enumerate(shares)]
    for other in G.SALTED_GATES - {NR.GATE}:
        assert ours != [G.salted(f"law-{i}", other, share) for i, share in enumerate(shares)]
    assert NR.GATE in G.SALTED_GATES and G.BY_NAME[NR.GATE].salted


def test_a_law_decided_by_its_chain_from_empty_alone_meets_the_gate_too():
    law = law_of(False)
    gated = Policy(nothing_read_gate=True, audit_fraction=0.5)
    i = 0
    while not (G.salted(f"law-{i}", "no_reading", 0.5) and not G.salted(f"law-{i}", NR.GATE, 0.5)):
        i += 1
    law = f"law-{i}"
    plain = decide(law, chain(None), replace(gated, nothing_read_gate=False))
    assert plain.rule == "salted" and plain.facts["salted"] == ["no_reading"] and plain.next_n == 16384
    decision = decide(law, chain(None), gated)
    assert decision.rule == NR.GATE and decision.facts["nothing_read"]["chains"] == ["empty"]


def test_a_decision_the_gate_made_replays_from_its_inputs():
    for salted in (False, True):
        law = law_of(salted)
        chains = chains_of(None, None, None, None)
        decision = EC.decide_every_chain(law, chains, GATED, starts_reading=APART)
        inputs = decision_inputs(law, chains["empty"], GATED, starts_reading=APART,
                                 chains={name: rungs for name, rungs in chains.items() if name != "empty"})
        row = dict(decision.as_dict(), inputs=inputs)
        assert replay_matches(row)["matches"] is True, replay_matches(row)["differences"]
