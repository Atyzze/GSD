from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import known_result
from graph_scale_dynamics.decisions.engine import DONE, RUN_NEXT, STOP, Policy, Rung, decide
from graph_scale_dynamics.decisions.every_chain import decide_every_chain
from graph_scale_dynamics.decisions.let_through import Ledger, ledger_from_rows

RULE = Policy(let_through_rule=G.LET_THROUGH_RULE, known_result_after=100)


def _row(law, n, action, rule, salted=(), signature=None, at=[0]):
    at[0] += 1
    return {"campaign_id": "1", "candidate_id": law, "decision_id": f"{at[0]:020d}-x", "at_n": n, "action": action,
            "rule": rule, "salted": list(salted), "signature": signature}


def test_a_let_through_is_judged_one_size_up():
    ledger = ledger_from_rows([
        _row("a", 64, "run_next", "base_block", ["empty"]),
        _row("a", 256, "run_next", "base_block", ["empty"]),
        _row("a", 1024, "run_next", "base_block"),
    ])
    doc = ledger.document(RULE)["gates"]["empty"]
    assert doc["64"]["clean"] == 1 and doc["64"]["same_gate"] == 1 and doc["64"]["missed"] == 0
    assert doc["256"]["missed"] == 1 and doc["256"]["clean_since_last_miss"] == 0
    assert doc["64"]["label"] == "records only"


def test_a_gate_clamps_after_its_run_of_clean_and_a_miss_resets_it():
    rows = []
    for i in range(100):
        rows += [_row(f"l{i}", 4096, "run_next", "salted", ["starts_alike"]),
                 _row(f"l{i}", 16384, "stop", "starts_alike")]
    ledger = ledger_from_rows(rows)
    assert ledger.share("starts_alike", 4096, RULE) == G.CONFIRMED_SHARE
    assert ledger.share("starts_alike", 16384, RULE) == G.TESTING_SHARE
    assert ledger.share("empty", 256, RULE) == G.RECORD_ONLY
    ledger.feed(_row("miss", 4096, "run_next", "salted", ["starts_alike"]))
    ledger.feed(_row("miss", 16384, "run_next", "starts_shape"))
    assert ledger.share("starts_alike", 4096, RULE) == G.TESTING_SHARE


def test_a_failed_rung_and_the_top_judge_nothing():
    ledger = ledger_from_rows([
        _row("a", 4096, "run_next", "salted", ["empty"]), _row("a", 16384, "stop", "failed"),
        _row("b", 65536, "run_next", "salted", ["empty"]), _row("b", 262144, "done", "ladder_complete"),
    ])
    doc = ledger.document(RULE)["gates"]["empty"]
    assert doc["4096"]["open"] == 1 and doc["65536"]["open"] == 1


def test_the_draw_is_a_size_at_a_time_and_the_base_block_records_only():
    policy = replace(RULE, salt_shares=())
    laws = [f"law{i}" for i in range(4000)]
    assert all(policy.let_through(law, "empty", 256) for law in laws[:50])
    at_4096 = {law for law in laws if policy.let_through(law, "empty", 4096)}
    at_16384 = {law for law in laws if policy.let_through(law, "empty", 16384)}
    assert 300 < len(at_4096) < 500 and 300 < len(at_16384) < 500
    assert len(at_4096 & at_16384) < 80, "one draw a size: the same law is not let through at every size"
    clamped = replace(policy, salt_shares=(("empty", 4096, G.CONFIRMED_SHARE),))
    assert sum(clamped.let_through(law, "empty", 4096) for law in laws) < 80


def _rung(n, degree, connected=1.0, d=None):
    return Rung(n=n, mean_degree=degree, connected_fraction=connected,
                probes=({"d_V": (d, 0.01), "d_s": (d, 0.01)} if d is not None else {}))


def test_an_empty_law_runs_the_base_block_and_is_recorded():
    rungs = [_rung(64, 0.0), _rung(256, 0.0), _rung(1024, 0.0)]
    decision = decide("law", rungs, RULE)
    assert decision.action == RUN_NEXT and decision.next_n == 4096
    assert decision.facts.get("salted") == ["empty"]
    assert "spent" not in decision.reason


def test_a_chain_that_completes_the_ladder_names_the_law():
    policy = replace(RULE, base_sizes=(64, 256, 1024, 4096), deep_sizes=(16384,), every_chain=True,
                     promising_bar=False)
    empty = [_rung(n, 0.0) for n in (64, 256, 1024, 4096, 16384)]
    square = [_rung(n, 4.0, d=2.0) for n in (64, 256, 1024, 4096, 16384)]
    salted_off = replace(policy, salt_shares=(("empty", 16384, 0.0),))
    decision = decide_every_chain("never-let-through", {"empty": empty, "square": square}, salted_off)
    assert decision.action == DONE and decision.rule == "ladder_complete"


def test_a_signature_known_result_parks_a_law_that_would_go_on():
    chains = {"empty": [_rung(4096, 2.0, d=1.0)], "square": [_rung(4096, 4.0, d=2.0)]}
    found = known_result.signature(chains, {"fates": {"square": ["holds", True]}}, RULE, 4096)
    assert found == "empty:k2 d1|square:k4 d2 holds"
    from graph_scale_dynamics.decisions.engine import Decision
    going = Decision(law="x", action=RUN_NEXT, rule="starts_shape", reason="r", at_n=4096, next_n=16384)
    unseen = known_result.gate("x", going, chains, {"fates": {"square": ["holds", True]}}, RULE)
    assert unseen.action == RUN_NEXT and unseen.facts["signature"] == found
    seen = replace(RULE, known_results=((4096, found),), salt_shares=(("repeats_a_known_result", 4096, 0.0),))
    parked = known_result.gate("x", going, chains, {"fates": {"square": ["holds", True]}}, seen)
    assert parked.action == STOP and parked.rule == "repeats_a_known_result"


def test_known_result_counts_laws_that_kept_their_signature():
    ledger = Ledger()
    for i in range(100):
        ledger.feed(_row(f"r{i}", 4096, "run_next", "starts_shape", signature="ring"))
        ledger.feed(_row(f"r{i}", 16384, "run_next", "starts_shape", signature="ring"))
    assert ledger.known_results(RULE) == ((4096, "ring"),)
    assert ledger.known_results(replace(RULE, known_result_after=0)) == ()


def test_gates_from_256_leave_known_result_from_4096():
    gated = replace(RULE, let_through_from=256, known_result_from=4096)
    assert (gated.live_share("empty", 256), gated.live_share("empty", 64)) == (G.TESTING_SHARE, G.RECORD_ONLY)
    chains = {"empty": [_rung(1024, 2.0, d=1.0)], "square": [_rung(1024, 4.0, d=2.0)]}
    from graph_scale_dynamics.decisions.engine import Decision
    going = Decision(law="x", action=RUN_NEXT, rule="base_block", reason="r", at_n=1024, next_n=4096)
    found = known_result.signature(chains, None, gated, 1024)
    seen = replace(gated, known_results=((1024, found),), salt_shares=(("repeats_a_known_result", 1024, 0.0),))
    kept = known_result.gate("x", going, chains, None, seen)
    assert kept.action == RUN_NEXT and "signature" not in (kept.facts or {})
    assert known_result.gate("x", going, chains, None, replace(seen, known_result_from=0)).rule == "repeats_a_known_result"
    ledger = Ledger()
    for i in range(100):
        ledger.feed(_row(f"g{i}", 1024, "run_next", "base_block", signature="ring"))
        ledger.feed(_row(f"g{i}", 4096, "run_next", "base_block", signature="ring"))
    assert ledger.known_results(gated) == () and ledger.known_results(replace(gated, known_result_from=0))
    assert ledger.document(gated)["known_result_from"] == 4096


def test_known_result_from_left_at_its_default_moves_no_fingerprint():
    from graph_scale_dynamics.decisions.engine import policy_fingerprint
    assert policy_fingerprint(RULE) == policy_fingerprint(replace(RULE, known_result_from=0))
    assert policy_fingerprint(RULE) != policy_fingerprint(replace(RULE, known_result_from=4096))
    assert RULE.known_result_size() == 4096 and replace(RULE, let_through_from=256).known_result_size() == 256


def test_every_gate_at_half_draws_each_law_s_arm_once_for_the_gate():
    ab = replace(RULE, let_through_from=256, ab_share=0.5)
    assert ab.live_share("starts_alike", 4096) == 0.5 and ab.live_share("empty", 256) == 0.5
    assert ab.live_share("empty", 64) == G.RECORD_ONLY
    for gate in ("empty", "starts_alike", "kept_shape"):
        arms = [ab.let_through(f"law{i}", gate, 4096) for i in range(2000)]
        assert 900 < sum(arms) < 1100, (gate, sum(arms))
        for i in range(200):
            assert {ab.let_through(f"law{i}", gate, n) for n in (256, 1024, 4096, 16384, 65536, 262144)} == {arms[i]}, (
                "a law's arm is the same at every size: the halves do not compound")
    ledger = Ledger()
    for i in range(150):
        ledger.feed(_row(f"e{i}", 4096, "run_next", "base_block", ["empty"]))
        ledger.feed(_row(f"e{i}", 16384, "stop", "empty"))
    assert ledger.share("empty", 4096, ab) == 0.5, "no gate confirms under A/B"
    doc = ledger.document(ab)
    assert doc["gates"]["empty"]["4096"]["label"] == "A/B" and doc["ab_share"] == 0.5
    from graph_scale_dynamics.decisions.engine import let_through_text
    assert "B arm" in let_through_text("empty", 0.5, ab) and "drawn a size at a time" in let_through_text(
        "empty", 0.1, RULE)


def test_no_a_b_share_moves_no_fingerprint():
    from graph_scale_dynamics.decisions.engine import policy_fingerprint
    assert policy_fingerprint(RULE) == policy_fingerprint(replace(RULE, ab_share=0.0))
    assert policy_fingerprint(RULE) != policy_fingerprint(replace(RULE, ab_share=0.5))
    assert RULE.let_through("x", "empty", 4096) == replace(RULE, ab_share=0.0).let_through("x", "empty", 4096)


def test_the_ledger_counts_what_each_gate_held_back_once_and_names_every_gate_s_kind():
    ab = replace(RULE, let_through_from=256, ab_share=0.5)
    ledger = Ledger()
    for i in range(10):
        ledger.feed(_row(f"h{i}", 16384, "stop", "empty"))
        ledger.feed(_row(f"h{i}", 16384, "stop", "empty"))
    ledger.feed(_row("p", 16384, "stop", "ladder_complete"))
    doc = ledger.document(ab)
    assert doc["gates"]["empty"]["16384"]["held"] == 10, "a law held back twice at one size counts once"
    assert "ladder_complete" not in doc["gates"], "an end that is not a gate's verdict is not a gate"
    about = doc["about"]
    assert about["empty"]["kind"] == "fact" and about["starts_alike"]["kind"] == "judgment"
    assert about["kept_shape"]["kind"] == "class" and about["kept_shape"]["let_through"]
    assert not about["failed"]["let_through"] and about["empty"]["order"] < about["starts_alike"]["order"]
    assert set(about) == {gate.name for gate in G.GATES}


def test_a_gate_is_judged_by_what_it_let_through_that_scored_and_a_bundle_lists_those_laws():
    rows = [_row(law, 4096, "run_next", "dimension_shows", ["starts_alike"]) for law in ("a", "b", "c")]
    rows += [_row("d", 4096, "stop", "starts_alike")]
    ledger = ledger_from_rows(rows)
    plain = ledger.document(RULE)["gates"]["starts_alike"]["4096"]
    assert "scored" not in plain and "laws" not in plain, "without scores the ledger says nothing of them"
    scores = {("1", "a"): 71, ("1", "b"): 0, ("1", "d"): 9, ("2", "c"): 30}
    entry = ledger.document(RULE, scores=scores, laws=True)["gates"]["starts_alike"]["4096"]
    assert (entry["let_through"], entry["held"], entry["scored"], entry["best_score"]) == (3, 1, 1, 71.0)
    assert entry["best_law"] == ["1", "a"], "a held-back law's score and another campaign's law are not counted"
    assert entry["laws"] == ["1:a", "1:b", "1:c"]
