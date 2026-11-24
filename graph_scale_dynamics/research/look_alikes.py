from __future__ import annotations

import numpy as np

from graph_scale_dynamics.measurements import known_answers
from graph_scale_dynamics.research import planted_geometries as planted

LOOK_ALIKES_CONTRACT = "gsd-look-alikes-1"

Built = tuple[int, list[tuple[int, int]]]


def side_of(n: float, dimension: int) -> int:
    return max(3, int(round(n ** (1.0 / dimension))))


def crossover_length(per_node: float, dimension: float) -> float:
    return per_node ** (-1.0 / dimension)


def torus(n: float, dimension: int) -> Built:
    side = side_of(n, dimension)
    total = side ** dimension
    index = np.arange(total).reshape((side,) * dimension)
    ends = [np.roll(index, -1, axis=axis).ravel() for axis in range(dimension)]
    return total, planted._pairs(total, np.concatenate([index.ravel()] * dimension), np.concatenate(ends))


def triangular_torus(n: float) -> Built:
    side = side_of(n, 2)
    total = side * side
    index = np.arange(total).reshape(side, side)
    ends = [np.roll(index, -1, axis=0), np.roll(index, -1, axis=1),
            np.roll(np.roll(index, -1, axis=0), -1, axis=1)]
    return total, planted._pairs(total, np.concatenate([index.ravel()] * 3),
                                 np.concatenate([end.ravel() for end in ends]))


def _joined(n: int, edges: list[tuple[int, int]], a, b) -> Built:
    return n, sorted({(min(u, v), max(u, v)) for u, v in edges} | set(planted._pairs(n, a, b)))


def with_shortcuts(built: Built | None, per_node: float, seed: int) -> Built | None:
    if built is None:
        return None
    n, edges = built
    rng = np.random.default_rng(seed)
    count = max(1, int(round(per_node * n)))
    return _joined(n, edges, rng.integers(0, n, size=count), rng.integers(0, n, size=count))


def square_with_local_chords(n: float, per_node: float, within: int, seed: int) -> Built:
    side = side_of(n, 2)
    total, edges = torus(n, 2)
    rng = np.random.default_rng(seed)
    count = max(1, int(round(per_node * total)))
    start = rng.integers(0, total, size=count)
    dx, dy = rng.integers(-within, within + 1, size=count), rng.integers(-within, within + 1, size=count)
    end = ((start // side + dx) % side) * side + (start % side + dy) % side
    return _joined(total, edges, start, end)


def diluted_square(n: float, kept: float, seed: int) -> Built:
    total, edges = torus(n / kept, 2)
    alive = np.random.default_rng(seed).random(total) < kept
    return planted._largest(total, [(a, b) for a, b in edges if alive[a] and alive[b]])


def _honeycomb(n: int) -> Built | None:
    return planted.lattice(known_answers.HONEYCOMB_TORUS, n)


def _sierpinski(n: int) -> Built:
    return planted.FAMILIES["sierpinski"]["build"](n, 0)


FAMILIES = {
    "triangular": lambda n, s: triangular_torus(n),
    "square_diluted": lambda n, s: diluted_square(n, 0.8, s),
    "square_local_chords": lambda n, s: square_with_local_chords(n, 0.05, 3, s),
    "rgg_3d_sparse": lambda n, s: planted.random_geometric(n, 3, 7.0, s),
    "percolation_2d_again": planted.FAMILIES["percolation_2d"]["build"],
    "square_shortcuts_p003": lambda n, s: with_shortcuts(torus(n, 2), 0.003, s),
    "square_shortcuts_p008": lambda n, s: with_shortcuts(torus(n, 2), 0.008, s),
    "honeycomb_shortcuts_p008": lambda n, s: with_shortcuts(_honeycomb(n), 0.008, s),
    "rgg_2d_shortcuts_p010": lambda n, s: with_shortcuts(planted.random_geometric(n, 2, 8.0, s), 0.010, s + 1000),
    "cubic_shortcuts_p020": lambda n, s: with_shortcuts(torus(n, 3), 0.020, s),
    "sierpinski_shortcuts_p005": lambda n, s: with_shortcuts(_sierpinski(n), 0.005, s),
    "preferential_attachment_4": lambda n, s: planted.preferential_attachment(n, 4, s),
    "square_shortcuts_p0005": lambda n, s: with_shortcuts(torus(n, 2), 0.0005, s),
    "square_shortcuts_p001": lambda n, s: with_shortcuts(torus(n, 2), 0.001, s),
    "square_shortcuts_p002": lambda n, s: with_shortcuts(torus(n, 2), 0.002, s),
    "square_shortcuts_p004": lambda n, s: with_shortcuts(torus(n, 2), 0.004, s),
    "honeycomb_shortcuts_p005": lambda n, s: with_shortcuts(_honeycomb(n), 0.005, s),
    "cubic_shortcuts_p002": lambda n, s: with_shortcuts(torus(n, 3), 0.002, s),
    "cubic_shortcuts_p010": lambda n, s: with_shortcuts(torus(n, 3), 0.010, s),
}

RANDOM = {
    "random_regular_4": lambda n, s: planted.random_regular(n, 4, s),
    "random_regular_5": lambda n, s: planted.random_regular(n, 5, s),
    "random_regular_6_deep": lambda n, s: planted.random_regular(n, 6, s),
    "random_regular_8": lambda n, s: planted.random_regular(n, 8, s),
    "erdos_renyi_5": lambda n, s: planted.erdos_renyi(n, 5.0, s),
    "erdos_renyi_6": lambda n, s: planted.erdos_renyi(n, 6.0, s),
    "erdos_renyi_8_deep": lambda n, s: planted.erdos_renyi(n, 8.0, s),
}
