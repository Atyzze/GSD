from __future__ import annotations

from graph_scale_dynamics.operations import standing_controls as SC
from graph_scale_dynamics.research import control_verdict as CV


LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304]


def test_the_campaign_runs_every_law_through_the_whole_ladder_each_given_chain_at_its_answer():
    criterion = SC.load_criterion()
    spec = SC.campaign_spec(criterion)
    policy = spec["engine"]["policy"]
    assert policy["base_sizes"] == LADDER and policy["deep_sizes"] == [] and policy["seeds"] == 3
    assert policy["audit_fraction"] == 1.0
    assert spec["search_policy"]["kind"] == "hand" and spec["name"] == SC.NAME
    starts = spec["sampling_contract"]["given_start_by_law"]
    assert {v["family"] for v in starts.values()} == {"periodic_square_lattice", "periodic_cubic_quotient"}
    assert "given_start" not in spec["sampling_contract"]
    assert set(spec["operator_whitelist"]) == {t["op"] for law in criterion["laws"] for t in law["spec"]["terms"]}
    from graph_scale_dynamics.scheduling.limits import units_for_seconds
    budgets = dict((int(n), int(units)) for n, units in policy["work_budgets"])
    assert sorted(budgets) == LADDER and min(budgets.values()) >= units_for_seconds(spec, SC.LEAST_BUDGET_SECONDS)
    assert CV.CAMPAIGN_OF[criterion["contract"]] == SC.NAME and CV.CRITERIA[SC.NAME] == SC.CRITERION


def test_the_judge_reads_the_probes_on_the_given_chain_where_the_criterion_asks():
    criterion = SC.load_criterion()
    ids = {law["label"]: law["candidate_id"] for law in SC.laws(criterion)}
    finite, glass = CV.FINITE, "no finite dimension"
    chains = {ids["P1"]: {"empty": glass, "given": finite, "given_implied_d_s": 2.0},
              ids["P2"]: {"empty": glass, "given": finite, "given_implied_d_s": 2.0},
              ids["N1"]: {"empty": glass, "given": glass, "given_implied_d_s": None},
              ids["N2"]: {"empty": glass, "given": glass, "given_implied_d_s": None},
              ids["C1"]: {"empty": glass, "given": finite, "given_implied_d_s": 3.1}}
    square = {str(n): {p: {"mean": 2.0} for p in CV.PROBES} for n in (16384, 65536)}
    cubic = {str(n): {"d_s": {"mean": 3.0}, "d_V": {"mean": 2.9}, "d_B": {"mean": 2.8}, "d_w": {"mean": 2.1}}
             for n in (16384, 65536)}
    probes = {ids["P1"]: square, ids["P2"]: square, ids["C1"]: cubic}
    assert CV.judge(criterion, chains, probes)["overall"] == "pass"
    flat = dict(probes, **{ids["C1"]: square})
    result = CV.judge(criterion, chains, flat)
    assert result["overall"] == "fail", "a cubic chain whose probes read two dimensions is not the answer"
    assert "C1" in [row["label"] for row in result["laws"] if row["verdict"] == "fail"]
    assert CV.judge(criterion, chains, {})["overall"] == "incomplete", "no probe read yet is not a pass"
    waiting = dict(chains, **{ids["C1"]: dict(chains[ids["C1"]], given="not decidable yet", given_implied_d_s=None)})
    result = CV.judge(criterion, waiting, probes)
    assert result["overall"] == "incomplete", "a given chain not decidable yet is read again, not failed"
    assert {row["label"]: row["verdict"] for row in result["laws"]}["C1"] == "not decidable yet"
