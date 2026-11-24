from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.operations import standing_controls as SC
from graph_scale_dynamics.research import control_verdict as CV
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "controls_criterion_3.json"
LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144]


def test_the_campaign_runs_every_law_to_its_top_rung_each_given_chain_declared():
    criterion = committed.read(CRITERION)
    spec = SC.campaign_spec(criterion)
    assert spec["name"] == "campaign-growth-controls" and spec["search_policy"]["kind"] == "hand"
    assert spec["engine"]["policy"]["base_sizes"] == LADDER and spec["engine"]["policy"]["seeds"] == 3
    starts = spec["sampling_contract"]["given_start_by_law"]
    assert {(v["family"], v["kernel"]) for v in starts.values()} == {
        ("random_geometric_2d_degree_4", "local_walk"), ("random_geometric_3d_degree_6", "local_walk")}


def test_the_judge_passes_a_kept_shape_and_a_melted_one_and_fails_the_reverse():
    criterion = committed.read(CRITERION)
    ids = {law["label"]: law["candidate_id"] for law in CV.control_laws(criterion)}
    glass = "no finite dimension"
    good = {ids["P2"]: {"empty": glass, "given": CV.FINITE, "given_implied_d_s": 2.1, "top_n": 262144},
            ids["P3"]: {"empty": glass, "given": CV.FINITE, "given_implied_d_s": 3.3, "top_n": 262144}}
    good |= {ids[label]: {"empty": glass, "given": glass, "given_implied_d_s": None, "top_n": 262144}
             for label in ("N1", "N2", "N3", "N1z")}
    assert CV.judge(criterion, good)["overall"] == "pass"
    melted = dict(good, **{ids["P3"]: {"empty": glass, "given": glass, "top_n": 262144}})
    assert CV.judge(criterion, melted)["overall"] == "fail"
    kept = dict(good, **{ids["N3"]: {"empty": glass, "given": CV.FINITE, "given_implied_d_s": 3.9,
                                     "top_n": 262144}})
    assert CV.judge(criterion, kept)["overall"] == "fail"
    too_high = dict(good, **{ids["P2"]: {"empty": glass, "given": CV.FINITE, "given_implied_d_s": 2.9,
                                         "top_n": 262144}})
    assert CV.judge(criterion, too_high)["overall"] == "fail", "a finite dimension, but not near 2"
