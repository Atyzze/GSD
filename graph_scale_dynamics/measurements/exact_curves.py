from __future__ import annotations

import math

import numpy as np

LARGEST = 3000


def _adjacency(n: int, edges) -> np.ndarray:
    if int(n) > LARGEST:
        raise ValueError(f"an exact curve is computed on at most {LARGEST} nodes")
    matrix = np.zeros((int(n), int(n)), dtype=float)
    for u, v in edges:
        matrix[int(u), int(v)] = matrix[int(v), int(u)] = 1.0
    return matrix


def distances(n: int, edges) -> np.ndarray:
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import shortest_path
    found = shortest_path(csr_matrix(_adjacency(n, edges)), unweighted=True)
    if not np.isfinite(found).all():
        raise ValueError("an exact curve is computed on a graph in one piece")
    return found


def return_probability(n: int, edges, t_max: int) -> np.ndarray:
    matrix = _adjacency(n, edges)
    degree = matrix.sum(axis=1)
    walk = np.linalg.eigvalsh(matrix / np.sqrt(np.outer(degree, degree)))
    lazy = 0.5 * (1.0 + walk)
    return np.array([float(np.mean(lazy ** t)) for t in range(1, int(t_max) + 1)])


def balls(n: int, edges) -> np.ndarray:
    found = distances(n, edges).astype(int)
    furthest = int(found.max())
    return np.stack([(found <= radius).sum(axis=1) for radius in range(furthest + 1)], axis=1).astype(float)


def mean_ball(n: int, edges) -> np.ndarray:
    return balls(n, edges).mean(axis=0)


def half_volume_radius(n: int, edges) -> float:
    every = balls(n, edges)
    target = int(math.ceil(0.5 * int(n)))
    return float(np.mean([int(np.searchsorted(row, target)) for row in every]))


def equilibrium_mean_square_distance(n: int, edges) -> float:
    degree = _adjacency(n, edges).sum(axis=1)
    squared = distances(n, edges) ** 2
    return float(np.mean(squared @ degree / degree.sum()))


def mean_square_distance(n: int, edges, times) -> np.ndarray:
    matrix = _adjacency(n, edges)
    step = matrix / matrix.sum(axis=1)[:, None]
    squared = distances(n, edges) ** 2
    wanted = sorted(int(t) for t in times)
    state = np.eye(int(n))
    out = {}
    for t in range(1, wanted[-1] + 1):
        state = state @ step
        if t in wanted:
            out[t] = float(np.mean(np.sum(state * squared, axis=1)))
    return np.array([out[int(t)] for t in times])


def is_a_cover(n: int, edges, centres, radius: int) -> bool:
    found = distances(n, edges)
    return bool((found[np.asarray(list(centres), dtype=int)].min(axis=0) <= radius).all())
