from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.measurements import hyperbolic_graphs


def kagome_torus(side: int) -> tuple[int, list[tuple[int, int]]]:
    def node(i, j, s):
        return 3 * ((i % side) * side + (j % side)) + s
    edges = set()
    for i in range(side):
        for j in range(side):
            a, b, c = node(i, j, 0), node(i, j, 1), node(i, j, 2)
            for v, w in ((a, b), (a, c), (b, c), (b, node(i + 1, j, 0)), (c, node(i, j + 1, 0)),
                         (b, node(i + 1, j - 1, 2))):
                edges.add((min(v, w), max(v, w)))
    return 3 * side * side, sorted(edges)


def diamond_torus(side: int) -> tuple[int, list[tuple[int, int]]]:
    def node(i, j, k, s):
        return 2 * (((i % side) * side + (j % side)) * side + (k % side)) + s
    edges = set()
    for i in range(side):
        for j in range(side):
            for k in range(side):
                a = node(i, j, k, 0)
                for w in (node(i, j, k, 1), node(i - 1, j, k, 1), node(i, j - 1, k, 1), node(i, j, k - 1, 1)):
                    edges.add((min(a, w), max(a, w)))
    return 2 * side ** 3, sorted(edges)


def box_torus(sides) -> tuple[int, list[tuple[int, int]]]:
    n = int(np.prod(sides))
    index = np.arange(n)
    edges = set()
    stride = 1
    for side in sides:
        digit = (index // stride) % side
        neighbour = index + np.where(digit == side - 1, -(side - 1) * stride, stride)
        for v, w in zip(index.tolist(), neighbour.tolist(), strict=True):
            if v != w:
                edges.add((min(v, w), max(v, w)))
        stride *= side
    return n, sorted(edges)


def hypercubic_torus(side: int, dimension: int) -> tuple[int, list[tuple[int, int]]]:
    return box_torus((side,) * dimension)


def king_torus(side: int) -> tuple[int, list[tuple[int, int]]]:
    def node(i, j):
        return (i % side) * side + (j % side)
    edges = set()
    for i in range(side):
        for j in range(side):
            v = node(i, j)
            for w in (node(i + 1, j), node(i, j + 1), node(i + 1, j + 1), node(i + 1, j - 1)):
                edges.add((min(v, w), max(v, w)))
    return side * side, sorted(edges)


def open_square(side: int) -> tuple[int, list[tuple[int, int]]]:
    edges = []
    for i in range(side):
        for j in range(side):
            v = i * side + j
            if i + 1 < side:
                edges.append((v, v + side))
            if j + 1 < side:
                edges.append((v, v + 1))
    return side * side, sorted(edges)


def cycle_soup(n: int, largest: int, small: int) -> tuple[int, list[tuple[int, int]]]:
    count = int(n)
    sizes = [min(count, int(largest))]
    left = count - sizes[0]
    while left >= int(small):
        sizes.append(int(small))
        left -= int(small)
    if left >= 3:
        sizes.append(left)
    edges, first = [], 0
    for size in sizes:
        edges += [(first + i, first + (i + 1) % size) if i + 1 < size else (first, first + i) for i in range(size)]
        first += size
    return count, sorted((min(v, w), max(v, w)) for v, w in edges)


def subdivided(n: int, edges, pieces: int) -> tuple[int, list[tuple[int, int]]]:
    grown, following = [], n
    for v, w in edges:
        chain = [v, *range(following, following + pieces - 1), w]
        following += pieces - 1
        grown += [(min(a, b), max(a, b)) for a, b in zip(chain, chain[1:], strict=False)]
    return following, sorted(grown)


def t_fractal(generation: int) -> tuple[int, list[tuple[int, int]]]:
    edges, n = [(0, 1)], 2
    for _ in range(generation):
        grown = []
        for v, w in edges:
            grown += [(v, n), (n, w), (n, n + 1)]
            n += 2
        edges = grown
    return n, sorted((min(v, w), max(v, w)) for v, w in edges)


def sierpinski_tetrahedron(generation: int) -> tuple[int, list[tuple[int, int]]]:
    corners = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    points = set(corners)
    edges = {(p, q) for p in corners for q in corners if p < q}
    for level in range(generation):
        scale = 2 ** level
        moved_points, moved_edges = set(), set()
        for corner in corners:
            shift = tuple(scale * c for c in corner)
            def move(p):
                return (p[0] + shift[0], p[1] + shift[1], p[2] + shift[2])
            moved_points |= {move(p) for p in points}
            moved_edges |= {tuple(sorted((move(p), move(q)))) for p, q in edges}
        points, edges = moved_points, moved_edges
    number = {p: i for i, p in enumerate(sorted(points))}
    return len(points), sorted((min(number[p], number[q]), max(number[p], number[q])) for p, q in edges)


def vicsek_fractal(generation: int) -> tuple[int, list[tuple[int, int]]]:
    points = {(0, 0)}
    for level in range(generation):
        step = 3 ** level
        points = {(x + step * dx, y + step * dy) for x, y in points for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))}
    number = {p: i for i, p in enumerate(sorted(points))}
    edges = [(number[(x, y)], number[q]) for x, y in points for q in ((x + 1, y), (x, y + 1)) if q in number]
    return len(points), sorted((min(v, w), max(v, w)) for v, w in edges)


def random_recursive_tree(n: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    return n, [(int(rng.integers(0, v)), v) for v in range(1, n)]


def ring_with_shortcuts(n: int, shortcuts_a_node: float, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    edges = {(v, (v + 1) % n) if v + 1 < n else (0, v) for v in range(n)}
    edges |= {(min(v, (v + 2) % n), max(v, (v + 2) % n)) for v in range(n)}
    for _ in range(int(round(shortcuts_a_node * n))):
        v, w = (int(x) for x in rng.integers(0, n, 2))
        if v != w:
            edges.add((min(v, w), max(v, w)))
    return n, sorted(edges)


hyperbolic_triangles = hyperbolic_graphs.hyperbolic_triangles
hyperbolic_squares = hyperbolic_graphs.hyperbolic_squares
hyperbolic_points = hyperbolic_graphs.hyperbolic_points
hyperbolically_within = hyperbolic_graphs.hyperbolically_within
joined_within = hyperbolic_graphs.joined_within


def hyperbolic_random_graph(n: int, mean_degree: float, alpha: float, seed: int) -> tuple[int, list[tuple[int, int]]]:
    from graph_scale_dynamics.research import planted_geometries as planted
    if alpha <= 0.5:
        raise ValueError("alpha must be above one half")
    disc = 2.0 * math.log(n * 2.0 * (alpha / (alpha - 0.5)) ** 2 / (math.pi * mean_degree))
    out, angle = hyperbolic_points(n, disc, alpha, seed)
    return planted._largest(n, planted._pairs(n, *joined_within(out, angle, disc)))


def hyperbolic_geometric_graph(n: int, mean_degree: float, within: float,
                               seed: int) -> tuple[int, list[tuple[int, int]]]:
    from graph_scale_dynamics.research import planted_geometries as planted
    return planted._largest(*hyperbolic_graphs.hyperbolic_geometric_points_joined(n, mean_degree, within, seed))


def four_point_thinness(n: int, edges, nodes: int, seed: int) -> dict:
    from graph_scale_dynamics.measurements.walk_dimension import _bfs_distances
    from graph_scale_dynamics.measurements.estimators import build_adjacency
    adjacency = build_adjacency(n, edges)
    rng = np.random.default_rng(seed)
    picked = rng.choice(n, size=min(nodes, n), replace=False)
    apart = np.stack([_bfs_distances(adjacency, int(v), n)[picked] for v in picked]).astype(float)
    count = len(picked)
    i, j, k, m = (np.asarray(x) for x in zip(*[(a, b, c, d) for a in range(count) for b in range(a + 1, count)
                                                for c in range(b + 1, count) for d in range(c + 1, count)],
                                              strict=True))
    sums = np.sort(np.stack([apart[i, j] + apart[k, m], apart[i, k] + apart[j, m], apart[i, m] + apart[j, k]]), axis=0)
    thinness = (sums[2] - sums[1]) / 2.0
    return {"nodes": int(count), "fours": int(len(thinness)), "largest": float(thinness.max()),
            "mean": float(thinness.mean()), "furthest_apart": float(apart.max())}
