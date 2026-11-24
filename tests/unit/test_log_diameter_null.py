from __future__ import annotations

import math

import pytest

from graph_scale_dynamics.scaleflow.ladder import radius_scaling_dimension

LADDER = (64, 256, 1024, 4096, 16384)


def manifold(d: float, noise: float = 0.0):
    return [{"component_size": v,
             "half_volume_radius": 4.0 * (v / 64.0) ** (1.0 / d)
                                   * (1.0 + noise * ((i % 3) - 1))}
            for i, v in enumerate(LADDER)]


def bounded_diameter(noise: float = 0.0):
    return [{"component_size": v, "half_volume_radius": math.log(v) * (1.0 + noise * ((i % 3) - 1))}
            for i, v in enumerate(LADDER)]


def test_the_predicted_slope_is_a_property_of_the_ladder_alone():
    expected = math.log(math.log(LADDER[-1]) / math.log(LADDER[0])) / math.log(LADDER[-1] / LADDER[0])
    assert expected == pytest.approx(0.1528, abs=5e-4)
    out = radius_scaling_dimension(bounded_diameter())
    assert out["log_diameter_slope"] == pytest.approx(expected, abs=1e-6)


def test_a_bounded_diameter_graph_is_refused_a_dimension():
    out = radius_scaling_dimension(bounded_diameter())
    assert out["verdict"] == "no_metric_structure"
    assert out["dimension"] is None
    assert out["log_diameter_separation_sigma"] < 2.0


def test_the_campaign_2_outliers_no_longer_score_a_dimension():
    out = radius_scaling_dimension(bounded_diameter(noise=0.004))
    assert out["dimension"] is None, (
        f"a log-diameter radius was awarded d = {out.get('dimension')}: "
        f"{out.get('reason')}")
    assert out["slope"] == pytest.approx(0.1528, abs=0.01)


@pytest.mark.parametrize("d", [2.0, 3.0, 4.0])
def test_a_real_geometry_still_reports_its_dimension(d):
    out = radius_scaling_dimension(manifold(d, noise=0.01))
    assert out["dimension"] is not None, out.get("reason")
    assert out["dimension"] == pytest.approx(d, rel=0.15)
    assert out["log_diameter_separation_sigma"] > 2.0


def test_the_ladder_states_the_dimension_it_cannot_resolve():
    out = radius_scaling_dimension(bounded_diameter())
    assert "cannot resolve a dimension above" in out["reason"]
    six = radius_scaling_dimension(manifold(6.0, noise=0.02))
    assert six["log_diameter_separation_sigma"] < 6.0, (
        "d=6 should be marginal on a 64..16,384 ladder; if this ever becomes "
        "comfortable the ladder or the estimator changed and the resolving-power "
        "claim in the reason string needs rewriting")


def test_a_shrinking_radius_is_not_a_dimension():
    collapsing = radius_scaling_dimension(
        [{"component_size": float(n), "half_volume_radius": r}
         for n, r in zip(LADDER, [9.0, 8.0, 6.0, 4.0, 3.1], strict=True)])
    assert collapsing["verdict"] == "no_metric_structure"
    assert collapsing["dimension"] is None
    assert "shrank" in collapsing["reason"]


def test_a_near_path_graph_is_allowed_because_it_is_possible():
    out = radius_scaling_dimension(
        [{"component_size": float(n), "half_volume_radius": 1.0 * (n / 64.0) ** 0.76}
         for n in LADDER])
    assert out["dimension"] is not None
    assert 1.0 <= out["dimension"] <= 1.6, out.get("reason")


def test_a_dimension_below_one_is_refused():
    out = radius_scaling_dimension(
        [{"component_size": float(n), "half_volume_radius": 1.0 * (n / 64.0) ** 1.4}
         for n in LADDER])
    assert out["dimension"] is None
    assert "denser than a path" in out["reason"]
