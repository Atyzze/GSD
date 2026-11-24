from __future__ import annotations

import math

import pytest

from graph_scale_dynamics.research.stability_score import (
    metric_class_population, score_law)
from graph_scale_dynamics.scaleflow.ladder import radius_scaling_dimension

PROBES = ("d_s", "d_V", "d_B", "d_w")
SIZES = [64, 256, 1024, 4096, 16384]
FLOORS = {"d_s": 0.2433, "d_B": 0.1355, "d_V": 0.0545, "d_w": 0.0792}

DECLARED_DROPS = {"slope_interval", "residual_rms", "power_law_rms",
                  "logarithmic_rms", "required"}


def _law(radius):
    return score_law(
        {p: [2.0, 2.1, 2.2, 2.25, 2.3] if p == "d_s" else [None] * 5 for p in PROBES},
        {p: [None] * 5 for p in PROBES}, floors=FLOORS, sizes=list(SIZES),
        probe_se_vectors={p: [0.05] * 5 for p in PROBES},
        connectivity_vector=[1.0] * 5, connectivity_floor=0.9,
        mean_degree_vector=[3.0] * 5, clustering_vector=[None] * 5,
        half_volume_radius_vector=list(radius))


PLANE = [4.0, 8.0, 16.0, 32.0, 64.0]
LOG_DIAMETER = [math.log(n) for n in SIZES]


def test_every_field_the_fitter_produces_reaches_the_published_cell():
    fitted = radius_scaling_dimension(
        [{"component_size": float(n), "half_volume_radius": r}
         for n, r in zip(SIZES, LOG_DIAMETER, strict=True)])
    published = _law(LOG_DIAMETER)["metric_class"]
    lost = sorted(set(fitted) - set(published) - DECLARED_DROPS)
    assert not lost, (
        f"the fitter produces these and the report never sees them: {lost}. "
        "Carry them, or name them in DECLARED_DROPS with a reason.")


def test_the_null_publishes_the_distance_that_justifies_it():
    cell = _law(LOG_DIAMETER)["metric_class"]
    assert cell["verdict"] == "no_metric_structure"
    assert cell["log_diameter_slope"] == pytest.approx(0.1528, abs=5e-4)
    assert cell["log_diameter_separation_sigma"] < 2.0
    assert isinstance(cell["log_diameter_separation_sigma"], float)


def test_the_aggregate_counts_the_verdict_and_not_the_superseded_comparison():
    population = [_law(LOG_DIAMETER) for _ in range(44)] + [_law(PLANE) for _ in range(6)]
    agg = metric_class_population(population)
    assert agg["logarithmic_radius"] == 44
    assert agg["power_law_radius"] == 6
    assert agg["logarithmic_radius"] + agg["power_law_radius"] \
        + agg["undetermined"] + agg["untested"] == agg["laws_scored"]


def test_the_aggregate_never_contradicts_the_rows_it_summarises():
    population = [_law(LOG_DIAMETER) for _ in range(44)]
    agg = metric_class_population(population)
    reporting_a_dimension = sum(
        1 for r in population if (r.get("metric_class") or {}).get("dimension") is not None)
    assert agg["power_law_radius"] == reporting_a_dimension, (
        "a law counted as power-law must be a law that reports a dimension")
    assert agg["logarithmic_radius"] == 44


def test_a_disagreement_between_the_verdict_and_the_old_comparison_is_counted():
    agg = metric_class_population([_law(LOG_DIAMETER) for _ in range(3)])
    assert "residual_comparison_disagrees" in agg
    assert agg["residual_comparison_disagrees"] >= 0
