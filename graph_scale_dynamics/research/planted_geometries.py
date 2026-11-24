from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree

from graph_scale_dynamics.measurements import known_answers

PLANTED_CONTRACT = "gsd-planted-geometries-1"


def _pairs(n: int, a, b) -> list[tuple[int, int]]:
    a, b = np.asarray(a, dtype=np.int64), np.asarray(b, dtype=np.int64)
    keep = a != b
    lo, hi = np.minimum(a[keep], b[keep]), np.maximum(a[keep], b[keep])
    code = np.unique(lo * n + hi)
    return [(int(c // n), int(c % n)) for c in code]


def _relabel(nodes: np.ndarray, edges: list[tuple[int, int]]) -> tuple[int, list[tuple[int, int]]]:
    index = {int(v): i for i, v in enumerate(nodes.tolist())}
    return len(nodes), [(index[a], index[b]) for a, b in edges if a in index and b in index]


def _largest(n: int, edges: list[tuple[int, int]]) -> tuple[int, list[tuple[int, int]]]:
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(x) for x in range(n)])
    values, counts = np.unique(roots, return_counts=True)
    keep = np.flatnonzero(roots == values[int(np.argmax(counts))])
    return _relabel(keep, [(a, b) for a, b in edges if roots[a] == values[int(np.argmax(counts))]])


def random_geometric(n: int, dimension: int, mean_degree: float, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    points = rng.random((n, dimension))
    unit_ball = math.pi ** (dimension / 2) / math.gamma(dimension / 2 + 1)
    radius = (mean_degree / (n * unit_ball)) ** (1.0 / dimension)
    pairs = cKDTree(points, boxsize=1.0).query_pairs(radius, output_type="ndarray")
    return _largest(n, _pairs(n, pairs[:, 0], pairs[:, 1]))


def sierpinski_gasket(level: int) -> tuple[int, list[tuple[int, int]]]:
    triangles = [((0, 0), (1, 0), (0, 1))]
    scale = 1
    for _ in range(level):
        scale *= 2
        nxt = []
        for a, b, c in triangles:
            a2, b2, c2 = (a[0] * 2, a[1] * 2), (b[0] * 2, b[1] * 2), (c[0] * 2, c[1] * 2)
            ab = ((a2[0] + b2[0]) // 2, (a2[1] + b2[1]) // 2)
            ac = ((a2[0] + c2[0]) // 2, (a2[1] + c2[1]) // 2)
            bc = ((b2[0] + c2[0]) // 2, (b2[1] + c2[1]) // 2)
            nxt += [(a2, ab, ac), (ab, b2, bc), (ac, bc, c2)]
        triangles = nxt
    index: dict = {}
    edges = set()
    for tri in triangles:
        ids = [index.setdefault(p, len(index)) for p in tri]
        for i in range(3):
            x, y = sorted((ids[i], ids[(i + 1) % 3]))
            edges.add((x, y))
    return len(index), sorted(edges)


def critical_percolation_cluster(side: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    n = side * side
    idx = np.arange(n).reshape(side, side)
    right = np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], axis=1)
    down = np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], axis=1)
    bonds = np.concatenate([right, down])
    bonds = bonds[rng.random(len(bonds)) < 0.5]
    return _largest(n, _pairs(n, bonds[:, 0], bonds[:, 1]))


def random_tree(n: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    prufer = rng.integers(0, n, size=n - 2)
    degree = np.ones(n, dtype=np.int64)
    np.add.at(degree, prufer, 1)
    import heapq
    leaves = [int(i) for i in np.flatnonzero(degree == 1)]
    heapq.heapify(leaves)
    edges = []
    for v in prufer.tolist():
        leaf = heapq.heappop(leaves)
        edges.append((min(leaf, v), max(leaf, v)))
        degree[v] -= 1
        if degree[v] == 1:
            heapq.heappush(leaves, v)
    a, b = heapq.heappop(leaves), heapq.heappop(leaves)
    edges.append((min(a, b), max(a, b)))
    return n, edges


def ring(n: int) -> tuple[int, list[tuple[int, int]]]:
    return n, [(i, i + 1) for i in range(n - 1)] + [(0, n - 1)]


def ring_with_chords(n: int, chords_per_node: float, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    m = max(1, int(round(chords_per_node * n)))
    a, b = rng.integers(0, n, size=m), rng.integers(0, n, size=m)
    base = ring(n)[1]
    return n, sorted(set(base) | set(_pairs(n, a, b)))


def erdos_renyi(n: int, mean_degree: float, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    m = int(round(mean_degree * n / 2))
    draws = int(m * 1.05) + 8
    a, b = rng.integers(0, n, size=draws), rng.integers(0, n, size=draws)
    keep = a != b
    lo, hi = np.minimum(a[keep], b[keep]), np.maximum(a[keep], b[keep])
    _, first = np.unique(lo * n + hi, return_index=True)
    first = np.sort(first)[:m]
    return _largest(n, [(int(x), int(y)) for x, y in zip(lo[first], hi[first], strict=True)])


def random_regular(n: int, degree: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    stubs = rng.permutation(np.repeat(np.arange(n), degree))
    pairs = [(int(min(x, y)), int(max(x, y))) for x, y in zip(stubs[0::2], stubs[1::2], strict=True)]
    seen: dict = defaultdict(int)
    for pair in pairs:
        seen[pair] += 1
    bad = [i for i, (x, y) in enumerate(pairs) if x == y or seen[(x, y)] > 1]
    while bad:
        i = bad.pop()
        a, b = pairs[i]
        if a != b and seen[(a, b)] == 1:
            continue
        j = int(rng.integers(len(pairs)))
        c, d = pairs[j]
        one, two = (min(a, c), max(a, c)), (min(b, d), max(b, d))
        if j == i or c == d or a == c or b == d or one == two or seen[one] or seen[two]:
            bad.append(i)
            continue
        seen[(a, b)] -= 1
        seen[(c, d)] -= 1
        pairs[i], pairs[j] = one, two
        seen[one] += 1
        seen[two] += 1
    return n, sorted(pairs)


def subdivided_regular(n: int, path_length: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    branch = max(4, int(round(n / (1 + 1.5 * (path_length - 1)))))
    branch += branch % 2
    _, core = random_regular(branch, 3, seed)
    edges, nxt = [], branch
    for a, b in core:
        chain = [a] + list(range(nxt, nxt + path_length - 1)) + [b]
        nxt += path_length - 1
        edges += [(min(x, y), max(x, y)) for x, y in zip(chain, chain[1:], strict=False)]
    return nxt, edges


def preferential_attachment(n: int, links: int, seed: int) -> tuple[int, list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    ends: list[int] = []
    edges = []
    for v in range(links, n):
        chosen = set()
        while len(chosen) < links:
            chosen.add(int(ends[rng.integers(len(ends))]) if ends else int(rng.integers(v)))
        for u in chosen:
            edges.append((min(u, v), max(u, v)))
            ends += [u, v]
    return n, sorted(set(edges))


def lattice(family: str, n: int) -> tuple[int, list[tuple[int, int]]] | None:
    found = known_answers.edges(family, n)
    return (n, found) if found is not None else None


FAMILIES = {
    "rgg_2d": {"kind": "dimensional", "d": 2.0, "build": lambda n, s: random_geometric(n, 2, 8.0, s)},
    "rgg_3d": {"kind": "dimensional", "d": 3.0, "build": lambda n, s: random_geometric(n, 3, 10.0, s)},
    "rgg_4d": {"kind": "dimensional", "d": 4.0, "build": lambda n, s: random_geometric(n, 4, 12.0, s)},
    "sierpinski": {"kind": "dimensional", "d": math.log(3) / math.log(2),
                   "build": lambda n, s: sierpinski_gasket(max(1, round(math.log((2 * n / 3) - 1, 3))))},
    "percolation_2d": {"kind": "dimensional", "d": 91 / 48,
                       "build": lambda n, s: critical_percolation_cluster(int(round(1.6 * n ** (48 / 91))), s)},
    "random_tree": {"kind": "dimensional", "d": 2.0, "build": lambda n, s: random_tree(n, s)},
    "ring": {"kind": "dimensional", "d": 1.0, "build": lambda n, s: ring(n)},
    "cubic": {"kind": "dimensional", "d": 3.0, "build": lambda n, s: lattice(known_answers.CUBIC_QUOTIENT, n)},
    "tesseract": {"kind": "dimensional", "d": 4.0, "build": lambda n, s: lattice(known_answers.TESSERACT_QUOTIENT, n)},
    "honeycomb": {"kind": "dimensional", "d": 2.0, "build": lambda n, s: lattice(known_answers.HONEYCOMB_TORUS, n)},
    "erdos_renyi_4": {"kind": "none", "build": lambda n, s: erdos_renyi(n, 4.0, s)},
    "random_regular_6": {"kind": "none", "build": lambda n, s: random_regular(n, 6, s)},
    "ring_with_chords": {"kind": "none", "build": lambda n, s: ring_with_chords(n, 0.02, s)},
    "subdivided_regular": {"kind": "none", "build": lambda n, s: subdivided_regular(n, 4, s)},
    "preferential_attachment": {"kind": "none", "build": lambda n, s: preferential_attachment(n, 2, s)},
}
