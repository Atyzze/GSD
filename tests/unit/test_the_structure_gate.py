from __future__ import annotations

import json
import math
from pathlib import Path

from dataclasses import replace

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import structure_gate as SG
from graph_scale_dynamics.decisions.decider import decide_pass, decision_inputs
from graph_scale_dynamics.decisions.engine import (
    GATE_RULES, HOLD, RULES_REVISION, RUN_NEXT, STOP, Policy, Rung, decide, policy_fingerprint)
from graph_scale_dynamics.decisions.replay import replay_matches
from tests.unit.test_decider import FakeStore, entry

ROOT = Path(__file__).resolve().parents[2]
POLICY = Policy(plateau_follow_in_flight=0, promising_bar=False, deep_salt_at_most=0.10)
LADDER = POLICY.ladder()
PLAIN = G.unsalted_law("law-", POLICY.audit_fraction)
SALTED = next(f"law-{i}" for i in range(20000)
              if G.salted(f"law-{i}", "no_finite_dimension", POLICY.audit_fraction)
              and not any(G.salted(f"law-{i}", gate, POLICY.audit_fraction)
                          for gate in G.SALTED_GATES - {"no_finite_dimension"}))


def two_d(n):
    return {"gap": 4.0 / n, "diameter": n ** 0.5}


def expander(n):
    return {"gap": 0.2, "diameter": 3.0 * math.log(n)}


def chain(geometry, n, **over):
    return {"seeds": 3, "giant": 1.0, "gap_reason": None} | geometry(n) | over


def structure(n, from_empty=two_d, given=None, *, flags=None, from_empty_over=None, given_over=None):
    return {"empty": chain(from_empty, n, **(from_empty_over or {})),
            "given": chain(given or from_empty, n, **(given_over or {})),
            "log_diameter": flags or {"raised": 0, "false": 3, "unknown": 0, "not_measured": 0}}


def rungs(top, from_empty=two_d, given=None, *, settled=True, d_s=1.5, mean_degree=2.5, others=(), per_n=None):
    out = []
    sizes = [n for n in LADDER if n <= top]
    for i, n in enumerate(sizes):
        value = d_s if settled or i < len(sizes) - 1 else d_s + 0.4
        probes = {"d_s": (value, 0.01)} | {p: (1.0, 0.01) for p in others}
        s = structure(n, from_empty, given, **((per_n or {}).get(n) or {}))
        out.append(Rung(n=n, mean_degree=mean_degree, connected_fraction=1.0, probes=probes, seeds_measured=3,
                        structure=s))
    return out


def replays(law, law_rungs, decision, gate=None, policy=POLICY):
    inputs = decision_inputs(law, law_rungs, policy, gate=gate)
    row = json.loads(json.dumps(decision.as_dict() | {"inputs": inputs}, default=str))
    verdict = replay_matches(dict(row, facts_json=json.dumps(decision.facts, default=str)))
    assert verdict["matches"] and verdict["same_rules"], verdict
    return True


def test_the_rule_is_the_committed_table_and_the_rules_revision_moved():
    table = json.loads((ROOT / "graph_scale_dynamics/resources/calibration/structure_thresholds.json")
                       .read_text(encoding="utf-8"))
    survey = Policy.from_spec(json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json")
                                         .read_text(encoding="utf-8")))
    assert survey.gap_exponent_at_most == table["thresholds"]["gap_exponent_at_most"]
    assert survey.diameter_exponent_at_least == table["thresholds"]["diameter_exponent_at_least"]
    assert list(survey.gap_window) == list(table["gap_window"])
    assert list(survey.diameter_window) == list(table["diameter_window"])
    assert Policy().gap_exponent_at_most == -0.3752, "census 2's number, for a campaign created before 629"
    assert RULES_REVISION >= 528, "a build that changes what a rule decides moves the rules revision"
    assert policy_fingerprint(Policy()) != policy_fingerprint(Policy(structure_gate=False))


def test_a_law_finite_on_both_chains_keeps_the_rung_its_rules_bought():
    law_rungs = rungs(65536)
    decision = decide(PLAIN, law_rungs, POLICY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    gate = decision.facts["gate"]
    assert gate["result"] == SG.FINITE and gate["stage"] == "full"
    assert abs(gate["chains"]["empty"]["implied_spectral_dimension"] - 2.0) < 0.01
    assert replays(PLAIN, law_rungs, decision)


def test_a_law_with_no_finite_dimension_on_either_chain_stops_with_everything_it_read():
    law_rungs = rungs(65536, expander)
    decision = decide(PLAIN, law_rungs, POLICY)
    assert (decision.action, decision.rule, decision.next_n) == (STOP, "no_finite_dimension", None)
    gate = decision.facts["gate"]
    assert gate["result"] == SG.NOT_FINITE and gate["refused"]
    assert gate["underlying"] == {"action": RUN_NEXT, "rule": "d_s_settled", "next_n": 262144,
                                  "reason": gate["underlying"]["reason"]}
    for name in SG.CHAINS:
        exponents = gate["chains"][name]["exponents"]
        assert exponents["gap"] > POLICY.gap_exponent_at_most and exponents["diameter"] < 0.1751
        assert exponents["gap_rungs"] == 3 and exponents["diameter_rungs"] == 3
    assert "no finite dimension on either chain" in decision.reason and "N=65,536" in decision.reason
    assert decision.facts["d_s_settled"], "the underlying decision's facts are kept"
    assert replays(PLAIN, law_rungs, decision)


def test_the_gate_only_refuses_a_hold_stays_a_hold_and_a_refused_hold_stops():
    held_rules = Policy(second_rung=False, promising_bar=False)
    finite = decide(PLAIN, rungs(65536, settled=False), held_rules)
    assert (finite.action, finite.rule) == (HOLD, "unsettled") and finite.facts["gate"]["result"] == SG.FINITE
    refused = decide(PLAIN, rungs(65536, expander, settled=False), held_rules)
    assert (refused.action, refused.rule) == (STOP, "no_finite_dimension")
    assert refused.facts["gate"]["underlying"]["action"] == HOLD
    audit = refused.facts["gate"]["audit"]
    assert not audit.get("full") and not audit.get("follow_full"), "a law held anyway loses nothing to the gate"
    for from_empty in (two_d, expander):
        parked = decide(PLAIN, rungs(65536, from_empty, settled=False), POLICY)
        assert (parked.action, parked.rule, parked.next_n) == (STOP, "no_second_rung", None)
        assert "gate" not in parked.facts


def test_given_chains_that_disagree_get_one_more_rung_once_then_are_refused():
    first = rungs(65536, two_d, expander)
    decision = decide(PLAIN, first, POLICY)
    assert (decision.action, decision.rule, decision.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert decision.facts["gate"]["result"] == SG.SPLIT and decision.facts["gate"]["one_more_rung"]
    assert replays(PLAIN, first, decision)
    second = rungs(262144, two_d, expander)
    again = decide(PLAIN, second, POLICY)
    assert (again.action, again.rule) == (STOP, "no_finite_dimension")
    assert "chains disagree on structure, twice" in again.reason
    assert again.facts["gate"]["twice"]["at_n"] == [65536, 262144]
    assert replays(PLAIN, second, again)


def test_an_undecidable_law_gets_one_more_rung_once_then_is_refused():
    unreadable = {n: {"from_empty_over": {"gap": None, "gap_reason": "no solve converged"},
                      "given_over": {"gap": None, "gap_reason": "no solve converged"}} for n in (16384, 65536)}
    first = rungs(65536, per_n=unreadable)
    decision = decide(PLAIN, first, POLICY)
    assert decision.action == RUN_NEXT and decision.facts["gate"]["result"] == SG.UNDECIDABLE
    assert decision.facts["gate"]["chains"]["empty"]["code"] == SG.GAP_UNREADABLE
    second = rungs(262144, per_n=unreadable)
    again = decide(PLAIN, second, POLICY)
    assert (again.action, again.rule) == (STOP, "no_finite_dimension") and "undecidable twice" in again.reason
    assert replays(PLAIN, second, again)


def test_a_fragmented_law_stops_as_no_giant_component():
    shards = {n: {"from_empty_over": {"giant": 0.3}, "given_over": {"giant": 0.3}} for n in (4096, 16384, 65536)}
    law_rungs = rungs(65536, per_n=shards)
    decision = decide(PLAIN, law_rungs, POLICY)
    assert (decision.action, decision.rule) == (STOP, "no_giant_component")
    assert "65,536" in decision.reason and decision.facts["gate"]["chains"]["empty"]["code"] == SG.GIANT_BELOW_HALF
    assert replays(PLAIN, law_rungs, decision)


def test_a_structure_that_changed_between_rungs_is_undecidable_not_refused():
    changed = {4096: {"from_empty_over": {"gap": 1e-4, "diameter": 40.0}, "given_over": {"gap": 1e-4, "diameter": 40.0}},
               16384: {"from_empty_over": {"gap": 3e-4, "diameter": 36.0}, "given_over": {"gap": 3e-4, "diameter": 36.0}},
               65536: {"from_empty_over": {"gap": 3e-3, "diameter": 34.0}, "given_over": {"gap": 3e-3, "diameter": 34.0}}}
    decision = decide(PLAIN, rungs(65536, per_n=changed), POLICY)
    assert decision.action == RUN_NEXT and decision.facts["gate"]["result"] == SG.UNDECIDABLE
    assert decision.facts["gate"]["chains"]["empty"]["code"] == SG.STRUCTURE_CHANGED


def test_a_log_diameter_flag_raised_or_unknown_does_not_pass():
    unknown = {65536: {"flags": {"raised": 0, "false": 2, "unknown": 1, "not_measured": 0}}}
    decision = decide(PLAIN, rungs(65536, per_n=unknown), POLICY)
    assert decision.action == RUN_NEXT and decision.facts["gate"]["result"] == SG.UNDECIDABLE
    assert decision.facts["gate"]["chains"]["empty"]["code"] == SG.LOG_DIAMETER_UNKNOWN
    raised = {65536: {"flags": {"raised": 1, "false": 2, "unknown": 0, "not_measured": 0}}}
    again = decide(PLAIN, rungs(65536, per_n=raised), POLICY)
    assert again.facts["gate"]["result"] == SG.UNDECIDABLE
    assert again.facts["gate"]["chains"]["empty"]["code"] == SG.LOG_DIAMETER_RAISED
    both = {n: {"flags": {"raised": 3, "false": 0, "unknown": 0, "not_measured": 0}} for n in (65536, 262144)}
    twice = decide(PLAIN, rungs(262144, per_n=both), POLICY)
    assert (twice.action, twice.rule) == (STOP, "no_finite_dimension") and "undecidable twice" in twice.reason
    decided = {65536: {"flags": {"raised": 0, "false": 3, "unknown": 0, "not_measured": 1}}}
    assert decide(PLAIN, rungs(65536, per_n=decided), POLICY).facts["gate"]["result"] == SG.FINITE, (
        "a seed whose flag was not measured is neither raised nor unknown")


def test_the_early_stage_reads_in_shadow_and_acts_only_on_the_switch_and_a_hundred_agreements():
    law_rungs = rungs(16384, expander)
    shadow = decide(PLAIN, law_rungs, POLICY)
    assert (shadow.action, shadow.rule, shadow.next_n) == (RUN_NEXT, "d_s_settled", 65536)
    gate = shadow.facts["gate"]
    assert gate["stage"] == "early" and gate["result"] == "would refuse" and not gate["acting"]
    short = {"early_stage_switch": True, "early_agreements": 99}
    assert decide(PLAIN, law_rungs, POLICY, gate=short).action == RUN_NEXT
    acting = {"early_stage_switch": True, "early_agreements": 100}
    refused = decide(PLAIN, law_rungs, POLICY, gate=acting)
    assert (refused.action, refused.rule) == (STOP, "no_finite_dimension") and "the clear case" in refused.reason
    assert replays(PLAIN, law_rungs, refused, gate=acting)
    assert decide(PLAIN, rungs(16384), POLICY, gate=acting).facts["gate"]["result"] == "not a clear case"


def test_the_full_rule_records_whether_the_shadow_would_have_agreed():
    agreed = decide(PLAIN, rungs(65536, expander), POLICY).facts["gate"]["early"]
    assert agreed == {"would_refuse": True, "agrees": True, "disagrees": False}
    finite = decide(PLAIN, rungs(65536), POLICY).facts["gate"]["early"]
    assert finite == {"would_refuse": False, "agrees": False, "disagrees": False}
    assert "early" not in decide(PLAIN, rungs(262144), POLICY).facts["gate"], "counted once, at 65,536"


def test_the_gate_s_salt_buys_one_rung_judged_by_its_own_reading_there_and_audits_near_misses_four_at_once():
    share = sum(G.salted(f"law-{i}", "no_finite_dimension", POLICY.audit_fraction) for i in range(20000)) / 20000
    assert 0.09 < share < 0.11
    law_rungs = rungs(65536, expander)
    salted = decide(SALTED, law_rungs, POLICY)
    assert (salted.action, salted.rule, salted.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert salted.facts["gate"]["salted"] and salted.facts["gate"]["refused"]
    assert salted.facts["salted"] == ["no_finite_dimension"] and "salted past the structure gate" in salted.reason
    assert "salt_spent" not in salted.facts
    assert replays(SALTED, law_rungs, salted)
    spent = decide(SALTED, rungs(262144, expander), POLICY)
    assert (spent.action, spent.rule, spent.next_n) == (STOP, "no_finite_dimension", None), "one rung, not every rung"
    assert spent.facts["salt_spent"] == {"gate": "no_finite_dimension", "salted_at": 65536, "held_at": 262144}
    assert spent.facts["gate"]["salt_spent"] and "the salt's one rung is spent" in spent.reason
    assert replays(SALTED, rungs(262144, expander), spent)
    turned = rungs(262144, lambda n: {"gap": 4.0 / n, "diameter": 20.0 if n <= 65536 else 2000.0})
    assert decide(SALTED, turned[:-1], POLICY).facts["gate"]["salted"]
    on = decide(SALTED, turned, POLICY)
    assert (on.action, on.rule, on.next_n) == (RUN_NEXT, "d_s_settled", 1048576)
    assert on.facts["gate"]["result"] == SG.FINITE and "salt_spent" not in on.facts
    assert decide(PLAIN, law_rungs, POLICY).rule == "no_finite_dimension"
    near = rungs(65536, lambda n: {"gap": 2.0 * n ** -0.33, "diameter": n ** 0.5})
    close = decide(PLAIN, near, POLICY)
    assert (close.action, close.rule) == (RUN_NEXT, "gate_audit") and close.facts["gate"]["audit"]["near_threshold"]
    full = decide(PLAIN, near, POLICY, gate={"audit_in_flight": POLICY.gate_audit_in_flight})
    assert (full.action, full.rule) == (STOP, "no_finite_dimension") and full.facts["gate"]["audit"]["full"]


def test_the_audit_buys_only_a_rung_the_gate_s_windows_still_read():
    near = lambda n: {"gap": 2.0 * n ** -0.33, "diameter": n ** 0.5}  # noqa: E731
    first = decide(PLAIN, rungs(65536, near), POLICY)
    assert (first.action, first.rule, first.next_n) == (RUN_NEXT, "gate_audit", 262144)
    assert first.facts["gate"]["audit"]["inside_the_windows"]
    again = decide(PLAIN, rungs(262144, near), POLICY)
    assert (again.action, again.rule, again.next_n) == (STOP, "no_finite_dimension", None)
    audit = again.facts["gate"]["audit"]
    assert audit["near_threshold"] and not audit["inside_the_windows"] and not audit.get("full")
    assert replays(PLAIN, rungs(262144, near), again)


def test_a_refused_law_on_a_long_plateau_is_followed_one_at_a_time():
    policy = Policy(promising_bar=False)
    law_rungs = rungs(65536, expander)
    followed = decide(PLAIN, law_rungs, policy)
    assert (followed.action, followed.rule, followed.next_n) == (RUN_NEXT, "plateau_follow", 262144)
    assert followed.facts["gate"]["follow"] and followed.facts["gate"]["audit"]["plateau_steps"] == 3
    assert replays(PLAIN, law_rungs, followed, policy=policy)
    busy = decide(PLAIN, law_rungs, policy, gate={"plateau_follow_laws": ["another-law"]})
    assert (busy.action, busy.rule) == (STOP, "no_finite_dimension") and busy.facts["gate"]["audit"]["follow_full"]
    itself = decide(PLAIN, rungs(262144, expander), policy, gate={"plateau_follow_laws": [PLAIN]})
    assert (itself.rule, itself.next_n) == ("plateau_follow", 1048576)
    short = rungs(65536, expander)
    short[2] = replace(short[2], probes={"d_s": (2.5, 0.01)})
    assert decide(PLAIN, short, policy).rule == "no_finite_dimension"


def test_the_gate_is_silent_where_it_has_nothing_to_read():
    bare = [Rung(n=r.n, mean_degree=r.mean_degree, connected_fraction=1.0, probes=r.probes, seeds_measured=3)
            for r in rungs(65536, expander)]
    decision = decide(PLAIN, bare, POLICY)
    assert (decision.action, decision.rule) == (RUN_NEXT, "d_s_settled") and "gate" not in decision.facts
    assert "gate" not in decide(PLAIN, rungs(4096, expander), POLICY).facts, "below 16,384 the gate does not read"
    off = decide(PLAIN, rungs(65536, expander), Policy(structure_gate=False, promising_bar=False))
    assert off.rule == "d_s_settled" and "gate" not in off.facts
    no_census = [Rung(n=r.n, mean_degree=r.mean_degree, connected_fraction=1.0, probes=r.probes, seeds_measured=3,
                      structure={"empty": {"seeds": 0}, "given": {"seeds": 0}}) for r in rungs(65536)]
    unread = decide(PLAIN, no_census, POLICY)
    assert unread.rule == "d_s_settled" and unread.facts["gate"]["result"] == "not read"
    assert GATE_RULES == {"no_finite_dimension", "no_giant_component", "gate_audit", "plateau_follow"}


class GatedStore(FakeStore):
    def __init__(self, laws, entries, structure, context):
        super().__init__(laws, entries=entries)
        self.structure, self.context = structure, context

    def law_evidence(self, campaign_id, law):
        return dict(super().law_evidence(campaign_id, law), structure=self.structure.get(law, {}))

    def gate_context(self, campaign_id):
        return dict(self.context)


def test_the_decider_records_where_the_gate_stood_and_counts_its_audits_as_it_buys_them():
    first = G.unsalted_law("law-", POLICY.audit_fraction)
    audited = [first, G.unsalted_law("law-", POLICY.audit_fraction, start=int(first.split("-")[1]) + 1)]
    law_rungs = rungs(65536, lambda n: {"gap": 2.0 * n ** -0.33, "diameter": n ** 0.5})
    entries = {law: {r.n: entry(2.5, d_s=1.5, se=0.01) for r in law_rungs} for law in audited}
    shapes = {law: {r.n: r.structure for r in law_rungs} for law in audited}
    context = {"contract": SG.GATE_CONTRACT, "early_stage_switch": False, "early_agreements": None,
               "audit_in_flight": POLICY.gate_audit_in_flight - 1}
    store = GatedStore(audited, entries, shapes, context)
    decide_pass(store, "1", POLICY)
    by_law = {row["law"]: row for row in store.decisions}
    assert by_law[audited[0]]["rule"] == "gate_audit", "the last audit the limit allows"
    assert by_law[audited[1]]["rule"] == "no_finite_dimension", "the limit reached within the pass"
    assert by_law[audited[1]]["facts"]["gate"]["audit"]["full"]
    for row in store.decisions:
        assert row["inputs"]["gate"]["audit_in_flight"] in (3, 4)
        assert row["inputs"]["rungs"][-1]["structure"]["empty"]["seeds"] == 3
        stored = json.loads(json.dumps(row, default=str))
        verdict = replay_matches(dict(stored, facts_json=json.dumps(row["facts"], default=str)))
        assert verdict["matches"], verdict


def _measurement(n, seed, *, gap, diameter, size, given=None, flag=False, multiplier=1, audit=False):
    census = {"largest_component": {"size": size, "spectral_gap": {"value": gap, "reason": None if gap else "x"},
                                    "diameter": {"lower_bound": diameter}}}
    metrics = {"census": {"empty": census, "given": given if given is not None else census},
               "log_diameter_flag": flag, "log_diameter": {"basis": "certified upper bound"},
               "health": {"equilibration": {"sweeps_multiplier": multiplier},
                          "sampler": {"sampler_audit": audit}}}
    return {"n": n, "seed": seed, "metrics": metrics}


def test_the_store_reads_both_chains_per_rung_as_the_analyzer_summarises_them():
    rows = [_measurement(4096, 0, gap=1e-3, diameter=64, size=4096),
            _measurement(4096, 1, gap=3e-3, diameter=60, size=2048, flag=None),
            _measurement(4096, 1, gap=9.0, diameter=1, size=1, multiplier=4, flag=None),
            _measurement(4096, 2, gap=5.0, diameter=5, size=5, audit=True),
            _measurement(16384, 0, gap=None, diameter=128, size=16384, given={})]
    out = SG.rung_structure(rows)
    assert sorted(out) == [4096, 16384]
    from_empty = out[4096]["empty"]
    assert from_empty["seeds"] == 2 and abs(from_empty["gap"] - (1e-3 + 9.0) / 2) < 1e-12
    assert abs(from_empty["giant"] - (1.0 + 1 / 4096) / 2) < 1e-12
    assert out[4096]["log_diameter"] == {"raised": 0, "false": 1, "unknown": 1, "not_measured": 0}
    assert out[16384]["empty"]["gap"] is None and out[16384]["empty"]["gap_reason"] == "x"
    assert out[16384]["given"]["seeds"] == 0, "a given chain without a census is not a seed of it"
