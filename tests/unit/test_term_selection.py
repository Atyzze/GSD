from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl.dsl import OPERATORS
from graph_scale_dynamics.scheduling import term_selection
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "campaign_engine_survey.json").read_text(encoding="utf-8"))
GRID = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "discrete_grid.json")
                  .read_text(encoding="utf-8"))
SURVEY["search_policy"]["grid"] = GRID
BUDGET = SURVEY["complexity_budget"]


def test_the_catalogue_covers_every_dsl_term_once():
    catalogue = term_selection.catalogue()
    assert [row["op"] for row in catalogue] == list(OPERATORS), (
        "the page offers a different set of terms, or a different order, from "
        "the one the campaign spec is written in")


def test_the_catalogue_agrees_with_the_drawer_about_which_terms_carry_a_law():
    rng = random.Random(5)
    for row in term_selection.catalogue():
        drew = True
        try:
            blind.blind_law(rng, [row["op"]], GRID, complexity_budget=BUDGET, max_attempts=60)
        except blind.GridError:
            drew = False
        assert drew == row["defines_sparse_phase"], (
            f"the catalogue says {row['op']} "
            f"{'can' if row['defines_sparse_phase'] else 'cannot'} define a sparse phase and "
            f"the drawer disagrees")


def test_a_selection_with_no_sparse_phase_is_refused_with_the_terms_that_would_fix_it():
    verdict = term_selection.preflight(["triangle_count", "square_count"], GRID, BUDGET)
    assert verdict["status"] == "REFUSED"
    assert verdict["problems"], "a refusal with no reason is not a refusal"
    assert "degree_square_sum" in verdict["problems"][0], (
        "the refusal must name a term that would make the selection workable")


def test_a_selection_that_draws_laws_passes_and_says_what_the_search_will_get():
    verdict = term_selection.preflight(["degree_square_sum", "edge_count"], GRID, BUDGET)
    assert verdict["status"] == "PASS"
    assert verdict["sample"]["laws_drawn"] > 0
    assert 0.0 <= verdict["sample"]["yield_fraction"] <= 1.0


def test_the_shipped_campaign_still_passes_admission():
    assert term_selection.selection_problems(SURVEY) == []


@pytest.mark.parametrize("op,reduction", [
    ("degree_anchor", ["degree_square_sum", "edge_count"]),
    ("wedge_count", ["degree_square_sum", "edge_count"]),
    ("degree_square_sum", []),
    ("triangle_count", []),
])
def test_a_term_that_is_exactly_other_terms_says_so(op, reduction):
    row = next(item for item in term_selection.catalogue() if item["op"] == op)
    assert row["reduces_to"] == reduction


def test_entanglement_is_reported_when_both_halves_are_selected():
    verdict = term_selection.preflight(["degree_anchor", "degree_square_sum", "edge_count"],
                                       GRID, BUDGET)
    assert any("not independent terms" in note for note in verdict["notes"])


def test_an_empty_or_unknown_selection_is_refused_rather_than_silently_widened():
    assert term_selection.preflight([], GRID, BUDGET)["status"] == "REFUSED"
    assert term_selection.preflight(["no_such_term"], GRID, BUDGET)["status"] == "REFUSED"
    assert term_selection.preflight(["edge_count", "edge_count"], GRID, BUDGET)["status"] == "REFUSED"


def test_the_diff_against_a_parent_is_what_goes_in_the_change_reason():
    diff = term_selection.selection_diff(["edge_count", "degree_anchor"],
                                         ["edge_count", "degree_anchor", "triangle_count"])
    assert diff["added"] == ["triangle_count"] and diff["removed"] == []
    assert diff["summary"] == "added triangle_count"
    assert term_selection.selection_diff(["a"], ["a"])["summary"] == "same terms as the parent"


def test_a_hand_campaign_is_not_asked_whether_it_can_draw():
    hand = dict(SURVEY, search_policy={"kind": "hand"},
                operator_whitelist=["triangle_count"])
    assert term_selection.selection_problems(hand) == []


def test_a_small_space_is_reported_and_never_refused():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=32)
    assert verdict["status"] == "PASS", verdict
    assert verdict["problems"] == []
    assert verdict["space"]["distinct_physical"] == 23
    assert any("23" in note and "32" in note for note in verdict["notes"]), verdict["notes"]


def test_admission_never_refuses_a_selection_for_the_size_of_its_space():
    spec = dict(SURVEY, operator_whitelist=["degree_square_sum"])
    assert term_selection.selection_problems(spec) == []


def test_the_advice_names_a_change_that_keeps_the_term_set():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=32)
    grid_advice = [row for row in verdict["advice"]
                   if row["change"] == "search_policy.grid.scales"]
    assert grid_advice, verdict["advice"]
    assert grid_advice[0]["keeps_terms"] is True
    assert grid_advice[0]["to"] > grid_advice[0]["from"], (
        "advice to widen the grid has to be measured as widening it")


def test_the_advice_explains_why_one_term_is_narrow():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=32)
    physics = [row for row in verdict["advice"] if row["change"].startswith("none")]
    assert physics, verdict["advice"]
    assert physics[0]["from"] == len(GRID["magnitudes"]) * len(GRID["betas"]) == 60
    assert physics[0]["to"] == 23
    assert "one knob" in physics[0]["detail"]


def test_a_parameterised_term_is_not_narrow_in_the_same_grid():
    flat = term_selection.preflight(["degree_square_sum"], GRID, BUDGET)
    keyed = term_selection.preflight(["degree_anchor"], GRID, BUDGET)
    assert keyed["space"]["distinct_physical"] > 20 * flat["space"]["distinct_physical"]
    assert term_selection._parameterless(["degree_square_sum"]) == ["degree_square_sum"]
    assert term_selection._parameterless(["degree_anchor"]) == []


def test_the_space_is_measured_with_the_key_the_proposer_deduplicates_on():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=32)
    assert verdict["space"]["distinct_physical"] <= verdict["sample"]["distinct_laws"]


def test_coverage_decides_whether_a_space_has_been_seen_whole():
    from graph_scale_dynamics.services.proposer.blind import DEFAULT_GRID
    wide = term_selection._space_estimate(
        ["degree_square_sum"], dict(GRID, scales=DEFAULT_GRID["scales"]), BUDGET,
        draws=term_selection.SPACE_DRAWS, seed=0)
    assert wide["distinct_physical"] / wide["draws"] < 0.5, (
        "this case only means something while the old ratio rule would have "
        "called this space exhaustive")
    assert wide["exhaustive"] is False, wide
    assert wide["seen_once"] > 0

    narrow = term_selection._space_estimate(["degree_square_sum"], GRID, BUDGET,
                                            draws=term_selection.SPACE_DRAWS, seed=0)
    assert narrow["exhaustive"] is True and narrow["coverage"] == 1.0, narrow


def test_a_wide_selection_is_not_reported_as_finished():
    verdict = term_selection.preflight(SURVEY["operator_whitelist"], GRID, BUDGET, pool_min=32)
    assert verdict["status"] == "PASS"
    assert verdict["space"]["exhaustive"] is False
    assert verdict["advice"] == [], "a space nobody has seen the end of needs no advice"


def test_no_pool_declared_means_no_pool_note():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=None)
    assert verdict["status"] == "PASS"
    assert not any("pool" in note for note in verdict["notes"])
    assert not any(row["change"] == "proposer.pool_min" for row in verdict["advice"])
