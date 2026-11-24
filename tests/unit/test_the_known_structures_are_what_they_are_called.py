from __future__ import annotations

from collections import Counter

import pytest

from graph_scale_dynamics.measurements import estimators as E
from graph_scale_dynamics.research import known_structures as K
from graph_scale_dynamics.research import probes_known_answers as L


def _degrees(n, edges):
    count = Counter()
    for v, w in edges:
        count[v] += 1
        count[w] += 1
    return Counter(count[v] for v in range(n))


def _connected(n, edges) -> bool:
    return len(E.largest_component(n, E.build_adjacency(n, edges))) == n


@pytest.mark.parametrize("built,nodes,degrees", [
    (K.kagome_torus(6), 108, {4: 108}), (K.diamond_torus(5), 250, {4: 250}),
    (K.hypercubic_torus(4, 5), 1024, {10: 1024}), (K.hypercubic_torus(5, 3), 125, {6: 125}),
    (K.sierpinski_tetrahedron(1), 10, {3: 4, 6: 6}), (K.sierpinski_tetrahedron(4), (4 ** 5 + 4) // 2, {3: 4, 6: 510}),
])
def test_a_lattice_or_fractal_has_its_count_its_neighbours_and_one_piece(built, nodes, degrees):
    n, edges = built
    assert n == nodes and dict(_degrees(n, edges)) == degrees and _connected(n, edges)
    assert len(set(edges)) == len(edges) and all(v < w for v, w in edges)


@pytest.mark.parametrize("generation", [1, 2, 4])
def test_the_vicsek_fractal_is_a_tree_of_five_copies_a_generation(generation):
    n, edges = K.vicsek_fractal(generation)
    assert n == 5 ** generation and len(edges) == n - 1 and _connected(n, edges)
    assert max(_degrees(n, edges)) == 4


@pytest.mark.parametrize("built,nodes,degrees", [
    (K.box_torus((50, 4)), 200, {4: 200}), (K.box_torus((12, 12, 4)), 576, {6: 576}),
    (K.box_torus((30,)), 30, {2: 30}), (K.king_torus(9), 81, {8: 81}),
    (K.open_square(7), 49, {2: 4, 3: 20, 4: 25}),
    (K.subdivided(*K.box_torus((6, 6)), 3), 36 + 72 * 2, {4: 36, 2: 144}),
])
def test_a_strip_a_slab_a_king_lattice_an_open_patch_and_a_subdivided_lattice_are_what_they_are_called(built, nodes,
                                                                                                       degrees):
    n, edges = built
    assert n == nodes and dict(_degrees(n, edges)) == degrees and _connected(n, edges)
    assert len(set(edges)) == len(edges) and all(v < w for v, w in edges)


def test_a_box_of_equal_sides_is_the_hypercubic_torus():
    assert K.box_torus((5, 5, 5)) == K.hypercubic_torus(5, 3)
    assert K.subdivided(*K.box_torus((4, 4)), 1) == K.box_torus((4, 4))


@pytest.mark.parametrize("generation", [1, 3, 6])
def test_the_t_fractal_is_a_tree_of_three_copies_a_generation(generation):
    n, edges = K.t_fractal(generation)
    assert n == 3 ** generation + 1 and len(edges) == n - 1 and _connected(n, edges)
    assert max(_degrees(n, edges)) == 3
    adj = E.build_adjacency(n, edges)
    steps, reached = {0: 0}, [0]
    for v in reached:
        for w in adj[v]:
            if int(w) not in steps:
                steps[int(w)] = steps[v] + 1
                reached.append(int(w))
    assert steps[1] == 2 ** generation, "its two ends are twice as far apart each generation"


def test_the_two_random_structures_are_drawn_by_their_seed():
    n, edges = K.random_recursive_tree(500, 3)
    assert len(edges) == n - 1 and _connected(n, edges) and edges == K.random_recursive_tree(500, 3)[1]
    assert edges != K.random_recursive_tree(500, 4)[1]
    n, edges = K.ring_with_shortcuts(1000, 0.05, 3)
    assert 2000 < len(edges) <= 2050 and _connected(n, edges) and edges != K.ring_with_shortcuts(1000, 0.05, 4)[1]
    assert len(K.ring_with_shortcuts(1000, 0.0, 3)[1]) == 2000


def _triangles_at(n, edges):
    adj = [set() for _ in range(n)]
    for v, w in edges:
        adj[v].add(w)
        adj[w].add(v)
    return adj, [sum(len(adj[v] & adj[w]) for w in adj[v]) // 2 for v in range(n)]


def _steps_from(adj, source):
    steps, reached = {source: 0}, [source]
    for v in reached:
        for w in adj[v]:
            if w not in steps:
                steps[w] = steps[v] + 1
                reached.append(w)
    return steps


@pytest.mark.parametrize("layers", [1, 2, 4, 6])
def test_seven_triangles_meet_at_every_node_of_the_hyperbolic_tiling_but_its_rim(layers):
    n, edges = K.hyperbolic_triangles(layers)
    fibonacci = [0, 1]
    while len(fibonacci) <= 2 * layers:
        fibonacci.append(fibonacci[-1] + fibonacci[-2])
    rim = 7 * fibonacci[2 * layers]
    assert n == 1 + 7 * sum(fibonacci[2 * layer] for layer in range(1, layers + 1)), "7, 21, 56, 147 a layer"
    assert len(set(edges)) == len(edges) and all(v < w for v, w in edges) and _connected(n, edges)
    adj, triangles = _triangles_at(n, edges)
    assert all(len(adj[v]) == 7 and triangles[v] == 7 for v in range(n - rim)), "seven neighbours, seven triangles"
    assert {len(adj[v]) for v in range(n - rim, n)} <= {3, 4}, "a node of the rim has its ring and one or two inside"
    assert len(edges) == 3 * n - 3 - rim, "a disc cut into triangles, by Euler's count"
    steps = _steps_from(adj, 0)
    assert max(steps.values()) == layers and sum(1 for step in steps.values() if step == layers) == rim, (
        "a layer is the nodes that many steps from the centre")


@pytest.mark.parametrize("layers", [1, 2, 4, 6])
def test_five_squares_meet_at_every_node_of_the_other_tiling_and_no_triangle(layers):
    n, edges = K.hyperbolic_squares(layers)
    fibonacci = [0, 1]
    while len(fibonacci) <= 2 * layers:
        fibonacci.append(fibonacci[-1] + fibonacci[-2])
    rim = 5 * fibonacci[2 * layers]
    assert n == 1 + 5 * sum(fibonacci[2 * layer] for layer in range(1, layers + 1))
    assert len(set(edges)) == len(edges) and all(v < w for v, w in edges) and _connected(n, edges)
    adj, triangles = _triangles_at(n, edges)
    assert not any(triangles), "squares only"
    assert all(len(adj[v]) == 5 for v in range(n - rim))
    steps = _steps_from(adj, 0)
    assert all(steps[v] % 2 != steps[w] % 2 for v, w in edges), "every edge joins a layer to the next"
    two_layers_inside = n - rim - 5 * fibonacci[2 * layers - 2] if layers > 1 else 0
    squares_at = [sum(len(adj[a] & adj[b]) - 1 for i, a in enumerate(sorted(adj[v])) for b in sorted(adj[v])[i + 1:])
                  for v in range(two_layers_inside)]
    assert set(squares_at) <= {5}, "five squares at every node two layers or more inside the rim"


def test_fewer_faces_at_a_node_than_a_hyperbolic_tiling_has_are_refused():
    with pytest.raises(ValueError):
        K.hyperbolic_triangles(3, at_a_node=6)
    with pytest.raises(ValueError):
        K.hyperbolic_squares(3, at_a_node=4)
    assert K.hyperbolic_triangles(2, at_a_node=8)[0] == 1 + 8 + 8 * 4


def _every_pair_within(out, angle, within):
    import numpy as np
    return {(a, int(b)) for a in range(len(out))
            for b in np.flatnonzero(K.hyperbolically_within(out[a], angle[a], out, angle, within)) if a < b}


@pytest.mark.parametrize("seed", [0, 1])
def test_the_hyperbolic_random_graphs_join_exactly_the_pairs_within_their_distance(seed):
    import math

    from graph_scale_dynamics.research import planted_geometries as planted
    n = 500
    for within, alpha in ((None, 0.75), (0.5, 1.0), (1.0, 1.0), (2.5, 1.0)):
        disc = (2.0 * math.log(n * 2.0 * 9.0 / (math.pi * 8.0)) if within is None
                else math.acosh(1.0 + n * (math.cosh(within) - 1.0) / 10.0))
        out, angle = K.hyperbolic_points(n, disc, alpha, seed)
        assert float(out.max()) <= disc
        found = set(planted._pairs(n, *K.joined_within(out, angle, disc if within is None else within)))
        assert found == _every_pair_within(out, angle, disc if within is None else within), (within, alpha)
    assert K.hyperbolic_random_graph(n, 8.0, 0.75, seed) == K.hyperbolic_random_graph(n, 8.0, 0.75, seed)
    assert K.hyperbolic_random_graph(n, 8.0, 0.75, seed) != K.hyperbolic_random_graph(n, 8.0, 0.75, seed + 5)
    with pytest.raises(ValueError):
        K.hyperbolic_random_graph(n, 8.0, 0.5, seed)


def test_the_hyperbolic_structures_are_thin_where_a_lattice_is_not():
    flat = K.four_point_thinness(*K.box_torus((40, 40)), 28, 1)
    assert flat["largest"] >= 8 and flat["furthest_apart"] >= 30, "on a square lattice a thinness of the lattice's order"
    for built in (K.hyperbolic_triangles(6), K.hyperbolic_squares(6), K.hyperbolic_geometric_graph(4096, 12.0, 1.0, 3),
                  K.hyperbolic_random_graph(4096, 8.0, 0.75, 3)):
        thin = K.four_point_thinness(*built, 28, 1)
        assert thin["fours"] == 20475 and thin["largest"] <= 2.5 and thin["largest"] <= 0.2 * thin["furthest_apart"], thin
    tree = K.four_point_thinness(*K.random_recursive_tree(600, 2), 28, 1)
    assert tree["largest"] == 0.0, "a tree is as thin as a graph can be: thinness alone does not tell a geometry"


def _criterion(structure):
    return {"seeds": [0, 1, 2], "structures": [structure]}


def test_a_structure_may_be_read_on_seeds_of_its_own():
    structure = {"name": "s", "build": "ring", "sizes": [64], "seeds": [5]}
    rows = L.measure(_criterion(structure))
    assert [row["seed"] for row in rows] == [5] and rows[0]["built"]
    assert set(rows[0]["probes"]) == set(L.EVERY_PROBE)
