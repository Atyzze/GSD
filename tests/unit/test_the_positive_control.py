from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import positive_control as PC  # noqa: E402
from benchmark_campaign import DEFAULT_SPEC, control_spec  # noqa: E402


def test_the_campaign_runs_every_law_through_every_rung_with_its_given_chain_at_the_torus():
    criterion = PC.load_criterion()
    spec = control_spec(json.loads(DEFAULT_SPEC.read_text()))
    assert spec["sampling_contract"]["given_start"] == {"family": "periodic_square_lattice"}
    policy = spec["engine"]["policy"]
    assert policy["base_sizes"] == criterion["rungs"] and policy["deep_sizes"] == []
    assert policy["audit_fraction"] == 1.0 and policy["seeds"] == criterion["seeds"]
    assert spec["search_policy"]["kind"] == "hand", "no proposals: the criterion's laws only"


def _chains(**by_label):
    ids = {law["label"]: law["candidate_id"] for law in PC.control_laws(PC.load_criterion())}
    return {ids[label]: dict(zip(("empty", "given", "given_implied_d_s"), value, strict=True))
            for label, value in by_label.items()}


GLASS, TORUS = "no finite dimension", "finite dimension"


def test_the_judge_passes_what_the_criterion_expects_and_nothing_else():
    criterion = PC.load_criterion()
    expected = _chains(P1=(GLASS, TORUS, 2.02), P2=(GLASS, TORUS, 1.98), N1=(GLASS, GLASS, None),
                       N2=(GLASS, "not decidable yet", None))
    assert PC.judge(criterion, expected)["overall"] == "pass"
    melted = dict(expected, **_chains(P1=(GLASS, GLASS, None)))
    assert PC.judge(criterion, melted)["overall"] == "fail", "a positive whose given chain lost the torus fails"
    frozen = dict(expected, **_chains(N1=(GLASS, TORUS, 2.0)))
    result = PC.judge(criterion, frozen)
    assert result["overall"] == "fail", "a negative that keeps a geometry is a false positive"
    assert [r["label"] for r in result["laws"] if r["verdict"] == "fail"] == ["N1"]
    wrong_dimension = dict(expected, **_chains(P2=(GLASS, TORUS, 3.1)))
    assert PC.judge(criterion, wrong_dimension)["overall"] == "fail", "a torus reads two dimensions"
    reached = dict(expected, **_chains(P1=(TORUS, TORUS, 2.0)))
    assert PC.judge(criterion, reached)["overall"] == "fail", \
        "the empty start reaching the torus is news, and not this criterion's pass"
    waiting = {k: v for k, v in expected.items() if k != PC.control_laws(criterion)[3]["candidate_id"]}
    assert PC.judge(criterion, waiting)["overall"] == "incomplete"


def test_the_check_reads_report_28_of_every_part_of_a_bundle(tmp_path):
    rows = [{"candidate_id": cid, **value} for cid, value in
            _chains(P1=(GLASS, TORUS, 2.0), P2=(GLASS, TORUS, 2.0), N1=(GLASS, GLASS, None),
                    N2=(GLASS, GLASS, None)).items()]
    part = tmp_path / "campaign_5_reports_x"
    part.mkdir()
    (part / "28-decision-engine.json").write_text(json.dumps(
        {"body": {"the_record": {"structure_by_the_committed_rule": {"chains_by_law": rows}}}}))
    result = PC.judge(PC.load_criterion(), PC.chains_from_bundle(tmp_path))
    assert result["overall"] == "pass" and "PASS" in PC.render(result)


def _census(n, gap, diameter):
    component = {"size": n, "cycle_rank": n, "spectral_gap": {"value": gap}, "diameter": {"lower_bound": diameter}}
    return {"degree_histogram": {"4": n}, "largest_component": component}


def test_report_28_records_both_chains_of_every_law_and_where_only_the_given_chain_reads_a_geometry():
    import math

    from graph_scale_dynamics.research.record_report import _structure
    rows = []
    for law, given_is_a_torus in (("P", True), ("N", False)):
        for n in (4096, 16384, 65536):
            expander = _census(n, 0.2, int(3 * math.log(n)))
            torus = _census(n, 4.0 / n, int(n ** 0.5))
            rows.append({"candidate_id": law, "n": n, "seed": 0, "metrics": {
                "census": {"empty": expander, "given": torus if given_is_a_torus else expander},
                "d_s": {"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW"}}})
    section = _structure(rows)
    chains = {row["candidate_id"]: row for row in section["chains_by_law"]}
    assert chains["P"]["empty"] == "no finite dimension" and chains["P"]["given"] == "finite dimension"
    assert abs(chains["P"]["given_implied_d_s"] - 2.0) < 0.05
    assert chains["N"]["given"] == "no finite dimension"
    assert [row["candidate_id"] for row in section["given_only_finite"]] == ["P"]
    assert section["chains_agreement"] == {"chains disagree on structure": 1, "neither chain finite": 1}


def test_a_criterion_of_several_campaigns_is_judged_campaign_by_campaign(tmp_path):
    from graph_scale_dynamics.research.control_verdict import load_criterion
    from tests.support import criteria
    criterion = load_criterion(criteria.written(tmp_path))
    parts = PC.parts_of(criterion)
    assert [part["campaign"] for part in parts] == list(criterion["campaigns"])
    assert all(part["laws"] and "campaigns" not in part for part in parts)
    assert PC.parts_of(parts[0]) == [parts[0]]


def test_the_standing_controls_are_found_by_their_contract_s_campaign_in_a_study(tmp_path):
    from graph_scale_dynamics.research.control_verdict import CRITERIA
    criterion = PC.load_criterion(CRITERIA["campaign-standing-controls"])
    assert criterion["campaign"] != "campaign-standing-controls", "its campaign field is a sentence, not the name"
    (tmp_path / "campaign_6_reports_x").mkdir()
    (tmp_path / "study.json").write_text(json.dumps({"campaigns": [
        {"campaign_id": "6", "name": "campaign-standing-controls", "bundle": "campaign_6_reports_x"},
        {"campaign_id": "7", "name": "campaign-cooling-controls", "bundle": "campaign_7_reports_x"}]}))
    assert PC._parts(tmp_path, criterion) == [tmp_path / "campaign_6_reports_x"], "only the standing controls are judged"
