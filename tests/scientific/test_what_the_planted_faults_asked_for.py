from __future__ import annotations

import random

import numpy as np
import pytest

from graph_scale_dynamics.measurements import box_covering as B
from graph_scale_dynamics.measurements import curvature_probe as C
from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.measurements import fits as F

RADII = np.arange(1, 9)


def _balls(power: float, rate: float) -> np.ndarray:
    return (2 * RADII + 1.0) ** power * np.exp(rate * RADII)


@pytest.mark.parametrize("power,rate", [(1.0, 0.25), (1.1, 0.22)])
def test_balls_that_neither_curve_fits_by_the_margin_are_undecided_and_not_exponential(power, rate):
    growth = E.growth_of_the_balls(RADII, _balls(power, rate))
    assert abs(growth["delta_aicc"]) < E.GROWTH_AICC_MARGIN, "the case is one inside the margin either way"
    assert growth["as_an_exponential"] > 0
    assert growth["verdict"] == E.UNDECIDED, growth


def test_the_margin_is_what_calls_a_growth_exponential_or_a_power():
    exponential = E.growth_of_the_balls(RADII, _balls(0.0, 0.5))
    power = E.growth_of_the_balls(RADII, _balls(2.0, 0.0))
    assert exponential["verdict"] == E.EXPONENTIAL and exponential["delta_aicc"] >= E.GROWTH_AICC_MARGIN
    assert power["verdict"] == E.POWER and power["delta_aicc"] <= -E.GROWTH_AICC_MARGIN


def _returns_bending_by(extra: float) -> dict:
    t = np.arange(1, 4001, dtype=float)
    log_t = np.log(t)
    return {"t": t.tolist(), "p0": np.exp(-log_t - extra * np.maximum(0.0, log_t - np.log(1000.0))).tolist()}


def test_a_running_slope_that_moves_past_its_margin_is_refused_and_one_within_it_is_read():
    moving = E.fit_ds(_returns_bending_by(0.5), 10 ** 9)
    assert moving["valid"] is False and moving["refusal"] == "NOT_SETTLED", moving
    drift = moving["window"]["moves_across_it"]
    assert 2 * E.NOT_SETTLED_SHARE * abs(moving["would_have_reported"]) < drift, "past the margin by more than twice"
    settled = E.fit_ds(_returns_bending_by(0.1), 10 ** 9)
    assert settled["valid"] is True, settled
    assert settled["window"]["moves_across_it"] < E.NOT_SETTLED_SHARE * settled["d_s"]


WIDTHS = 2.0 * np.arange(1, 9) + 1.0


@pytest.mark.parametrize("power,rate", [(1.0, 0.1), (1.0, 0.15)])
def test_box_counts_between_a_power_and_an_exponential_keep_the_power_law_s_precondition(power, rate):
    log_counts = np.log(1.0e4) - power * np.log(WIDTHS) - rate * WIDTHS
    against = F.exponential_is_better(WIDTHS, log_counts)
    assert abs(against["delta_aicc"]) < F.EXPONENTIAL_AICC_MARGIN and against["exponential"] is False, against
    profile = {"valid": True, "radii": list(range(1, 9)), "box_counts": np.exp(log_counts).tolist(),
               "box_count_sd": [0.0] * 8, "covers": 1}
    read = B.fit_box_dimension(profile)
    assert read["power_law_preferred"] is True and read["power_law_precondition"] == "supported", read


def test_box_counts_that_fall_exponentially_lose_the_precondition():
    log_counts = np.log(1.0e4) - 0.3 * WIDTHS
    against = F.exponential_is_better(WIDTHS, log_counts)
    assert against["exponential"] is True and against["delta_aicc"] >= F.EXPONENTIAL_AICC_MARGIN
    profile = {"valid": True, "radii": list(range(1, 9)), "box_counts": np.exp(log_counts).tolist(),
               "box_count_sd": [0.0] * 8, "covers": 1}
    assert B.fit_box_dimension(profile)["power_law_precondition"] == "unsupported"


def _sparse_graph(n: int, m: int, seed: int) -> list[tuple[int, int]]:
    rng, edges = random.Random(seed), set()
    while len(edges) < m:
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            edges.add((min(u, v), max(u, v)))
    return sorted(edges)


def _simple_paths(adj: list[set], u: int, v: int, steps: int) -> int:
    def walk(at: int, seen: tuple, left: int) -> int:
        if left == 1:
            return int(v in adj[at] and at != u)
        return sum(walk(nxt, seen + (nxt,), left - 1) for nxt in adj[at] if nxt not in seen and nxt != v)
    return sum(walk(x, (u, x), steps - 1) for x in adj[u] if x != v)


@pytest.mark.parametrize("n,m,seed", [(24, 30, 1), (24, 48, 2), (24, 72, 3), (40, 60, 4)])
def test_the_fallback_counts_each_edge_s_short_cycles_as_its_simple_paths(n, m, seed):
    edges = _sparse_graph(n, m, seed)
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    triangles = 0
    for u, v in edges:
        counted = C.cycle_counts_python(adj, u, v)
        assert counted == tuple(_simple_paths(adj, u, v, k) for k in (2, 3, 4)), (u, v, counted)
        triangles += counted[0]
    assert triangles, "the graphs hold triangles, where a path can come back through its own vertex"


@pytest.mark.skipif(C._engine() is None, reason="needs the Rust engine (tools/build_engine.sh)")
@pytest.mark.parametrize("m,seed", [(60, 3), (90, 5), (120, 3), (120, 7)])
def test_the_engine_and_the_fallback_agree_on_sparse_graphs_too(m, seed):
    edges = _sparse_graph(60, m, seed)
    engine, _ = C.curvature_per_edge(60, edges)
    fallback, _ = C.curvature_per_edge(60, edges, engine=False)
    assert np.array_equal(engine, fallback)
