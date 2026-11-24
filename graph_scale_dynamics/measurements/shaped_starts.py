from __future__ import annotations

import re

PREFIX = "random_geometric_"
_NAME = re.compile(r"^random_geometric_(\d+)d_degree_(\d+)$")
MIN_NODES = 16
FIRST_NEIGHBOURS, WIDE_NEIGHBOURS = 4, 12


def family(dimension: int, degree: int) -> str:
    if int(dimension) < 1 or int(degree) < 1:
        raise ValueError("a shaped start needs a dimension and a degree of at least 1")
    return f"{PREFIX}{int(dimension)}d_degree_{int(degree)}"


def parse(name: str) -> tuple[int, int] | None:
    match = _NAME.match(str(name))
    if not match:
        return None
    dimension, degree = int(match.group(1)), int(match.group(2))
    return (dimension, degree) if dimension >= 1 and degree >= 1 else None


def reaches(name: str, n: int) -> bool:
    parsed = parse(name)
    return parsed is not None and int(n) >= max(MIN_NODES, parsed[1] + 2)


def build(n: int, dimension: int, degree: int, seed: int) -> list[tuple[int, int]]:
    import numpy as np
    from scipy.spatial import cKDTree

    n, dimension, degree, seed = int(n), int(dimension), int(degree), int(seed)
    points = np.random.default_rng(seed).random((n, dimension))
    tree = cKDTree(points, boxsize=1.0)
    adj: list[set] = [set() for _ in range(n)]

    def join(a: int, b: int) -> None:
        if a != b and len(adj[a]) < degree and len(adj[b]) < degree and b not in adj[a] and not adj[a] & adj[b]:
            adj[a].add(b)
            adj[b].add(a)
    dist, idx = tree.query(points, k=min(n, FIRST_NEIGHBOURS * degree + 1))
    rows = np.repeat(np.arange(n), idx.shape[1] - 1)
    others = idx[:, 1:].reshape(-1)
    lengths = dist[:, 1:].reshape(-1)
    keep = rows < others
    rows, others, lengths = rows[keep], others[keep], lengths[keep]
    order = np.lexsort((others, rows, lengths))
    for a, b in zip(rows[order].tolist(), others[order].tolist()):
        join(a, b)
    short = [a for a in range(n) if len(adj[a]) < degree]
    if short:
        _, wide = tree.query(points[short], k=min(n, WIDE_NEIGHBOURS * degree))
        for a, row in zip(short, wide.tolist()):
            for b in row[1:]:
                if len(adj[a]) >= degree:
                    break
                join(a, int(b))
    return sorted((a, b) for a in range(n) for b in adj[a] if a < b)
