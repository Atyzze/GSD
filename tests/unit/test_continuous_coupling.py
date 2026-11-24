from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.scheduling import term_selection
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "campaign_engine_survey.json").read_text(encoding="utf-8"))
GRID = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "discrete_grid.json")
                  .read_text(encoding="utf-8"))
SURVEY["search_policy"]["grid"] = GRID
BUDGET = SURVEY["complexity_budget"]
CONTINUOUS = dict(GRID, magnitudes={"min": 0.01, "max": 2.0},
                  betas={"min": 0.1, "max": 100.0})


def test_a_list_still_draws_from_the_list():
    rng = random.Random(0)
    for _ in range(50):
        value = blind.draw_value(rng, GRID["magnitudes"])
        assert value in GRID["magnitudes"]


def test_an_interval_draws_inside_itself_and_never_repeats():
    rng = random.Random(0)
    drawn = [blind.draw_value(rng, {"min": 0.01, "max": 2.0}) for _ in range(300)]
    assert all(0.01 <= value <= 2.0 for value in drawn)
    assert len(set(drawn)) == 300, "a continuous draw that repeats is not continuous"


def test_a_log_interval_spends_its_draws_evenly_across_decades():
    rng = random.Random(1)
    drawn = [blind.draw_value(rng, {"min": 0.01, "max": 100.0}) for _ in range(2000)]
    below_one = sum(1 for value in drawn if value < 1.0)
    assert 0.4 < below_one / len(drawn) < 0.6, (
        "log spacing must split a symmetric range about its geometric middle")


def test_linear_spacing_is_available_when_it_is_asked_for():
    rng = random.Random(1)
    drawn = [blind.draw_value(rng, {"min": -2.0, "max": 2.0, "spacing": "linear"})
             for _ in range(500)]
    assert all(-2.0 <= value <= 2.0 for value in drawn)
    assert min(drawn) < -1.0 and max(drawn) > 1.0


def test_an_interval_that_crosses_zero_is_linear_by_default():
    rng = random.Random(2)
    drawn = [blind.draw_value(rng, {"min": -1.0, "max": 1.0}) for _ in range(200)]
    assert any(value < 0 for value in drawn) and any(value > 0 for value in drawn)


def test_an_integer_interval_draws_whole_numbers_inside_it():
    rng = random.Random(3)
    drawn = [blind.draw_value(rng, {"min": 2, "max": 32}, integer=True) for _ in range(200)]
    assert all(isinstance(value, int) and 2 <= value <= 32 for value in drawn)
    assert len(set(drawn)) > 10


def test_a_draw_keeps_six_significant_figures_at_every_magnitude():
    rng = random.Random(4)
    for _ in range(200):
        value = blind.draw_value(rng, {"min": 1e-3, "max": 1e2})
        assert value == float(f"{value:.6g}")


def test_one_term_stops_having_twenty_three_laws():
    rng = random.Random(5)
    couplings = set()
    for _ in range(300):
        law = dsl.normalize(blind.blind_law(rng, ["degree_square_sum"], CONTINUOUS,
                                            complexity_budget=BUDGET))
        couplings.add(law["terms"][0]["coeff"]["c0"] * law["dynamics"]["beta"])
    assert len(couplings) == 300, (
        "the same selection that had 23 distinct couplings must now have one "
        "per draw: the coupling is drawn from a continuum")


def test_the_estimator_refuses_to_put_a_number_on_a_continuum():
    space = term_selection._space_estimate(["degree_square_sum"], CONTINUOUS, BUDGET,
                                           draws=300, seed=0)
    assert space["continuous"] is True
    assert space["exhaustive"] is False, (
        "a campaign whose coupling is continuous has no last law, and nothing "
        "downstream may mark it surveyed")


def test_the_discrete_grid_is_still_reported_as_finite():
    space = term_selection._space_estimate(["degree_square_sum"], GRID, BUDGET,
                                           draws=300, seed=0)
    assert space["continuous"] is False and space["exhaustive"] is True
    assert space["distinct_physical"] == 23


def test_the_preflight_says_the_campaign_runs_until_it_is_paused():
    verdict = term_selection.preflight(["degree_square_sum"], CONTINUOUS, BUDGET, pool_min=32)
    assert verdict["status"] == "PASS"
    assert any("no last law" in note for note in verdict["notes"]), verdict["notes"]
    assert not any("pool" in note and "never fills" in note for note in verdict["notes"])


def test_the_advice_leads_with_the_change_that_removes_the_ceiling():
    verdict = term_selection.preflight(["degree_square_sum"], GRID, BUDGET, pool_min=32)
    first = verdict["advice"][0]
    assert first["continuous"] is True
    assert "interval" in first["detail"]
    assert first["sampled"] > 500, "the advice quotes a measured draw, not a promise"


@pytest.mark.parametrize("entry,because", [
    ({"min": 2.0, "max": 1.0}, "above min"),
    ({"min": 0.0, "max": 2.0}, "above zero"),
    ({"min": -1.0, "max": 2.0}, "above zero"),
    ({"min": 0.01, "max": 1e6}, "coefficient bound"),
    ({"min": 0.01, "max": 2.0, "spacing": "quadratic"}, "log or linear"),
    ({"min": "a", "max": 2.0}, "finite numeric"),
])
def test_an_unusable_magnitude_interval_is_refused_with_its_reason(entry, because):
    problems = blind.validate_grid(dict(blind.DEFAULT_GRID, magnitudes=entry))
    assert problems and any(because in problem for problem in problems), problems


def test_a_power_exponent_interval_must_lie_inside_the_dsl_bounds():
    assert blind.validate_grid(dict(blind.DEFAULT_GRID,
                                    power_exponents={"min": -3.0, "max": 2.0}))
    assert blind.validate_grid(dict(blind.DEFAULT_GRID,
                                    power_exponents={"min": -2.0, "max": 2.0})) == []


def test_a_categorical_entry_cannot_be_an_interval():
    assert "scales" not in blind.GRID_INTERVAL_KEYS
    assert "term_counts" not in blind.GRID_INTERVAL_KEYS
    assert "signs" not in blind.GRID_INTERVAL_KEYS
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, scales={"min": 1, "max": 2}))


def test_the_continuous_grid_the_operator_would_write_is_accepted():
    assert blind.validate_grid(dict(blind.DEFAULT_GRID, **CONTINUOUS)) == []
    assert blind.is_continuous(CONTINUOUS) is True
    assert blind.is_continuous(GRID) is False


def test_an_interval_keeps_the_spacing_it_was_given():
    rng = random.Random(7)
    linear = [blind.draw_value(rng, {"min": 0.01, "max": 100.0, "spacing": "linear"})
              for _ in range(2000)]
    rng = random.Random(7)
    logged = [blind.draw_value(rng, {"min": 0.01, "max": 100.0, "spacing": "log"})
              for _ in range(2000)]
    below_one_linear = sum(1 for v in linear if v < 1.0) / len(linear)
    below_one_log = sum(1 for v in logged if v < 1.0) / len(logged)
    assert below_one_linear < 0.05, "a linear draw barely visits the bottom decade"
    assert 0.4 < below_one_log < 0.6, "a log draw splits the range at its geometric middle"


def test_both_spacings_pass_the_grid_validator():
    for spacing in ("log", "linear"):
        assert blind.validate_grid(
            dict(blind.DEFAULT_GRID,
                 magnitudes={"min": 0.01, "max": 2.0, "spacing": spacing})) == []


def test_a_spacing_the_drawer_does_not_know_is_refused():
    problems = blind.validate_grid(
        dict(blind.DEFAULT_GRID, magnitudes={"min": 0.01, "max": 2.0, "spacing": "geometric"}))
    assert problems and "log or linear" in problems[0]
