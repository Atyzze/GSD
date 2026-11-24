from __future__ import annotations

import json

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions.engine import DONE, HOLD, RUN_NEXT, STOP, Policy, Rung, Seed

POLICY = Policy(promising_bar=False)


def decide(law, rungs, policy=POLICY, **context):
    return E.decide(law, rungs, policy, **context)
NOT_AUDITED = G.unsalted_law("law-", POLICY.audit_fraction)
AUDITED = next(f"law-{i}" for i in range(5000) if G.salted(f"law-{i}", "disconnected", POLICY.audit_fraction))


def rung(n, md=2.5, cf=1.0, d_s=None, se=0.05, given=False, seeds=3, others=(), seed_work=()):
    probes = {"d_s": (d_s, se)} if d_s is not None else {}
    probes.update({p: (1.0, 0.1) for p in others})
    budget = POLICY.work_budget(n)
    made = tuple(Seed(termination=w[0], work_units=int(w[1] * budget), work_budget=budget) if isinstance(w, tuple)
                 else Seed(termination="ceiling", work_units=int(w * budget), work_budget=budget) for w in seed_work)
    return Rung(n=n, mean_degree=md, connected_fraction=cf, probes=probes, chains_disagreed=given,
                seeds_measured=seeds, seeds=made)


def test_a_law_with_no_rungs_starts_at_the_first():
    d = decide(NOT_AUDITED, [])
    assert (d.action, d.rule, d.next_n) == (RUN_NEXT, "start", 64)


def test_a_rung_short_of_seeds_is_completed_first():
    d = decide(NOT_AUDITED, [rung(64, seeds=2)])
    assert (d.action, d.rule, d.next_n) == (RUN_NEXT, "complete_rung", 64)


def test_the_g39928_pattern_is_bought_not_rejected():
    rungs = [rung(64, md=1.917, d_s=1.20, se=1.245, given=True), rung(256, md=2.339, d_s=1.41, se=0.33),
             rung(1024, md=2.579, d_s=1.62, se=0.15), rung(4096, md=2.770, d_s=1.78, se=0.078)]
    d = decide(NOT_AUDITED, rungs)
    assert d.action == RUN_NEXT and d.next_n == 16384
    assert d.rule != "unhealthy"


def test_given_chain_disagreement_is_recorded_and_never_stops_a_law():
    rungs = [rung(n, d_s=1.5, given=True) for n in (64, 256, 1024, 4096)]
    d = decide(NOT_AUDITED, rungs)
    assert d.action != STOP
    assert d.facts["chains_disagreed_at"] == [64, 256, 1024, 4096]
    unread = decide(NOT_AUDITED, [rung(n, given=True) for n in (64, 256, 1024, 4096)])
    assert (unread.action, unread.rule) == (STOP, "no_reading") and "given" not in unread.reason


def test_too_dense_and_empty_stop_from_256():
    assert decide(NOT_AUDITED, [rung(64, md=17.0)]).rule == "base_block"
    assert decide(NOT_AUDITED, [rung(64, md=17.0), rung(256, md=17.0)]).rule == "too_dense"
    assert decide(NOT_AUDITED, [rung(64, md=0.0), rung(256, md=0.01)]).rule == "empty"


def test_disconnection_stops_from_1024_and_not_before():
    assert decide(NOT_AUDITED, [rung(64, cf=0.3), rung(256, cf=0.3)]).rule == "base_block"
    d = decide(NOT_AUDITED, [rung(64, cf=0.3), rung(256, cf=0.3), rung(1024, cf=0.3)])
    assert (d.action, d.rule) == (STOP, "disconnected")


def test_each_final_verdict_lets_its_own_tenth_through():
    assert POLICY.audit_fraction == 0.10
    for gate in ("empty", "disconnected", "too_dense"):
        share = sum(G.salted(f"law-{i}", gate, POLICY.audit_fraction) for i in range(20000)) / 20000
        assert 0.09 < share < 0.11, gate
    both = sum(G.salted(f"law-{i}", "empty", 0.1) and G.salted(f"law-{i}", "too_dense", 0.1)
               for i in range(20000)) / 20000
    assert both < 0.02, "drawn apart per gate, not one shared sample"


def test_a_salted_law_goes_past_its_final_verdict_and_says_so():
    rungs = [rung(64, cf=0.3), rung(256, cf=0.3), rung(1024, cf=0.3)]
    d = decide(AUDITED, rungs)
    assert d.rule == "base_block" and d.facts["salted"] == ["disconnected"]
    assert decide(NOT_AUDITED, rungs).rule == "disconnected"


def test_beyond_the_base_block_one_priority_buys_a_settled_d_s():
    base = [rung(64), rung(256), rung(1024, md=2.50, d_s=1.50), rung(4096, md=2.52, d_s=1.53)]
    d = decide(NOT_AUDITED, base)
    assert (d.action, d.rule, d.priority, d.next_n) == (RUN_NEXT, "d_s_settled", 1, 16384)
    assert "mean degree settled" in d.reason and d.facts["mean_degree_settled"] is True
    moving = base[:3] + [rung(4096, md=2.80, d_s=1.53)]
    d = decide(NOT_AUDITED, moving)
    assert (d.action, d.rule, d.priority) == (RUN_NEXT, "d_s_settled", 1), "whatever the mean degree does"
    assert "mean degree moved more than 3%" in d.reason, d.reason


def test_a_law_other_probes_read_is_held_and_the_reason_says_what_read():
    base = [rung(64), rung(256), rung(1024, md=2.5, d_s=1.0), rung(4096, md=3.0, d_s=2.0)]
    assert decide(NOT_AUDITED, base).rule == "second_rung"
    assert decide(NOT_AUDITED, base, Policy(second_rung=False)).action == HOLD
    reading = base[:3] + [rung(4096, md=3.0, d_s=2.0, others=("d_V", "d_w"))]
    d = decide(NOT_AUDITED, reading)
    assert (d.action, d.rule, d.priority, d.next_n) == (RUN_NEXT, "second_rung", 2, 16384)
    assert "d_V, d_w read at the top rung" in d.reason, d.reason
    assert d.facts["other_probes"] == ["d_V", "d_w"]
    off_line = base[:3] + [rung(4096, md=3.0, d_s=1.5)]
    d = decide(NOT_AUDITED, off_line)
    assert (d.action, d.rule) == (RUN_NEXT, "second_rung")
    assert "branching line" not in d.reason, "no reason reads d_s against the mean degree since 790"
    held = decide(NOT_AUDITED, off_line, Policy(second_rung=False))
    assert (held.action, held.rule, held.priority) == (HOLD, "unsettled", None)


def test_the_engine_has_one_contract_and_records_it():
    import json
    from pathlib import Path
    from graph_scale_dynamics.decisions import engine as E
    assert E.ENGINE_VERSION == "decision-engine-2" and not hasattr(E, "ENGINE_CONTRACT")
    assert decide(NOT_AUDITED, []).engine == E.ENGINE_VERSION
    assert E.SETTLING_RULES == {"d_s_settled"}
    shipped = json.loads((Path(__file__).resolve().parents[2]
                          / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    assert E.is_engine_campaign(shipped)
    assert not E.is_engine_campaign(dict(shipped, engine=dict(shipped["engine"], contract="decision-engine-1")))


def test_a_hold_states_what_was_computed():
    expander = [rung(64, md=4.0, d_s=None), rung(256, md=4.0, d_s=None), rung(1024, md=4.0, d_s=None),
                rung(4096, md=4.0, d_s=None)]
    parked = decide(NOT_AUDITED, expander)
    assert (parked.action, parked.rule) == (STOP, "no_reading")
    assert "d_s has no reading" in parked.reason and "mean degree settled" in parked.reason, parked.reason
    assert "no other probe reads" in parked.reason, parked.reason
    moving = [rung(64), rung(256), rung(1024, md=2.5, d_s=1.0), rung(4096, md=3.0, d_s=2.0)]
    looked = decide(NOT_AUDITED, moving)
    assert "outside 2 standard errors" in looked.reason and "mean degree moved more than 3%" in looked.reason, looked.reason


def test_the_last_declared_rung_is_done():
    rungs = [rung(n, md=2.5, d_s=1.5) for n in POLICY.ladder()]
    assert decide(NOT_AUDITED, rungs).action == DONE


def test_a_seed_that_ends_at_its_budget_is_marked_and_the_law_is_decided_as_any_other():
    rungs = [rung(64), rung(256, seed_work=(0.5, ("budget", 1.0), 0.6))]
    d = decide(NOT_AUDITED, rungs)
    assert (d.action, d.rule) == (RUN_NEXT, "base_block") and d.facts["budget_ended"] == {"seeds": [1], "of": 3,
                                                                                          "at_n": 256}
    use = d.facts["budget_use"]
    assert [u["reached"] for u in use] == [False, True, False]
    assert use[1]["work_budget"] == POLICY.work_budget(256) and use[1]["budget_fraction"] == 1.0


def test_the_budget_s_end_is_a_mark_for_the_audit_sample_too():
    rungs = [rung(64), rung(256, seed_work=(0.5, ("budget", 0.97), 0.6))]
    assert decide(AUDITED, rungs).facts["budget_ended"]["seeds"] == [1]
    ended = [rung(64), rung(256, seed_work=(0.5, 1.2, 0.6))]
    assert "budget_ended" not in decide(AUDITED, ended).facts, "a seed that ended otherwise did not reach it, however much it spent"


def test_budgets_are_the_declared_table_in_units_of_work():
    budgets = [POLICY.work_budget(n) for n in POLICY.ladder()]
    assert all(isinstance(units, int) and units > 0 for units in budgets)
    assert len(set(budgets[:4])) == 1, 'the base block is one number'
    assert all(b > a for a, b in zip(budgets[3:], budgets[4:], strict=False)), 'every deep rung is wider'
    top, units = max(POLICY.work_budgets)
    assert POLICY.work_budget(4 * top) == 4 * units, "a size past the table takes four times the top's budget a step"
    assert set(POLICY.work_weights()) == {"moves", "evaluations", "changes", "lists", "entries", "tests"}


def test_a_law_well_inside_its_budgets_records_how_little_it_used():
    d = decide(NOT_AUDITED, [rung(64, seed_work=(0.1, 0.05, 0.02))])
    assert [u["budget_fraction"] for u in d.facts["budget_use"]] == [0.1, 0.05, 0.02]


def test_a_decision_is_plain_data_and_reproducible():
    rungs = [rung(64), rung(256), rung(1024, md=2.5, d_s=1.5), rung(4096, md=2.51, d_s=1.52)]
    first, second = decide(NOT_AUDITED, rungs), decide(NOT_AUDITED, rungs)
    assert first == second
    assert json.loads(json.dumps(first.as_dict()))["rule"] == "d_s_settled"


def test_a_campaign_declares_the_engine_and_its_policy():
    import json
    from pathlib import Path
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    from graph_scale_dynamics.decisions.engine import first_multipliers_of
    from graph_scale_dynamics.scheduling.limits import work_budget
    root = Path(__file__).resolve().parents[2]
    spec = json.loads((root / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    assert is_engine_campaign(spec)
    policy = Policy.from_spec(spec)
    from dataclasses import replace
    from graph_scale_dynamics.calibration import finite_size
    fits = finite_size.committed()
    assert policy == replace(Policy(), deep_sizes=(16384, 65536, 262144, 1048576),
                             first_multipliers=first_multipliers_of(spec),
                             deep_lane_widths=((1048576, 4),), depth_rules=631, gap_exponent_at_most=-0.309,
                             finite_size_fits=tuple((name, f["d_inf"], f["a"], f["omega"], f["scatter"], f["n_min"])
                                                    for name, f in sorted(fits["families"].items())),
                             finite_size_scatter_sigmas=fits["scatter_sigmas"])
    assert spec["ladder"][-1] == spec["extension_ladder"][-1] == spec["budgets"]["max_n"] == 1048576
    assert [work_budget(spec, n) for n in policy.ladder()] == [Policy().work_budget(n) for n in policy.ladder()]
    for mechanism in ("auto_continuation", "filters", "prescreen", "runtime_budget"):
        assert mechanism not in spec
    assert "stage_gate" not in spec["base_block"]


def test_a_seed_that_failed_for_good_stops_the_law_with_its_rung_and_count():
    d = decide(NOT_AUDITED, [rung(64), rung(256, seeds=2)], failed_seeds={256: 1})
    assert (d.action, d.rule, d.at_n) == (STOP, "failed", 256)
    assert d.facts["failed_seeds"] == {256: 1}
    assert decide(NOT_AUDITED, [rung(64)], failed_seeds={}).rule == "base_block"


def test_a_component_under_the_floor_stops_only_when_it_is_not_growing():
    dust = decide(NOT_AUDITED, [rung(64, cf=0.01), rung(256, cf=0.01), rung(1024, cf=0.003)])
    assert (dust.action, dust.rule) == (STOP, "disconnected")
    assert "not growing" in dust.reason and "-0.007" in dust.reason, dust.reason
    forming = decide(NOT_AUDITED, [rung(64, cf=0.05), rung(256, cf=0.20), rung(1024, cf=0.45, d_s=1.5)])
    assert forming.action == RUN_NEXT, "0.20 to 0.45 is a giant component forming, not dust"
    stalled = decide(NOT_AUDITED, [rung(256, cf=0.45), rung(1024, cf=0.45), rung(4096, cf=0.44)])
    assert (stalled.action, stalled.rule) == (STOP, "disconnected")
    assert Policy().connectivity_floor == 0.5
    assert decide(NOT_AUDITED, [rung(256, cf=0.9), rung(1024, cf=0.6, d_s=1.5)]).action == RUN_NEXT


def _ladder_to(top, d_s=(1.50, 1.52, 1.53, 1.54, 1.54), md=(2.50, 2.51, 2.52, 2.52, 2.52)):
    sizes = [n for n in (4096, 16384, 65536, 262144, 1048576, 4194304) if n <= top]
    base = [rung(64), rung(256), rung(1024, md=2.5, d_s=1.5)]
    values = list(d_s)[-len(sizes):]
    degrees = list(md)[-len(sizes):]
    return base + [rung(n, md=degrees[i], d_s=values[i]) for i, n in enumerate(sizes)]


STANDING = {"control_family": None, "law_score": 42.0}


def test_below_the_plateau_rung_one_settled_step_still_buys():
    d = decide(NOT_AUDITED, _ladder_to(16384, d_s=(1.50, 1.52)), standing={"law_score": 0.0})
    assert (d.action, d.rule, d.next_n) == (RUN_NEXT, "d_s_settled", 65536)


def test_a_deep_rung_takes_a_plateau_across_three_rungs():
    d = decide(NOT_AUDITED, _ladder_to(65536, d_s=(1.0, 1.52, 1.53)), standing=STANDING)
    assert (d.action, d.rule, d.next_n) == (HOLD, "no_plateau", 262144)
    assert "d_s did not settle at the step before" in d.reason, d.reason
    d = decide(NOT_AUDITED, _ladder_to(65536), standing=STANDING)
    assert (d.action, d.rule, d.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert d.facts["plateau"] == {"d_s_settled_before": True}, "score 10 and the class are retired (646)"


def test_only_d_s_decides_whether_a_deep_rung_is_earned():
    moving = decide(NOT_AUDITED, _ladder_to(65536, md=(2.5, 2.51, 2.9)), standing=STANDING)
    assert (moving.action, moving.rule, moving.next_n) == (RUN_NEXT, "d_s_settled", 262144)
    assert moving.facts["mean_degree_settled"] is False, "still measured, no longer a gate"
    for score in (0.0, 100.0):
        d = decide(NOT_AUDITED, _ladder_to(65536), standing={"law_score": score})
        assert (d.action, d.rule) == (RUN_NEXT, "d_s_settled"), "the law score orders a lane and decides nothing"
    unknown = decide(NOT_AUDITED, _ladder_to(65536), standing=None)
    assert unknown.action == RUN_NEXT


def test_a_deep_lane_is_as_wide_as_its_rung_declares():
    law = _ladder_to(262144)
    full = decide(NOT_AUDITED, law, standing=STANDING, deep_lane_in_flight=4)
    assert (full.action, full.rule, full.next_n) == (HOLD, "deep_lane_full", 1048576)
    room = decide(NOT_AUDITED, law, standing=STANDING, deep_lane_in_flight=3)
    assert (room.action, room.next_n) == (RUN_NEXT, 1048576)
    assert decide(NOT_AUDITED, _ladder_to(65536), standing=STANDING, deep_lane_in_flight=99).action == RUN_NEXT, \
        "a lane is a rung that declares a width, and 262144 does not"
