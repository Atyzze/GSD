from __future__ import annotations

import itertools
import random

import numpy as np
import pytest

from tests.support import chains as SC
from graph_scale_dynamics.measurements import curvature_probe as C
from graph_scale_dynamics.measurements.calibration import periodic_cubic_lattice, periodic_square_lattice


def _projective_plane_incidence(q: int = 5) -> tuple[int, list[tuple[int, int]]]:
    points = []
    for v in itertools.product(range(q), repeat=3):
        if any(v):
            first = next(x for x in v if x)
            inverse = pow(first, -1, q)
            normal = tuple((x * inverse) % q for x in v)
            if normal not in points:
                points.append(normal)
    count = len(points)
    edges = [(i, count + j) for i, p in enumerate(points) for j, line in enumerate(points)
             if sum(a * b for a, b in zip(p, line, strict=True)) % q == 0]
    return 2 * count, edges


def _kappa(n, edges, engine=None):
    scaled, _ = C.curvature_per_edge(n, edges, engine=engine)
    degree = np.bincount(np.asarray(edges).ravel(), minlength=n)
    a, b = np.asarray(edges).T
    return scaled / (degree[a] * degree[b])


ENGINES = [False] + ([None] if C._engine() is not None else [])


@pytest.mark.parametrize("engine", ENGINES, ids=lambda e: "python" if e is False else "rust")
def test_a_flat_grid_is_flat_on_every_edge(engine):
    for n, edges in (periodic_square_lattice(8), periodic_cubic_lattice(5)):
        assert np.all(_kappa(n, edges, engine) == 0.0)


@pytest.mark.parametrize("engine", ENGINES, ids=lambda e: "python" if e is False else "rust")
def test_a_regular_graph_with_no_short_cycle_reads_minus_two_d_minus_two_over_d(engine):
    n, edges = _projective_plane_incidence(5)
    assert np.allclose(_kappa(n, edges, engine), -4.0 / 3.0)
    ring = [(i, (i + 1) % 40) for i in range(40)]
    assert np.all(_kappa(40, ring, engine) == 0.0)


def _random_graph(n: int, m: int, seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    edges = set()
    while len(edges) < m:
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            edges.add((min(u, v), max(u, v)))
    return sorted(edges, key=lambda e: rng.random())


@pytest.mark.skipif(C._engine() is None, reason="needs the Rust engine (tools/build_engine.sh)")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_engine_the_term_and_the_fallback_count_the_same_curvature(seed):
    edges = _random_graph(60, 240 + 40 * seed, seed)
    static, _ = C.curvature_per_edge(60, edges)
    ledger, _ = C.curvature_per_edge(60, edges, incremental=True)
    python, _ = C.curvature_per_edge(60, edges, engine=False)
    assert np.array_equal(static, ledger) and np.array_equal(static, python)
    assert len(set(static.tolist())) > 3, "a parity test on one value tests nothing"


@pytest.mark.skipif(C._engine() is None, reason="needs the Rust engine (tools/build_engine.sh)")
def test_the_engine_refuses_a_repeated_edge_and_a_loop():
    for bad in ([(0, 1), (1, 0)], [(2, 2)]):
        with pytest.raises(ValueError):
            C.curvature_per_edge(4, bad)


def test_the_reading_is_the_giant_component_and_says_what_it_read():
    n, edges = periodic_square_lattice(6)
    stray = [(n, n + 1), (n + 1, n + 2), (n + 2, n)]
    reading = C.read(n + 3, edges + stray)
    assert reading["measured"] and reading["component_edges"] == len(edges)
    assert reading["mean"] == 0.0 and reading["zero_share"] == 1.0 and reading["degree_weighted_mean"] == 0.0
    assert C.read(10, [])["measured"] is False


def test_a_graph_over_its_walk_budget_is_recorded_not_measured():
    n, edges = periodic_cubic_lattice(4)
    reading = C.read(n, edges, budget=10)
    assert reading["measured"] is False and "over the 10" in reading["reason"] and reading["walk_steps"] > 10


def test_the_probe_is_outside_the_calibration_closure():
    from graph_scale_dynamics.calibration.fingerprint import measurement_closure
    closure = measurement_closure()
    assert "graph_scale_dynamics/measurements/curvature_probe.py" not in closure
    assert closure == sorted(["graph_scale_dynamics/measurements/box_covering.py",
                              "graph_scale_dynamics/measurements/estimators.py",
                              "graph_scale_dynamics/measurements/fits.py",
                              "graph_scale_dynamics/measurements/walk_dimension.py"])


def test_every_analysis_records_it_on_every_chain_it_reads():
    from graph_scale_dynamics.scaleflow.one_shot import curvature_reading
    n, lattice = periodic_square_lattice(6)
    envelope = SC.envelope(n, SC.chain("empty", block={"edge_list": lattice}), SC.chain("given", block={"edge_list": lattice}))
    metrics = {"probe_seconds": {"d_s": 1.0}}
    reading = curvature_reading(n, envelope, metrics, {"given": {"edge_list": lattice}})
    assert reading["empty"]["mean"] == 0.0 and reading["given"]["mean"] == 0.0
    assert metrics["probe_seconds"]["kappa"] >= 0.0 and metrics["probe_seconds"]["d_s"] == 1.0
    assert "given" not in curvature_reading(n, envelope, {}, {}), "a chain not read has no reading"
    at_cap = curvature_reading(n, envelope, {}, {"given": {"edge_list": lattice}}, ["empty"])
    assert at_cap["empty"]["measured"] is False and at_cap["given"]["mean"] == 0.0
    refused = curvature_reading(n, envelope, {"limit_refusal": "X"}, {"given": {"edge_list": lattice}})
    assert refused["empty"]["measured"] is False and "mean-degree cap" in refused["empty"]["reason"]
