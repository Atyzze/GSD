from __future__ import annotations

from pathlib import Path

import pytest

from graph_scale_dynamics.research.stability_score import (
    DENSITY_FLOWING_BUCKET, MEAN_DEGREE_DRIFT_TOLERANCE, density_diagnostic,
    gate_bucket_names)

ROOT = Path(__file__).resolve().parents[2]
SIZES = [64, 256, 1024, 4096, 16384]


def test_g228088s_mean_degree_is_converging_not_flowing():
    result = density_diagnostic([2.146, 2.536, 2.962, 3.327, 3.636], SIZES)
    assert result["flowing"] is False
    assert result["decelerating"] is True
    assert result["converged_at_this_rung"] is False
    assert result["extrapolated_limit"] == pytest.approx(5.34, abs=0.05)
    assert result["remaining_relative"] > 0.4
    assert "converging" in result["reading"]


def test_a_mean_degree_whose_rise_is_not_slowing_is_flowing():
    result = density_diagnostic([2.0, 2.3, 2.9, 4.1, 6.5], SIZES)
    assert result["flowing"] is True
    assert result["decelerating"] is False
    assert all(r >= 1.0 for r in result["step_ratios"])
    assert "no limit in sight" in result["reading"]


def test_a_constant_mean_degree_is_converged_not_flowing():
    result = density_diagnostic([4.0, 4.0, 4.0, 4.0], SIZES[:4])
    assert result["flowing"] is False and result["converged_at_this_rung"] is True


def test_an_erdos_renyi_giant_component_is_not_flowing():
    assert density_diagnostic([2.62, 2.55, 2.547, 2.541], SIZES[:4])["flowing"] is False
    assert MEAN_DEGREE_DRIFT_TOLERANCE == 0.03


def test_fewer_than_three_rungs_is_not_evaluable():
    result = density_diagnostic([3.0, 3.3], [4096, 16384])
    assert result["evaluable"] is False and result["flowing"] is False


def test_missing_degrees_are_skipped_not_treated_as_zero():
    result = density_diagnostic([None, 2.5, None, 2.55, 2.56], SIZES)
    assert result["rungs_compared"] == 3
    assert result["flowing"] is False


def test_a_flowing_law_has_its_points_withheld_and_its_convergence_remembered():
    from graph_scale_dynamics.research.stability_score import score_law

    FLOORS = {"d_s": 0.31, "d_V": 0.03, "d_B": 0.125, "d_w": 0.077}
    vectors = {"d_s": [1.61, 1.41, 1.33, 1.30, 1.29], "d_V": [None] * 5,
               "d_B": [None] * 5, "d_w": [None] * 5}
    scored = score_law(vectors, None, floors=FLOORS, sizes=SIZES,
                       mean_degree_vector=[2.0, 2.3, 2.9, 4.1, 6.5])
    assert scored["density"]["flowing"] is True
    assert (scored["blocks"]["d_s"]["score"], scored["blocks"]["mean_degree"]["score"]) == (0.0, 0.0)
    assert scored["blocks"]["d_s"]["bucket"] == DENSITY_FLOWING_BUCKET
    assert scored["blocks"]["d_s"].get("converged_before_density_gate") in (True, None), (
        "remembered where the block had settled, so probation can still buy a rung")


def test_the_density_bucket_is_counted_not_dropped():
    assert DENSITY_FLOWING_BUCKET in gate_bucket_names()
