from __future__ import annotations

import math
from collections import defaultdict, deque

import pytest

from graph_scale_dynamics.research import planted_geometries as P


def _connected(n, edges):
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    seen, todo = {0}, deque([0])
    while todo:
        for w in adj[todo.popleft()]:
            if w not in seen:
                seen.add(w)
                todo.append(w)
    return len(seen) == n


def _simple(n, edges):
    return all(0 <= a < b < n for a, b in edges) and len(set(edges)) == len(edges)


@pytest.mark.parametrize("family", sorted(P.FAMILIES))
def test_every_family_builds_one_simple_connected_graph(family):
    built = P.FAMILIES[family]["build"](1024, 1)
    assert built is not None, f"{family} has no graph at 1,024"
    n, edges = built
    assert n > 200 and _simple(n, edges), f"{family}: {n} nodes, edges not simple"
    assert _connected(n, edges), f"{family} came out in pieces"


def test_a_random_geometric_graph_has_the_mean_degree_it_was_asked_for():
    n, edges = P.random_geometric(4096, 3, 10.0, 2)
    assert 9.0 < 2 * len(edges) / n < 10.5


def test_the_gasket_has_its_known_size():
    n, edges = P.sierpinski_gasket(5)
    assert n == (3 ** 6 + 3) // 2 and len(edges) == 3 ** 6


def test_a_tree_has_one_edge_fewer_than_nodes_and_one_piece():
    n, edges = P.random_tree(2000, 4)
    assert len(edges) == n - 1 and _connected(n, edges)


@pytest.mark.parametrize("k", [3, 6])
def test_a_regular_graph_is_regular_and_simple(k):
    n, edges = P.random_regular(4096, k, 5)
    degree = defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    assert _simple(n, edges) and set(degree.values()) == {k}


def test_an_erdos_renyi_graph_is_not_crowded_onto_its_low_labels():
    n, edges = P.erdos_renyi(4000, 4.0, 3)
    degree = defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    low = sum(degree[v] for v in range(n // 2)) / sum(degree.values())
    assert 0.45 < low < 0.55


def test_a_subdivided_graph_keeps_its_branch_nodes_at_degree_three():
    n, edges = P.subdivided_regular(2000, 4, 1)
    degree = defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    assert set(degree.values()) == {2, 3}
    assert math.isclose(sum(1 for d in degree.values() if d == 3) / n, 1 / 5.5, rel_tol=0.05)


def test_the_same_seed_builds_the_same_graph():
    assert P.random_geometric(1024, 2, 8.0, 7) == P.random_geometric(1024, 2, 8.0, 7)
    assert P.random_geometric(1024, 2, 8.0, 7) != P.random_geometric(1024, 2, 8.0, 8)
