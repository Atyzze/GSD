from __future__ import annotations

import math

import numpy as np

CUBIC_QUOTIENT = "periodic_cubic_quotient"
SQUARE_TORUS = "periodic_square_lattice"
TESSERACT_QUOTIENT = "periodic_tesseract_quotient"
HONEYCOMB_TORUS = "periodic_honeycomb_lattice"
TRIANGULAR_TORUS = "periodic_triangular_lattice"
BODY_CENTRED_CUBIC = "periodic_body_centred_cubic_lattice"
FACE_CENTRED_CUBIC = "periodic_face_centred_cubic_lattice"
SMALLEST_SIDE = 4


def _fold(n: int) -> tuple[int, int] | None:
    for index in (1, 2, 4):
        if n % index:
            continue
        m = round((n // index) ** (1.0 / 3.0))
        for candidate in (m - 1, m, m + 1):
            if candidate >= 3 and candidate ** 3 * index == n:
                return candidate, index
    return None


def _fold4(n: int) -> tuple[int, int] | None:
    for index, smallest in ((1, 3), (4, 2)):
        if n % index:
            continue
        m = round((n // index) ** 0.25)
        for candidate in (m - 1, m, m + 1):
            if candidate >= smallest and candidate ** 4 * index == n:
                return candidate, index
    return None


def _square_side(n: int) -> int | None:
    side = math.isqrt(int(n))
    return side if side >= 3 and side * side == int(n) else None


def _honeycomb_side(n: int) -> int | None:
    side = _square_side(n)
    return side if side is not None and side >= 4 and side % 2 == 0 else None


def _box(cells: int) -> tuple[int, int, int] | None:
    cells = int(cells)
    if cells < 1 or cells & (cells - 1):
        return None
    power = cells.bit_length() - 1
    sides = tuple(1 << (power // 3 + (1 if axis < power % 3 else 0)) for axis in range(3))
    return sides if min(sides) >= SMALLEST_SIDE else None


BODY_CENTRED = "body_centred"
FACE_CENTRED = "face_centred"
CELLS_A_NODE = {BODY_CENTRED: 4, FACE_CENTRED: 2}
STEPS = {BODY_CENTRED: ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1)),
         FACE_CENTRED: ((1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1), (0, 1, 1), (0, 1, -1))}
MODULUS_INSIDE = {(BODY_CENTRED, 1): 2, (BODY_CENTRED, 2): 2, (BODY_CENTRED, 4): 1,
                  (FACE_CENTRED, 1): 2, (FACE_CENTRED, 2): 1, (FACE_CENTRED, 4): 2}


def cubic_fold(lattice: str, n: int) -> tuple[int, int] | None:
    for index in (1, 2, 4):
        cube, left = divmod(int(n) * CELLS_A_NODE[lattice], index)
        if left:
            continue
        m = round(cube ** (1.0 / 3.0))
        for candidate in (m - 1, m, m + 1):
            if (candidate >= SMALLEST_SIDE and candidate ** 3 == cube
                    and candidate % MODULUS_INSIDE[(lattice, index)] == 0):
                return candidate, index
    return None


def reaches(family: str, n: int) -> bool:
    if family == CUBIC_QUOTIENT:
        return _fold(int(n)) is not None
    if family == SQUARE_TORUS:
        return _square_side(int(n)) is not None
    if family == TESSERACT_QUOTIENT:
        return _fold4(int(n)) is not None
    if family == HONEYCOMB_TORUS:
        return _honeycomb_side(int(n)) is not None
    if family == TRIANGULAR_TORUS:
        return _square_side(int(n)) is not None
    if family == BODY_CENTRED_CUBIC:
        return cubic_fold(BODY_CENTRED, n) is not None
    if family == FACE_CENTRED_CUBIC:
        return cubic_fold(FACE_CENTRED, n) is not None
    return False


_BUILDERS = {}


def edges(family: str, n: int) -> list[tuple[int, int]] | None:
    if not reaches(family, n):
        return None
    built = _BUILDERS[family](n)
    return built[1] if built is not None else None


def _unique_pairs(n: int, a: np.ndarray, b: np.ndarray) -> list[tuple[int, int]]:
    low, high = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
    keep = low != high
    keys = np.unique(low[keep] * int(n) + high[keep])
    return list(zip((keys // int(n)).tolist(), (keys % int(n)).tolist(), strict=True))


def periodic_square_torus(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    side = _square_side(int(n))
    if side is None:
        return None
    index = np.arange(int(n), dtype=np.int64)
    x, y = index % side, index // side
    right = y * side + (x + 1) % side
    down = ((y + 1) % side) * side + x
    return int(n), _unique_pairs(int(n), np.concatenate([index, index]), np.concatenate([right, down]))


def _coset(q: np.ndarray, index: int) -> np.ndarray:
    if index == 1:
        return np.zeros(len(q), dtype=np.int64)
    if index == 2:
        return q.sum(axis=1) % 2
    return ((q[:, 0] - q[:, 2]) % 2) * 2 + ((q[:, 1] - q[:, 2]) % 2)


_REPRESENTATIVES = {1: np.array([[0, 0, 0]]),
                    2: np.array([[0, 0, 0], [1, 0, 0]]),
                    4: np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0]])}


def periodic_cubic_quotient(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    fold = _fold(int(n))
    if fold is None:
        return None
    m, index = fold
    residues = np.stack(np.meshgrid(np.arange(m), np.arange(m), np.arange(m), indexing="ij"), axis=-1).reshape(-1, 3)
    points = (residues[None, :, :] + m * _REPRESENTATIVES[index][:, None, :]).reshape(-1, 3)
    assert _coset(np.floor_divide(points, m), index).tolist() == np.repeat(np.arange(index), m ** 3).tolist()

    def node(p: np.ndarray) -> np.ndarray:
        q = np.floor_divide(p, m)
        x = p - m * q
        return _coset(q, index) * m ** 3 + (x[:, 0] * m + x[:, 1]) * m + x[:, 2]

    here = node(points)
    ends = []
    for axis in range(3):
        step = np.zeros(3, dtype=np.int64)
        step[axis] = 1
        ends.append(node(points + step))
    return int(n), _unique_pairs(int(n), np.concatenate([here, here, here]), np.concatenate(ends))


def periodic_tesseract_quotient(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    fold = _fold4(int(n))
    if fold is None:
        return None
    m, index = fold
    label = np.arange(int(n), dtype=np.int64)
    coset, rest = label // m ** 4, label % m ** 4
    residues = [(rest // m ** (3 - axis)) % m for axis in range(4)]
    ends = []
    for axis in range(4):
        moved = residues[axis] + 1
        wraps = moved == m
        stepped = [moved % m if other == axis else residues[other] for other in range(4)]
        to = ((coset + wraps) % index) * m ** 4
        for other in range(4):
            to = to + stepped[other] * m ** (3 - other)
        ends.append(to)
    return int(n), _unique_pairs(int(n), np.concatenate([label] * 4), np.concatenate(ends))


def periodic_honeycomb_torus(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    side = _honeycomb_side(int(n))
    if side is None:
        return None
    label = np.arange(int(n), dtype=np.int64)
    x, y = label // side, label % side
    along = x * side + (y + 1) % side
    even = (x + y) % 2 == 0
    across = ((x[even] + 1) % side) * side + y[even]
    return int(n), _unique_pairs(int(n), np.concatenate([label, label[even]]), np.concatenate([along, across]))


def periodic_triangular_torus(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    side = _square_side(int(n))
    if side is None:
        return None
    label = np.arange(int(n), dtype=np.int64)
    x, y = label // side, label % side
    ends = [((x + dx) % side) * side + (y + dy) % side for dx, dy in ((1, 0), (0, 1), (1, -1))]
    return int(n), _unique_pairs(int(n), np.concatenate([label] * 3), np.concatenate(ends))


def _inside(lattice: str, points: np.ndarray) -> np.ndarray:
    if lattice == BODY_CENTRED:
        return (points[:, 0] % 2 == points[:, 1] % 2) & (points[:, 1] % 2 == points[:, 2] % 2)
    return points.sum(axis=1) % 2 == 0


def cubic_torus_points(lattice: str, n: int):
    fold = cubic_fold(lattice, n)
    if fold is None:
        return None
    m, index = fold
    residues = np.stack(np.meshgrid(np.arange(m), np.arange(m), np.arange(m), indexing="ij"), axis=-1).reshape(-1, 3)
    every = (residues[None, :, :] + m * _REPRESENTATIVES[index][:, None, :]).reshape(-1, 3)

    def cell(p: np.ndarray) -> np.ndarray:
        q = np.floor_divide(p, m)
        x = p - m * q
        return _coset(q, index) * m ** 3 + (x[:, 0] * m + x[:, 1]) * m + x[:, 2]

    points = every[_inside(lattice, every)]
    assert len(points) == int(n)
    label = np.full(index * m ** 3, -1, dtype=np.int64)
    label[cell(points)] = np.arange(int(n), dtype=np.int64)
    return points, lambda p: label[cell(np.asarray(p, dtype=np.int64))]


def _cubic_torus_of(lattice: str, n: int) -> tuple[int, list[tuple[int, int]]] | None:
    found = cubic_torus_points(lattice, n)
    if found is None:
        return None
    points, node_of = found
    here = np.arange(int(n), dtype=np.int64)
    ends = [node_of(points + np.asarray(step, dtype=np.int64)) for step in STEPS[lattice]]
    assert all((end >= 0).all() for end in ends)
    return int(n), _unique_pairs(int(n), np.concatenate([here] * len(ends)), np.concatenate(ends))


def periodic_body_centred_cubic(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    return _cubic_torus_of(BODY_CENTRED, n)


def periodic_face_centred_cubic(n: int) -> tuple[int, list[tuple[int, int]]] | None:
    return _cubic_torus_of(FACE_CENTRED, n)


_BUILDERS.update({CUBIC_QUOTIENT: periodic_cubic_quotient, SQUARE_TORUS: periodic_square_torus,
                  TESSERACT_QUOTIENT: periodic_tesseract_quotient, HONEYCOMB_TORUS: periodic_honeycomb_torus,
                  TRIANGULAR_TORUS: periodic_triangular_torus, BODY_CENTRED_CUBIC: periodic_body_centred_cubic,
                  FACE_CENTRED_CUBIC: periodic_face_centred_cubic})
