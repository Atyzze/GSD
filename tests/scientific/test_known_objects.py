from __future__ import annotations

import math

import numpy as np
import pytest

from graph_scale_dynamics.measurements.calibration import (
    CRT_DS, balanced_tree, erdos_renyi_graph, random_regular_graph,
    uniform_random_tree)
from graph_scale_dynamics.measurements.estimators import (
    _measure_graph, build_adjacency, largest_component)

pytestmark = pytest.mark.scientific


def _probe(n, edges, seed=0):
    result, _curves = _measure_graph(n, edges, np.random.default_rng(seed),
                                     measure_geometry=True)
    out = {}
    for channel, key in (("d_s", "d_s"), ("d_B", "d_B"), ("d_w", "d_w"), ("d_V", "d_V_window")):
        entry = result.get(channel) or {}
        value = entry.get(key)
        out[channel] = (float(value) if entry.get("valid") and value is not None
                        and math.isfinite(float(value)) else None)
    adjacency = build_adjacency(n, edges)
    component = set(int(v) for v in largest_component(n, adjacency))
    inside = sum(1 for a, b in edges if a in component and b in component)
    out["mean_degree"] = 2 * inside / max(1, len(component))
    out["component"] = len(component)
    return out


def _mean(values):
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else None


@pytest.mark.parametrize("n", [1024, 4096])
def test_the_uniform_random_tree_reads_four_thirds(n):
    readings = [_probe(*uniform_random_tree(n, seed), seed) for seed in range(3)]
    d_s = _mean([r["d_s"] for r in readings])
    mean_degree = _mean([r["mean_degree"] for r in readings])
    assert d_s is not None, "d_s must read on a CRT; it is a metric object"

    assert mean_degree < 2.0, "every tree has mean degree below 2"
    assert abs(d_s - CRT_DS) < 0.20, (
        f"d_s={d_s:.3f} should be within the declared band of the exact 4/3")


def _refused(n, edges, seed=0):
    result, _curves = _measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)
    return {probe: (result[probe].get("refusal"), result[probe].get("would_have_reported"))
            for probe in ("d_s", "d_V", "d_B", "d_w")}


def test_a_balanced_binary_tree_is_read_by_no_probe_and_d_s_keeps_what_it_would_have_read():
    n, edges = balanced_tree(2, 12)
    refused = _refused(n, edges)
    assert {probe: refusal for probe, (refusal, _) in refused.items()} == dict.fromkeys(
        ("d_s", "d_V", "d_B", "d_w"), "EXPONENTIAL_GROWTH"), "its balls grow exponentially, and that decides"
    assert refused["d_s"][1] is not None, "the number d_s would have given is kept beside the refusal"


@pytest.mark.parametrize("mean_degree", [2.5, 3.0])
def test_a_sparse_random_graph_is_read_by_no_probe(mean_degree):
    for seed in range(3):
        n, edges = erdos_renyi_graph(8192, mean_degree, seed)
        refused = _refused(n, edges, seed)
        assert all(refusal == "EXPONENTIAL_GROWTH" for refusal, _ in refused.values()), refused


def test_the_random_3_regular_expander_is_read_by_no_probe():
    for seed in range(3):
        n, edges = random_regular_graph(4096, 3, seed)
        refused = _refused(n, edges, seed)
        assert all(refusal == "EXPONENTIAL_GROWTH" for refusal, _ in refused.values()), refused
    n, edges = random_regular_graph(4096, 3, 0)
    assert len(edges) == 3 * n // 2, "a 3-regular graph is very far from a tree"
    assert len(edges) - n + 1 > n / 3, "it carries a positive density of cycles"


def test_the_spectral_probe_stops_answering_above_the_band():
    readings = [_probe(*erdos_renyi_graph(8192, 4.0, seed), seed) for seed in range(2)]
    assert all(r["d_s"] is None for r in readings), (
        "d_s should refuse on a denser random graph; if it answers, the band has moved "
        "and the calibration note in erdos_renyi_dense needs re-measuring")


def test_a_real_lattice_reads_its_dimension():
    from graph_scale_dynamics.measurements.calibration import periodic_square_lattice

    n, edges = periodic_square_lattice(64)
    reading = _probe(n, edges)
    assert reading["d_s"] is not None and abs(reading["d_s"] - 2.0) < 0.3, "a 2D torus reads d_s near 2"
