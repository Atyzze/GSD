from __future__ import annotations

from collections import Counter

import pytest

from graph_scale_dynamics.measurements import calibration as C
from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements import random_starts as R
from graph_scale_dynamics.measurements.calibration import control_family_edges, control_family_reaches

LADDER = [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304]
LATTICES = {"periodic_honeycomb_lattice": 3, K.CUBIC_QUOTIENT: 6, K.TESSERACT_QUOTIENT: 8}


def _degrees(n: int, edges) -> Counter:
    degree = Counter()
    for a, b in edges:
        assert 0 <= a < b < n
        degree[a] += 1
        degree[b] += 1
    return degree


def test_every_lattice_start_reaches_every_rung_of_the_ladder():
    for family in LATTICES:
        for n in LADDER:
            assert control_family_reaches(family, n), (family, n)
    assert [K._fold4(n) for n in LADDER] == [(2, 4), (4, 1), (4, 4), (8, 1), (8, 4), (16, 1), (16, 4), (32, 1),
                                             (32, 4)]
    assert not control_family_reaches(K.TESSERACT_QUOTIENT, 16), "2 by 2 by 2 by 2 merges each step with its reverse"
    assert not control_family_reaches(K.TESSERACT_QUOTIENT, 512)


@pytest.mark.parametrize("family", sorted(LATTICES))
@pytest.mark.parametrize("n", [64, 256, 1024, 4096, 16384])
def test_every_node_of_a_lattice_start_has_its_lattice_s_neighbours(family, n):
    edges = control_family_edges(family, n)
    degree = _degrees(n, edges)
    assert len(degree) == n and set(degree.values()) == {LATTICES[family]}, (family, n)
    assert len(edges) == len(set(edges)) == LATTICES[family] * n // 2, "each link once, none to itself"


def test_the_4d_lattice_at_64_nodes_is_the_fold_of_index_4_with_every_neighbour():
    size, edges = K.periodic_tesseract_quotient(64)
    assert size == 64 and len(edges) == 256 and set(_degrees(64, edges).values()) == {8}
    neighbours = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    assert not any(neighbours[a] & neighbours[b] for a, b in edges), "a 4D lattice has no triangle"


@pytest.mark.parametrize("side", [4, 8])
def test_the_4d_torus_is_the_calibration_family_s_node_for_node(side):
    assert K.periodic_tesseract_quotient(side ** 4)[1] == C.periodic_hypercubic_lattice_4d(side)[1]


@pytest.mark.parametrize("side", [4, 6, 8, 10, 16, 32, 64])
def test_the_honeycomb_here_is_the_calibration_family_s_node_for_node(side):
    assert K.periodic_honeycomb_torus(side * side)[1] == C.periodic_honeycomb_lattice(side)[1]


def test_the_honeycomb_start_reaches_past_the_calibration_ladder():
    assert K.reaches(K.HONEYCOMB_TORUS, 2048 ** 2) and not K.reaches(K.HONEYCOMB_TORUS, 9)
    assert not K.reaches(K.HONEYCOMB_TORUS, 2 * 2), "a side of 2 folds each node's two links along y into one"


def test_the_random_start_s_degree_is_drawn_once_a_law_uniformly_up_to_the_cap():
    degrees = [R.drawn_degree(f"{index:064x}", "random", 16.0) for index in range(4000)]
    assert all(0.0 < d <= 16.0 for d in degrees)
    assert abs(sum(degrees) / len(degrees) - 8.0) < 0.3
    assert 0.04 < sum(d < 1.0 for d in degrees) / len(degrees) < 0.085, "one law in 16 below a mean degree of 1"
    assert R.drawn_degree("a" * 64, "random", 16.0) == R.drawn_degree("a" * 64, "random", 16.0)
    assert R.drawn_degree("a" * 64, "random", 16.0) != R.drawn_degree("a" * 64, "random_2", 16.0), \
        "two random starts of one law are drawn apart"
    family = R.drawn_family("a" * 64, "random", 16.0)
    assert R.parse(family) == round(R.drawn_degree("a" * 64, "random", 16.0), 6)
    assert R.family(16.0) == "random_mean_degree_16" and R.family(0.5) == "random_mean_degree_0.5"
    assert R.parse("random_mean_degree_0") is None and R.parse("periodic_honeycomb_lattice") is None


@pytest.mark.parametrize("n", [64, 256, 4096])
def test_the_random_start_is_a_uniform_random_graph_at_its_degree(n):
    family = R.family(7.3)
    edges = control_family_edges(family, n, seed=3)
    assert edges == sorted(set(edges)) and all(0 <= a < b < n for a, b in edges)
    assert len(edges) == R.links(n, 7.3) == round(7.3 * n / 2)
    assert edges == control_family_edges(family, n, seed=3), "the same law, N and seed: the same start"
    assert edges != control_family_edges(family, n, seed=4), "each seed its own graph"
    assert control_family_reaches(family, n)


def test_the_random_start_keeps_both_ends_of_its_draw():
    assert R.build(64, 0.01, 1) == [], "under one link at this N the start is empty, and still a start"
    assert len(R.build(17, 16.0, 1)) == 17 * 16 // 2, "at the cap on 17 nodes it is every pair"
    assert not R.reaches(R.family(16.0), 16), "more links than pairs is no graph"
