from __future__ import annotations

import random

import numpy as np
import pytest

from graph_scale_dynamics.measurements.calibration import periodic_square_lattice, random_regular_graph
from graph_scale_dynamics.measurements.estimators import _measure_graph, build_adjacency, largest_component
from tests.support.calibration_table import skip_module_without_table

skip_module_without_table()

from graph_scale_dynamics.research.stability_score import (
    WITHHELD_SETTLED_BUCKETS, score_rung_rows)
from graph_scale_dynamics.scaleflow.flow import rung_summary
from graph_scale_dynamics.research.score_door import table_noise_floors as _noise_floors
from graph_scale_dynamics.scheduling.limits import mean_degree_window

LADDER = (64, 256, 1024, 4096)
FLOOR = 0.9


def _measure(n: int, edges, seed: int) -> dict:
    result, _ = _measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)
    adj = build_adjacency(n, edges)
    component = largest_component(n, adj)
    result["health"] = {"connected_fraction": len(component) / n, "mean_degree": 2 * len(edges) / n}
    return result


def _score(builds) -> dict:
    floors, floors_by_n = _noise_floors()
    rows = []
    for build in builds:
        n, edges = build()
        per_seed = [_measure(n, edges, seed) for seed in range(2)]
        rows.append({"n": n, "summary": rung_summary(per_seed),
                     "terminal_classification": None, "chains_verdict": None})
    return score_rung_rows(rows, floors=floors, floors_by_n=floors_by_n, connectivity_floor=FLOOR)


def binary_tree(n: int):
    return n, [(i, (i - 1) // 2) for i in range(1, n)]


def sparse_er(n: int, mean_degree: float = 3.0, seed: int = 0):
    rng = random.Random(seed)
    wanted = int(n * mean_degree / 2)
    edges: set = set()
    while len(edges) < wanted:
        a, b = rng.randrange(n), rng.randrange(n)
        if a != b:
            edges.add((min(a, b), max(a, b)))
    return n, sorted(edges)


def k44_dust(n: int):
    blocks = n // 8
    edges = [(base + i, base + j) for base in range(0, blocks * 8, 8)
             for i in range(4) for j in range(4, 8)]
    return blocks * 8, edges


NO_LONGER_READ = ("DEGRADED_WITH_N", "REFUSED_NO_SCALING_WINDOW")


def _withheld(scored: dict) -> bool:
    return not any(b == "CONVERGED" for b in scored["buckets"].values())


@pytest.mark.parametrize("name,build,expect_gate", [
    ("balanced binary tree", binary_tree, (*WITHHELD_SETTLED_BUCKETS, *NO_LONGER_READ, "NO_METRIC_STRUCTURE")),
    ("sparse Erdos-Renyi <d>=3", sparse_er, ("NO_METRIC_STRUCTURE", *NO_LONGER_READ, *WITHHELD_SETTLED_BUCKETS)),
    ("random 4-regular", lambda n: random_regular_graph(n, 4, seed=1), None),
])
def test_bounded_diameter_graphs_earn_nothing(name, build, expect_gate):
    scored = _score([lambda n=n: build(n) for n in LADDER])
    assert _withheld(scored), (name, scored["buckets"])
    if expect_gate:
        assert scored["buckets"]["d_s"] in expect_gate, (name, scored["buckets"])
    assert scored["metric_class"]["verdict"] == "no_metric_structure", (name, scored["metric_class"])


def test_disjoint_k44_blocks_are_refused_below_the_connectivity_floor():
    scored = _score([lambda n=n: k44_dust(n) for n in LADDER])
    assert all(b == "REFUSED_BELOW_CONNECTIVITY_FLOOR" for b in scored["buckets"].values()), scored["buckets"]


def test_a_star_is_refused_by_every_estimator_and_a_complete_graph_by_the_window():
    star = lambda n: (n, [(0, i) for i in range(1, n)])
    scored = _score([lambda n=n: star(n) for n in LADDER])
    assert all(b == "REFUSED_NO_SCALING_WINDOW" for p, b in scored["buckets"].items() if p != "d_s"), scored["buckets"]
    assert scored["buckets"]["d_s"] in ("REFUSED_NO_SCALING_WINDOW", "DEGRADED_WITH_N"), scored["buckets"]
    lo, hi = mean_degree_window({})
    assert all((n - 1) >= hi for n in LADDER), "a complete graph is above the window at every rung"
    assert lo <= 2 * (LADDER[-1] - 1) / LADDER[-1] < hi, "the star is inside the window; refusal is the estimators' job"


def test_a_square_lattice_is_read_as_a_plane():
    scored = _score([lambda s=s: periodic_square_lattice(s) for s in (8, 16, 32, 64)])
    assert scored["buckets"]["d_s"] == "CONVERGED" and scored["buckets"]["d_B"] == "INSIDE_NOISE_TOO_FEW_RUNGS"
    metric = scored["metric_class"]
    assert metric["verdict"] == "metric" and abs(metric["dimension"] - 2.0) < 0.15, metric
    assert "tree_line" not in scored
