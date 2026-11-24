from __future__ import annotations

import pytest

from graph_scale_dynamics.research.stability_score import (
    metric_class_population, score_law)

PROBES = ("d_s", "d_V", "d_B", "d_w")
SIZES = [64, 256, 1024, 4096, 16384]
FLOORS = {"d_s": 0.2433, "d_B": 0.1355, "d_V": 0.0545, "d_w": 0.0792}

GATE_AGGREGATES = {"control_family": "control_families",
                   "density": "density", "metric_class": "metric_class"}


def _law(radius):
    return score_law(
        {p: [2.0, 2.1, 2.2, 2.25, 2.3] if p == "d_s" else [None] * 5 for p in PROBES},
        {p: [None] * 5 for p in PROBES}, floors=FLOORS, sizes=list(SIZES),
        probe_se_vectors={p: [0.05] * 5 for p in PROBES},
        connectivity_vector=[1.0] * 5, connectivity_floor=0.9,
        mean_degree_vector=[3.0] * 5, clustering_vector=[None] * 5,
        half_volume_radius_vector=list(radius))


PLANE = [4.0, 8.0, 16.0, 32.0, 64.0]
SMALL_WORLD = [4.2, 5.5, 6.6, 7.6, 8.5]


def test_every_per_law_gate_block_has_a_body_aggregate():
    row = _law(PLANE)
    gates = {k for k, v in row.items()
             if isinstance(v, dict) and ("gate_applied" in v or "withheld_points" in v)}
    unmapped = sorted(gates - set(GATE_AGGREGATES))
    assert not unmapped, (
        f"these gate blocks are computed per law and aggregated nowhere: {unmapped}. "
        "A gate published only through `ranked` is published for the top 100 laws, "
        "which is a sample, not a population. Add an aggregate to the report body "
        "and name it in GATE_AGGREGATES.")


def test_the_metric_class_aggregate_counts_the_whole_population_not_the_ranked_cut():
    population = [_law(SMALL_WORLD) for _ in range(150)] + [_law(PLANE) for _ in range(7)]
    agg = metric_class_population(population)
    assert agg["laws_scored"] == 157, "the denominator is every scored law"
    assert agg["logarithmic_radius"] + agg["power_law_radius"] + agg["untested"] == 157, (
        "the three outcomes must sum to the population, or the table is not a "
        "summary of it")
    assert agg["logarithmic_radius"] >= 150 > 100, (
        "the aggregate must see past the ranked cut; this is the whole point")


def test_a_plane_and_a_small_world_graph_land_on_opposite_verdicts():
    plane = (_law(PLANE).get("metric_class") or {})
    small = (_law(SMALL_WORLD).get("metric_class") or {})
    assert plane.get("logarithmic_wins") is False, (
        f"a radius growing as sqrt(N) was called logarithmic: {plane.get('reason')}")
    assert small.get("logarithmic_wins") is True, (
        f"a radius growing as log(N) was called a power law: {small.get('reason')}")
    assert plane["radius_growth"] > 3 * small["radius_growth"], (
        "radius_growth is the number read beside the verdict and must separate "
        "these two by a wide margin")


def test_radius_growth_percentiles_are_ordered():
    agg = metric_class_population([_law(SMALL_WORLD) for _ in range(20)]
                                  + [_law(PLANE) for _ in range(20)])
    g = agg["radius_growth"]
    assert g["count"] == 40
    assert g["min"] <= g["p10"] <= g["median"] <= g["p90"] <= g["max"]


def test_the_aicc_comparison_survives_into_the_rung_summary():
    from graph_scale_dynamics.scaleflow.flow import _diffusive_evidence

    def seed(delta, gap, power, comparable=True):
        return {"d_s": {"valid": delta > 2.0, "diffusive_window_evidence": {
            "comparable": comparable, "delta_aicc": delta, "gap_decay_rate": gap,
            "power_law_exponent": power, "is_power_law": delta > 2.0}}}

    out = _diffusive_evidence([seed(3.0, 0.029, -1.0), seed(1.0, 0.031, -1.1)])
    assert out["seeds_comparable"] == 2
    assert out["delta_aicc"] == pytest.approx(2.0)
    assert out["gap_decay_rate"] == pytest.approx(0.030)
    assert out["seeds_calling_it_a_power_law"] == 1


def test_a_seed_with_no_comparison_is_not_counted_as_a_zero():
    from graph_scale_dynamics.scaleflow.flow import _diffusive_evidence

    usable = {"d_s": {"valid": True, "diffusive_window_evidence": {
        "comparable": True, "delta_aicc": 8.0, "gap_decay_rate": 0.02,
        "power_law_exponent": -1.0, "is_power_law": True}}}
    short = {"d_s": {"valid": False, "diffusive_window_evidence": {
        "comparable": False, "reason": "window too short for a model comparison"}}}
    out = _diffusive_evidence([usable, short, short])
    assert out["seeds_comparable"] == 1 and out["seeds"] == 3
    assert out["delta_aicc"] == pytest.approx(8.0)
    assert _diffusive_evidence([short])["seeds_comparable"] == 0
    assert _diffusive_evidence([short]).get("delta_aicc") is None
