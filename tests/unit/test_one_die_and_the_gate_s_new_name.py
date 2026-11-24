from __future__ import annotations

from dataclasses import asdict, replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import let_through as LT
from graph_scale_dynamics.decisions.engine import Policy, policy_fingerprint
from graph_scale_dynamics.decisions.replay import policy_from_inputs

RULE = Policy(let_through_rule=G.LET_THROUGH_RULE, let_through_from=256)
LAWS = [f"law{i:04d}".ljust(64, "0") for i in range(2000)]


def test_one_die_lets_a_law_past_every_gate_at_a_size_together():
    one = replace(RULE, one_die=True)
    for law in LAWS[:400]:
        picks = {one.let_through(law, gate, 1024) for gate in ("empty", "disconnected", "too_dense", "starts_alike")}
        assert len(picks) == 1, law
    through = sum(one.let_through(law, "empty", 1024) and one.let_through(law, "disconnected", 1024) for law in LAWS)
    assert 150 < through < 250, f"about 10% of 2,000 through both, not 1%: {through}"
    apart = sum(RULE.let_through(law, "empty", 1024) and RULE.let_through(law, "disconnected", 1024) for law in LAWS)
    assert apart < 50, f"each gate's own die lets about 1% through both: {apart}"


def test_one_die_is_new_a_size_and_leaves_the_gates_own_dice_and_every_fingerprint_as_they_were():
    one = replace(RULE, one_die=True)
    assert [G.die(law, None, 1024) for law in LAWS[:20]] != [G.die(law, None, 4096) for law in LAWS[:20]]
    assert G.die(LAWS[0], "empty", 1024) == int(__import__("hashlib").sha256(
        f"let-through:empty:1024:{LAWS[0]}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    assert policy_fingerprint(one) != policy_fingerprint(RULE)
    assert policy_fingerprint(replace(RULE, one_die=False)) == policy_fingerprint(RULE)


def test_the_renamed_gate_draws_the_die_it_drew_as_seen_enough():
    for law in LAWS[:50]:
        assert G.die(law, "repeats_a_known_result", 4096) == int(__import__("hashlib").sha256(
            f"let-through:seen_enough:4096:{law}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def test_a_design_or_a_recorded_policy_in_the_former_names_is_read_in_today_s():
    former = {"let_through_rule": G.LET_THROUGH_RULE, "let_through_from": 256, "seen_enough_after": 100,
              "seen_enough_from": 256, "gate_shares": [["seen_enough", 1.0]],
              "seen_signatures": [[1024, "ring"]], "salt_shares": [["seen_enough", 1024, 0.01]]}
    policy = Policy.from_spec({"engine": {"policy": {k: v for k, v in former.items()
                                                    if k not in ("seen_signatures", "salt_shares")}}})
    assert (policy.known_result_after, policy.known_result_from) == (100, 256)
    assert policy.own_share("repeats_a_known_result") == 1.0 and LT.records_only(policy, LT.KNOWN_RESULT, 1024)
    recorded = policy_from_inputs(former)
    assert recorded.known_results == ((1024, "ring"),)
    assert recorded.live_share("repeats_a_known_result", 1024) == 1.0
    today = dict(asdict(recorded), gate_shares=[["repeats_a_known_result", 1.0]])
    assert policy_fingerprint(policy_from_inputs(today)) != policy_fingerprint(recorded), (
        "a design that names the gate today is its own design")
    assert LT.salted_of({"salted": ["seen_enough", "empty"]}) == ["repeats_a_known_result", "empty"]


def test_a_fingerprint_is_what_it_was_before_the_fields_were_renamed():
    policy = replace(RULE, known_result_after=100, known_result_from=4096)
    import hashlib
    from graph_scale_dynamics.decisions.engine import ENGINE_VERSION, LIVE_FIELDS, SET_FIELDS, rules_revision
    unset = {key for key, default in SET_FIELDS if getattr(policy, key) == default}
    former = {"known_result_after": "seen_enough_after", "known_result_from": "seen_enough_from",
              "known_results": "seen_signatures"}
    items = {former.get(key, key): value for key, value in asdict(policy).items()
             if not (policy.let_through_rule and key in LIVE_FIELDS) and key not in unset}
    payload = "|".join([ENGINE_VERSION, str(rules_revision(policy))]
                       + [f"{key}={value!r}" for key, value in sorted(items.items())])
    assert policy_fingerprint(policy) == hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def test_a_recorded_decision_is_read_in_today_s_words():
    from graph_scale_dynamics.decisions import known_result
    assert known_result.GATE == "repeats_a_known_result"
    words = G.in_today_s_words({"rule": "seen_enough", "salted": ["seen_enough"], "seen_enough": {"x": 1},
                                "seen_enough_after": 3, "reason": "let through past seen_enough: it repeats"})
    assert words == {"rule": "repeats_a_known_result", "salted": ["repeats_a_known_result"],
                     "repeats_a_known_result": {"x": 1}, "seen_enough_after": 3,
                     "reason": "let through past repeats_a_known_result: it repeats"}
    assert G.today("seen_enough") == "repeats_a_known_result" and G.today("empty") == "empty"
    assert G.in_today_s_words("seen enough: 100 laws kept it; parked") == "repeats a known result: 100 laws kept it; parked"
