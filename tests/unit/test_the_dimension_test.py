from __future__ import annotations

import json
import math

from graph_scale_dynamics.research import dimension_test as T
from graph_scale_dynamics.resources import committed

SIZES = (1024, 4096, 16384)
R = T.Rule(reach_exponent_at_least=0.125, growth_agrees_within=0.4, d_step_within=0.75)


def _chain(d, reach=lambda n, d: n ** (1 / d), d_s=None, d_w=2.0, degree=6.0, piece=1.0):
    return [{"n": n, "d_V": d, "d_B": d, "d_s": d if d_s is None else d_s, "d_w": d_w, "reach": reach(n, d),
             "mean_degree": degree, "giant_fraction": piece} for n in SIZES]


def test_a_graph_whose_reach_and_balls_agree_reads_dimensional_with_its_d():
    judged = T.judge_chain(_chain(2.6, d_w=2.0), R)
    assert judged["verdict"] == "dimensional" and abs(judged["d"] - 2.6) < 1e-9, judged["why"]


def test_a_fractional_d_is_read_as_it_is():
    judged = T.judge_chain(_chain(1.585, d_s=1.365, d_w=2.32), R)
    assert judged["verdict"] == "dimensional" and abs(judged["d"] - 1.585) < 1e-9, judged["why"]


def test_a_graph_whose_reach_grows_as_a_logarithm_is_a_small_world():
    judged = T.judge_chain(_chain(4.0, reach=lambda n, d: 1.5 * math.log(n)), R)
    assert judged["verdict"] == "not_dimensional"
    assert any("small world" in why for why in judged["why"])


def test_balls_that_claim_more_than_the_reach_allows_are_refused():
    judged = T.judge_chain(_chain(4.0, reach=lambda n, d: n ** 0.5), R)
    assert judged["verdict"] == "not_dimensional"
    assert "its reach and its balls disagree on the dimension" in judged["why"]


def test_a_chain_whose_balls_read_nothing_is_not_told_they_disagree():
    rows = [dict(row, d_V=None, d_B=None) for row in _chain(2.0)]
    assert T.judge_chain(rows, R)["why"] == ["no mass dimension read at the top size"]


def test_the_einstein_relation_is_reported_and_not_judged():
    judged = T.judge_chain(_chain(2.0, d_s=3.5, d_w=2.0), R)
    assert judged["verdict"] == "dimensional" and abs(judged["signals"]["einstein_gap"] - 1.5) < 1e-9


def test_a_graph_in_pieces_or_too_few_sizes_reads_nothing():
    assert T.judge_chain(_chain(2.0, piece=0.5), R)["verdict"] == "not_dimensional"
    assert T.judge_chain(_chain(2.0)[-1:], R)["why"] == ["fewer usable sizes than the rule needs"]


def test_a_look_alike_that_reads_dimensional_at_a_middle_size_fails_its_case():
    criterion = {"training": {"seeds": [1], "cases": [{"family": "fake", "verdict": "not_dimensional"}]}}
    rows = [dict(row, family="fake", seed=1, built=True) for row in _chain(2.0)]
    rows[-1]["reach"] = 1.5 * 9.7
    judged = T.judge_against(criterion, [{"part": "training", "rows": rows}], R)
    seed = judged["cases"][0]["seeds"][0]
    assert seed["verdict"] == "not_dimensional" and seed["dimensional_early_at"] == [4096]
    assert not judged["passes"]


def test_the_final_probes_read_the_known_answers_as_committed_and_the_rule_is_calibrated_on_them():
    from graph_scale_dynamics.research import dimension_rule

    def load(name):
        return json.loads(committed.path(name).read_text(encoding="utf-8"))

    criterion = load("dimension_test_criterion_4.json")
    readings = [load("dimension_test_4_training.json"), load("dimension_test_4_held_out.json")]
    for measured in readings:
        assert measured["measured_utc"] > criterion["committed_utc"], f"{measured['part']} predates its criterion"
        assert measured["analysis_version"] == "analysis-5.3.0"
    judged = T.judge_against(criterion, readings)
    assert json.loads(json.dumps(judged)) == load("dimension_test_4_judged.json")
    assert judged["passes"]
    assert dimension_rule.CALIBRATED_ON == {"criterion": "dimension_test_criterion_4.json",
                                            "training": "dimension_test_4_training.json",
                                            "judged": "dimension_test_4_judged.json"}
