from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.operations.campaign_control import grid_diff
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "campaign_engine_survey.json").read_text(encoding="utf-8"))
GRID = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "discrete_grid.json")
                  .read_text(encoding="utf-8"))
SURVEY["search_policy"]["grid"] = GRID
BUDGET = SURVEY["complexity_budget"]

HIS = dict(GRID, scales=["one", "log_N"], per_term={
    "edge_count": {"magnitudes": [1.0], "signs": [1], "scales": ["log_N"]},
    "degree_square_sum": {"magnitudes": {"min": 0.001, "max": 1.0}, "signs": [1]},
})


def test_a_term_without_an_override_draws_from_the_campaigns_grid():
    grid = dict(blind.DEFAULT_GRID, per_term={"edge_count": {"signs": [1]}})
    assert blind.term_grid(grid, "degree_square_sum")["signs"] == grid["signs"]
    assert blind.term_grid(grid, "edge_count")["signs"] == [1]


def test_an_override_replaces_a_key_and_leaves_the_rest_alone():
    grid = dict(blind.DEFAULT_GRID, per_term={"edge_count": {"scales": ["log_N"]}})
    own = blind.term_grid(grid, "edge_count")
    assert own["scales"] == ["log_N"]
    assert own["magnitudes"] == blind.DEFAULT_GRID["magnitudes"]


def test_the_edge_term_is_pinned_while_the_penalty_roams():
    rng = random.Random(0)
    edges, quadratics = set(), set()
    for _ in range(150):
        law = dsl.normalize(blind.blind_law(rng, ["edge_count", "degree_square_sum"], HIS,
                                            complexity_budget=BUDGET))
        for term in law["terms"]:
            if term["op"] == "edge_count":
                edges.add((term["coeff"]["c0"], term["coeff"]["scale"]))
            else:
                quadratics.add(term["coeff"]["c0"])
    assert edges == {(1.0, "log_N")}, edges
    assert len(quadratics) > 50, "the penalty is meant to be free"
    assert all(value > 0 for value in quadratics), "its sign was pinned positive"


def test_the_unbounded_combination_is_closed_with_or_without_a_pinned_sign():
    loose = dict(GRID, scales=["one", "log_N"])
    pinned = dict(loose, per_term={"degree_square_sum": {"signs": [1]}})
    for grid in (loose, pinned):
        rng = random.Random(3)
        drawn = 0
        for _ in range(1200):
            try:
                law = blind.blind_law(rng, ["degree_square_sum", "edge_count"], grid,
                                      complexity_budget=BUDGET)
            except blind.GridError:
                continue
            drawn += 1
            assert not any(t["op"] == "degree_square_sum" and t["coeff"]["c0"] < 0
                           for t in law["terms"]), law
        assert drawn > 1000


def test_the_predicate_reads_the_reduced_form():
    anchor = [{"op": "degree_anchor", "params": {"k": 4},
               "coeff": {"c0": -0.5, "scale": "one"}}]
    written = [{"op": "degree_square_sum", "params": {}, "coeff": {"c0": -0.5, "scale": "one"}},
               {"op": "edge_count", "params": {}, "coeff": {"c0": 8.0, "scale": "one"}}]
    assert blind._bounded_below(anchor) is False
    assert blind._bounded_below(written) is False, "the same law as the anchor, and unbounded below"
    quartic = {"op": "degree_fourth_sum", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}
    assert blind._bounded_below(written + [quartic]) is True
    assert blind._bounded_below(written + [dict(quartic, coeff={"c0": 0.1, "scale": "log_N"})]) is False, \
        "a quartic on another scale does not bound it at every N"
    cancelled = anchor + [{"op": "degree_square_sum", "params": {}, "coeff": {"c0": 0.75, "scale": "one"}}]
    assert blind._bounded_below(cancelled) is True, "a positive square that outweighs the anchor's"
    wedge = [{"op": "wedge_count", "params": {}, "coeff": {"c0": -0.2, "scale": "one"}}]
    assert blind._bounded_below(wedge) is False, "a negative wedge count is a negative square"


def test_a_per_term_interval_makes_the_whole_campaign_continuous():
    assert blind.is_continuous(GRID) is False
    assert blind.is_continuous(
        dict(GRID, per_term={"degree_square_sum": {"magnitudes": {"min": 0.01, "max": 1.0}}})
    ) is True


def test_the_change_reason_names_the_pinned_terms_not_their_values():
    diff = grid_diff({}, {"per_term": {"edge_count": {"scales": ["log_N"]},
                                       "degree_square_sum": {"signs": [1]}}})
    assert "degree_square_sum, edge_count" in diff["summary"]


@pytest.mark.parametrize("override,because", [
    ({"betas": [1.0]}, "may only override"),
    ({"term_counts": [1]}, "may only override"),
    ({}, "non-empty grid"),
    ({"magnitudes": []}, "non-empty list"),
    ({"magnitudes": {"min": 0.0, "max": 1.0}}, "above zero"),
])
def test_an_unusable_override_is_refused_with_its_reason(override, because):
    problems = blind.validate_grid(
        dict(blind.DEFAULT_GRID, per_term={"edge_count": override}))
    assert problems and any(because in problem for problem in problems), problems
    assert all("per_term.edge_count" in problem for problem in problems), (
        "the refusal must say which term it is about")


def test_an_override_for_an_operator_that_does_not_exist_is_refused():
    problems = blind.validate_grid(
        dict(blind.DEFAULT_GRID, per_term={"degree_ninth_sum": {"signs": [1]}}))
    assert problems and "not a known operator" in problems[0]


def test_per_term_itself_must_be_an_object():
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, per_term=["edge_count"]))


def test_a_grid_with_no_overrides_is_unchanged():
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, **GRID)) == []
    assert blind.term_grid(dict(blind.DEFAULT_GRID, **GRID), "edge_count") \
        == dict(blind.DEFAULT_GRID, **GRID)
