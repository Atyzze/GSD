from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.operations.campaign_control import grid_diff
from graph_scale_dynamics.services.proposer.blind import DEFAULT_GRID, validate_grid
from graph_scale_dynamics.scheduling import term_selection

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "campaign_engine_survey.json").read_text(encoding="utf-8"))
GRID = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "discrete_grid.json")
                  .read_text(encoding="utf-8"))
SURVEY["search_policy"]["grid"] = GRID
BUDGET = SURVEY["complexity_budget"]


def test_the_diff_reports_a_list_by_its_length_not_its_contents():
    diff = grid_diff(GRID, dict(GRID, magnitudes=[0.1, 0.2, 0.3, 0.4]))
    assert diff["changed"]["magnitudes"] == {"from": 6, "to": 4}
    assert diff["summary"] == "magnitudes 6 to 4"


def test_an_unchanged_grid_says_so_rather_than_inventing_a_change():
    assert grid_diff(GRID, dict(GRID))["summary"] == "same grid as the parent"
    assert grid_diff(None, None)["summary"] == "same grid as the parent"


def test_a_scale_change_is_reported_as_a_count_too():
    diff = grid_diff(GRID, dict(GRID, scales=DEFAULT_GRID["scales"]))
    assert diff["changed"]["scales"] == {"from": 1, "to": 6}


def test_the_grid_is_validated_by_the_drawer_and_not_by_a_second_copy():
    assert validate_grid(GRID) == []
    assert validate_grid(dict(GRID, betas=[0.0])), "a zero beta must be refused"
    assert validate_grid(dict(GRID, magnitudes=[-1.0])), "a negative magnitude must be refused"
    assert validate_grid(dict(GRID, scales=["quadratic"])), "an unknown scale must be refused"
    assert validate_grid(dict(GRID, magnitudes=[])), "an empty list must be refused"


def test_widening_the_grid_widens_a_one_term_campaign_more_than_a_term_does():
    narrow = term_selection.preflight(["degree_square_sum"], GRID, BUDGET)
    wider_grid = term_selection.preflight(
        ["degree_square_sum"], dict(GRID, scales=DEFAULT_GRID["scales"]), BUDGET)
    assert wider_grid["space"]["distinct_physical"] > \
        5 * narrow["space"]["distinct_physical"]


def test_more_magnitudes_alone_widen_the_space():
    fine = [round(0.05 * step, 3) for step in range(1, 25)]
    narrow = term_selection.preflight(["degree_square_sum"], GRID, BUDGET)
    dense = term_selection.preflight(["degree_square_sum"], dict(GRID, magnitudes=fine), BUDGET)
    assert dense["space"]["distinct_physical"] > narrow["space"]["distinct_physical"]
    assert validate_grid(dict(GRID, magnitudes=fine)) == []


@pytest.mark.parametrize("grid,expected_terms", [
    (dict(GRID, betas=[1.0]), True),
    (dict(GRID, magnitudes=[1.0]), True),
])
def test_a_one_value_list_is_legal_and_narrows_the_space(grid, expected_terms):
    assert validate_grid(grid) == []
    verdict = term_selection.preflight(["degree_square_sum"], grid, BUDGET)
    assert verdict["status"] == "PASS"
    assert verdict["space"]["distinct_physical"] >= 1


def test_a_partial_grid_is_legal_because_the_drawer_fills_the_rest():
    fragment = {"magnitudes": [1.0], "betas": [1.0, 2.0]}
    assert validate_grid(fragment), "a fragment is not a complete grid on its own"
    assert validate_grid(dict(DEFAULT_GRID, **fragment)) == [], (
        "and it is valid as the drawer will see it, which is what decides")
