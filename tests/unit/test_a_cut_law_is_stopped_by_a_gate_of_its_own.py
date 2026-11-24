from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import cut
from graph_scale_dynamics.decisions import depth
from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import nothing_read as NR
from graph_scale_dynamics.decisions.decider import decision_inputs
from graph_scale_dynamics.decisions.engine import (
    HOLD, OVER_BUDGET, PARKING_RULES, RUN_NEXT, STOP, Decision, Policy, Rung, Seed, decide, policy_fingerprint)
from graph_scale_dynamics.decisions.every_chain import decide_every_chain
from graph_scale_dynamics.decisions.let_through import Ledger, ledger_from_rows
from graph_scale_dynamics.decisions.replay import policy_from_inputs, replay_matches

LAW = "7" * 64
BUDGETS = ((64, 400), (256, 400), (1024, 400), (4096, 1600))
RULE = Policy(let_through_rule=G.LET_THROUGH_RULE, let_through_from=256, one_die=True, work_budgets=BUDGETS)
OFF = RULE
CLOSED = replace(RULE, cut_gate=True, gate_shares=(("cut", 0.0),))
OPEN = replace(RULE, cut_gate=True, gate_shares=(("cut", 1.0),))
TENTH = replace(RULE, cut_gate=True, gate_shares=(("cut", 0.1),))


def _seed(termination="completed", units=100, chunk=20, moves=1000):
    return Seed(termination=termination, work_units=units, moves=moves, first_chunk_units=chunk, first_chunk_moves=moves,
                first_multiplier=1, final_multiplier=1, work_budget=400)


def _rungs(cut_at=256, cut_seeds=(0, 2), sizes=(64, 256), chunk=20):
    return [Rung(n=n, mean_degree=3.0 + 0.1 * index, connected_fraction=1.0, probes={}, seeds_measured=3,
                 seeds=tuple(_seed("budget" if n == cut_at and i in cut_seeds else "completed", chunk=chunk)
                             for i in range(3)))
            for index, n in enumerate(sizes)]


def test_the_gate_is_a_named_operational_gate_and_a_design_asks_for_it():
    gate = G.BY_NAME["cut"]
    assert dict(G.KINDS)["operational"] == ("failed", "over_budget", "cut") and gate.stage == "operational" and gate.salted
    assert "cut" in G.LET_THROUGH_GATES and "cut" in PARKING_RULES
    assert Policy().cut_gate is False and not Policy().asks_for("cut") and Policy().asks_for("empty")
    assert RULE.live_share("cut", 4096) == G.RECORD_ONLY == Ledger().share("cut", 4096, RULE), "172's: no cut gate"
    assert TENTH.live_share("cut", 4096) == 0.1 == Ledger().share("cut", 4096, TENTH)
    assert TENTH.live_share("cut", 64) == G.RECORD_ONLY, "below let_through_from every verdict is recorded only"
    assert policy_fingerprint(replace(RULE, cut_gate=True)) != policy_fingerprint(RULE)
    assert policy_fingerprint(policy_from_inputs({key: value for key, value in decision_inputs(LAW, [], RULE)["policy"]
                                                  .items() if key != "cut_gate"})) == policy_fingerprint(RULE), (
        "a decision recorded before 841 has no cut_gate and replays under the same fingerprint")


def test_a_design_without_the_gate_lets_a_cut_law_go_on_as_172_did():
    decision = decide(LAW, _rungs(), OFF)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "base_block", 1024)
    assert "cut" not in (decision.facts or {}) and "salted" not in (decision.facts or {})


def test_a_law_with_a_cut_seed_is_stopped_at_the_size_it_was_cut_at():
    decision = decide(LAW, _rungs(), CLOSED)
    assert (decision.action, decision.rule, decision.at_n, decision.next_n) == (STOP, "cut", 256, None)
    assert decision.facts["cut"] == {"contract": cut.CONTRACT, "at_n": 256, "seeds": [0, 2], "of": 3}
    assert decision.facts["refused"] == {"action": RUN_NEXT, "rule": "base_block", "next_n": 1024, "priority": 3} or (
        decision.facts["refused"]["rule"] == "base_block" and decision.facts["refused"]["next_n"] == 1024)
    assert decision.reason.startswith("2 of its 3 seeds at N=256 ran out of their budget in work before they settled")
    assert "everything it measured kept" in decision.reason
    assert decide(LAW, _rungs(cut_at=None), CLOSED).rule == "base_block", "no cut seed, no stop"
    assert decide(LAW, _rungs(cut_at=64), CLOSED).rule == "base_block", "a cut at a size below is that size's verdict"


def test_a_let_through_goes_on_with_the_verdict_recorded():
    decision = decide(LAW, _rungs(), OPEN)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "base_block", 1024)
    assert decision.facts["salted"] == ["cut"] and decision.facts["cut"]["salted"] is True
    assert decision.facts["cut"]["seeds"] == [0, 2] and "let through past cut, which would park it" in decision.reason


def test_a_tenth_of_the_cut_laws_go_on_and_the_pick_is_the_law_s_one_die_at_the_size():
    laws = [f"{i:064x}" for i in range(3000)]
    on = [law for law in laws if decide(law, _rungs(), TENTH).action == RUN_NEXT]
    assert 0.08 < len(on) / len(laws) < 0.12
    assert all(TENTH.let_through(law, "cut", 256) for law in on)
    assert {law for law in laws if TENTH.let_through(law, "cut", 256)} == {
        law for law in laws if replace(TENTH, gate_shares=(("cut", 0.1), ("empty", 0.1))).let_through(law, "empty", 256)}, (
        "one die a law a size: the gates read the same pick")
    assert all(decide(law, _rungs(cut_at=64, sizes=(64,)), TENTH).action == RUN_NEXT for law in laws[:200]), (
        "below let_through_from the verdict is recorded and every law goes on")


def test_a_longer_chain_at_the_same_size_is_stopped_too_and_a_rung_being_completed_is_not():
    rungs = _rungs(cut_at=4096, sizes=(64, 256, 1024, 4096))

    def asked(rule, next_n, action=RUN_NEXT):
        return Decision(law=LAW, action=action, rule=rule, reason="r", at_n=4096, next_n=next_n, priority=3, facts={})
    assert cut.gate(LAW, asked("longer_chain", 4096), rungs, CLOSED).rule == "cut"
    assert cut.gate(LAW, asked("starts_apart", 16384), rungs, CLOSED).rule == "cut"
    assert cut.gate(LAW, asked("no_plateau", 16384, HOLD), rungs, CLOSED).rule == "cut"
    assert cut.gate(LAW, asked("complete_rung", 4096), rungs, CLOSED).rule == "complete_rung"
    stopped = Decision(law=LAW, action=STOP, rule="empty", reason="r", at_n=4096, next_n=None, priority=None, facts={})
    assert cut.gate(LAW, stopped, rungs, CLOSED) is stopped, "a law another gate stops keeps that gate's name"


def test_the_stop_and_the_let_through_replay_from_their_recorded_inputs():
    for policy in (CLOSED, OPEN, OFF):
        decision = decide(LAW, _rungs(), policy)
        row = {"action": decision.action, "rule": decision.rule, "reason": decision.reason, "next_n": decision.next_n,
               "at_n": decision.at_n, "priority": decision.priority, "facts": decision.facts,
               "inputs": decision_inputs(LAW, _rungs(), policy)}
        found = replay_matches(row)
        assert found["matches"] and found["same_rules"], found


def test_on_every_chain_the_cut_comes_before_the_price_and_a_let_through_is_priced():
    chains = {"empty": _rungs(chunk=5000), "random": _rungs(cut_at=None, chunk=5000)}
    closed = replace(CLOSED, every_chain=True)
    stopped = decide_every_chain(LAW, chains, closed)
    assert (stopped.action, stopped.rule, stopped.at_n) == (STOP, "cut", 256)
    priced = decide_every_chain(LAW, chains, replace(OPEN, every_chain=True))
    assert (priced.action, priced.rule) == (STOP, OVER_BUDGET) and priced.facts["salted"] == ["cut"], (
        "the tenth let through past cut is priced as any law is, the gate's verdict kept on the stop")
    cheap = {"empty": _rungs(), "random": _rungs(cut_at=None)}
    assert decide_every_chain(LAW, cheap, replace(OPEN, every_chain=True)).action == RUN_NEXT
    assert decide_every_chain(LAW, cheap, replace(OFF, every_chain=True)).facts.get("salted") is None


def _row(law, n, action, rule, salted=(), at=[0]):
    at[0] += 1
    return {"campaign_id": "1", "candidate_id": law, "decision_id": f"{at[0]:020d}-x", "at_n": n, "action": action,
            "rule": rule, "salted": list(salted), "signature": None}


def test_the_ledger_counts_the_verdicts_of_a_law_stopped_over_budget_where_a_design_asks():
    rows = [_row("a", 1024, "run_next", "base_block", ["nothing_read"]),
            _row("a", 4096, "stop", "over_budget", ["nothing_read", "no_steady_chain"]),
            _row("b", 4096, "stop", "over_budget")]
    before = ledger_from_rows(rows).document(RULE)["gates"]
    assert before["nothing_read"]["1024"]["open"] == 1 and "4096" not in before["nothing_read"], "172's ledger"
    counting = replace(RULE, ledger_counts_priced=True)
    after = ledger_from_rows(rows, counting).document(counting)["gates"]
    assert after["nothing_read"]["1024"]["clean"] == 1 and after["nothing_read"]["1024"]["same_gate"] == 1
    assert after["nothing_read"]["1024"]["open"] == 0
    assert after["nothing_read"]["4096"]["held"] == 1 and after["no_steady_chain"]["4096"]["held"] == 1
    assert "over_budget" not in after, "the price is not a gate of the let-through rule; b's stop carries no verdict"
    assert policy_fingerprint(counting) != policy_fingerprint(RULE)


def test_a_budget_stop_is_held_against_a_gate_only_where_the_gate_acts():
    rows = [_row("c", 1024, "stop", "over_budget", ["cut", "nothing_read"]),
            _row("d", 4096, "stop", "over_budget", ["cut"])]
    recording = replace(OPEN, ledger_counts_priced=True)
    gates = ledger_from_rows(rows, recording).document(recording)["gates"]
    assert gates["cut"]["1024"]["label"] == "records only"
    assert (gates["cut"]["1024"]["held"], gates["cut"]["1024"]["priced"]) == (0, 1), "173: the budget held c, not cut"
    assert (gates["cut"]["4096"]["held"], gates["cut"]["4096"]["priced"]) == (0, 1)
    assert (gates["nothing_read"]["1024"]["held"], gates["nothing_read"]["1024"]["priced"]) == (1, 1)
    acting = replace(recording, gate_shares=(("cut", 0.1),))
    assert ledger_from_rows(rows, acting).document(acting)["gates"]["cut"]["1024"]["held"] == 1


def test_nothing_read_s_piece_is_a_share_of_the_graph_where_a_design_sets_it():
    share = replace(Policy(every_chain=True, nothing_read_gate=True), nothing_read_piece_share=0.9)
    assert NR.piece_nodes(4096) == NR.piece_nodes(4096, Policy()) == 4096.0
    assert abs(NR.piece_nodes(4096, share) - 3686.4) < 1e-9 and NR.piece_nodes(16384, share) == 4096.0

    def rungs(nodes):
        return [Rung(n=n, mean_degree=3.0 + 0.2 * index, connected_fraction=(nodes / 4096 if n == 4096 else 1.0),
                     probes={}, seeds_measured=3, valid_fractions=({"d_V": 1.0} if n == 4096 else {}))
                for index, n in enumerate((64, 256, 1024, 4096))]
    as_built = Policy(every_chain=True, nothing_read_gate=True)
    asked = Decision(law=LAW, action=RUN_NEXT, rule="starts_apart", reason="r", at_n=4096, next_n=16384, priority=3,
                     facts={})

    def gated(nodes, policy):
        return NR.gate(LAW, asked, {"empty": rungs(nodes)}, policy)
    for nodes in (3993, 4071):
        assert gated(nodes, as_built).rule == NR.GATE, "172: 4c5892bd611b and dfd97f6ae8c9 withheld"
        assert gated(nodes, share) is asked
    parked = gated(3600, share)
    assert parked.rule == NR.GATE and parked.facts["nothing_read"]["piece_share"] == 0.9
    assert "nor on a piece of 0.9 of the graph or of 4,096 nodes from N=4,096" in parked.reason
    assert "piece_share" not in gated(3600, as_built).facts["nothing_read"]
    assert "nor on a piece of 4,096 nodes or more" in gated(3600, as_built).reason


def test_a_longer_chain_is_weighed_against_the_design_s_scale_of_its_size_s_budget():
    asked = Decision(law=LAW, action=RUN_NEXT, rule="longer_chain", reason="r", at_n=4096, next_n=4096, priority=3,
                     facts={})
    assert depth.budget_scale(asked, RULE) == 1.0 and Policy().longer_chain_budget_scale == 1.0
    twice = replace(RULE, longer_chain_budget_scale=2.0)
    assert depth.budget_scale(asked, twice) == 2.0
    up = Decision(law=LAW, action=RUN_NEXT, rule="starts_apart", reason="r", at_n=4096, next_n=16384, priority=3,
                  facts={})
    assert depth.budget_scale(up, twice) == 1.0, "only the longer chain"
    assert policy_fingerprint(twice) != policy_fingerprint(RULE)
