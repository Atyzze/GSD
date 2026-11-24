from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from math import comb

from graph_scale_dynamics.dsl.dsl import SCALES

RUNAWAY_VERSION = "runaway-energy-1"
STAR, CLIQUE, REGULAR = "star", "clique", "regular"
SHAPES = (STAR, CLIQUE, REGULAR)
MAX_POWER = 6
CANCELLED = 1e-12
DEFAULT_LADDER = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)


def _k(params: dict | None) -> int:
    return int((params or {}).get("k", 0))


def _curvature_on_clique(m: int) -> int:
    from graph_scale_dynamics.engine.engine import scaled_curvature
    if m < 2:
        return 0
    t, s, p = m - 2, (m - 2) * (m - 3), (m - 2) * (m - 3) * max(0, m - 4)
    return comb(m, 2) * scaled_curvature(t, s, p, m - 1, m - 1)


def _curvature_on_star(d: int) -> int:
    from graph_scale_dynamics.engine.engine import scaled_curvature
    return d * scaled_curvature(0, 0, 0, d, 1) if d >= 1 else 0


def star_energy(op: str, params: dict | None, d: int) -> int:
    k = _k(params)
    if op == "edge_count":
        return d
    if op == "degree_square_sum":
        return d * d + d
    if op == "wedge_count":
        return comb(d, 2)
    if op in ("triangle_count", "triangle_edge_overlap", "square_count", "square_edge_overlap",
              "induced_square_count"):
        return 0
    if op == "degree_neighbor_gradient":
        return d * (d - 1) ** 2
    if op == "degree_anchor":
        return (d - k) ** 2 - k * k + d * ((1 - k) ** 2 - k * k)
    if op == "degree_anchor_abs":
        return abs(d - k) - abs(k) + d * (abs(1 - k) - abs(k))
    if op == "degree_cube_sum":
        return d ** 3 + d
    if op == "degree_fourth_sum":
        return d ** 4 + d
    if op == "ollivier_curvature":
        return _curvature_on_star(d)
    raise KeyError(f"no closed form on the star for {op!r}")


def clique_energy(op: str, params: dict | None, m: int) -> int:
    k = _k(params)
    if op == "edge_count":
        return comb(m, 2)
    if op == "degree_square_sum":
        return m * (m - 1) ** 2
    if op == "wedge_count":
        return m * comb(m - 1, 2)
    if op == "triangle_count":
        return comb(m, 3)
    if op == "triangle_edge_overlap":
        return comb(m, 2) * comb(max(0, m - 2), 2)
    if op == "square_count":
        return 3 * comb(m, 4)
    if op == "square_edge_overlap":
        return comb(m, 2) * comb(max(0, (m - 2) * (m - 3)), 2)
    if op in ("induced_square_count", "degree_neighbor_gradient"):
        return 0
    if op == "degree_anchor":
        return m * ((m - 1 - k) ** 2 - k * k)
    if op == "degree_anchor_abs":
        return m * (abs(m - 1 - k) - abs(k))
    if op == "degree_cube_sum":
        return m * (m - 1) ** 3
    if op == "degree_fourth_sum":
        return m * (m - 1) ** 4
    if op == "ollivier_curvature":
        return _curvature_on_clique(m)
    raise KeyError(f"no closed form on the clique for {op!r}")


def regular_energy(op: str, params: dict | None, d: int) -> Fraction:
    k = _k(params)
    if op == "edge_count":
        return Fraction(d, 2)
    if op == "degree_square_sum":
        return Fraction(d * d)
    if op == "wedge_count":
        return Fraction(comb(d, 2))
    if op in ("triangle_count", "triangle_edge_overlap", "square_count", "square_edge_overlap",
              "induced_square_count", "degree_neighbor_gradient"):
        return Fraction(0)
    if op == "degree_anchor":
        return Fraction((d - k) ** 2 - k * k)
    if op == "degree_anchor_abs":
        return Fraction(abs(d - k) - abs(k))
    if op == "degree_cube_sum":
        return Fraction(d ** 3)
    if op == "degree_fourth_sum":
        return Fraction(d ** 4)
    if op == "ollivier_curvature":
        from graph_scale_dynamics.engine.engine import scaled_curvature
        return Fraction(d * scaled_curvature(0, 0, 0, d, d), 2)
    raise KeyError(f"no closed form on the regular graph for {op!r}")


def energy(shape: str, op: str, params: dict | None, size: int):
    return {STAR: star_energy, CLIQUE: clique_energy, REGULAR: regular_energy}[shape](op, params, int(size))


@lru_cache(maxsize=None)
def _polynomial(shape: str, op: str, k: int) -> tuple[Fraction, ...]:
    params = {"k": k} if k else {}
    start = max(abs(k) + 2, 6)
    values = [Fraction(energy(shape, op, params, start + i)) for i in range(MAX_POWER + 2)]
    table = [values]
    while len(table[-1]) > 1:
        row = table[-1]
        table.append([row[i + 1] - row[i] for i in range(len(row) - 1)])
    if table[MAX_POWER + 1][0] != 0:
        raise ValueError(f"{op} on the {shape} is not a polynomial of degree {MAX_POWER} or less past {start}")
    coefficients = [Fraction(0)] * (MAX_POWER + 1)
    for j in range(MAX_POWER + 1):
        delta = table[j][0]
        if delta == 0:
            continue
        falling = [Fraction(1)]
        for i in range(j):
            root = start + i
            falling = [Fraction(0)] + falling
            for power in range(len(falling) - 1):
                falling[power] -= root * falling[power + 1]
        scale = delta / Fraction(_factorial(j))
        for power, value in enumerate(falling):
            coefficients[power] += scale * value
    return tuple(coefficients)


def _factorial(j: int) -> int:
    out = 1
    for i in range(2, j + 1):
        out *= i
    return out


def polynomial(shape: str, op: str, params: dict | None = None) -> tuple[Fraction, ...]:
    return _polynomial(shape, op, _k(params))


@lru_cache(maxsize=None)
def _float_polynomial(shape: str, op: str, k: int) -> tuple[float, ...]:
    return tuple(float(value) for value in _polynomial(shape, op, k))


def _multiplier(coeff: dict, n: int) -> float:
    scale = str(coeff.get("scale") or "one")
    if scale == "power":
        return float(max(1, n)) ** float(coeff.get("p") or 0.0)
    return float(SCALES[scale](n))


def _leading(polynomials: list[tuple[float, ...]], weights: list[float]) -> tuple[int, float]:
    for power in range(MAX_POWER, 0, -1):
        total = size = 0.0
        for poly, weight in zip(polynomials, weights, strict=True):
            value = poly[power]
            if value and weight:
                contribution = weight * value
                total += contribution
                size = max(size, abs(contribution))
        if size and abs(total) > CANCELLED * size:
            return power, total
    return 0, 0.0


def leading(terms: list[dict], n: int, shape: str) -> tuple[int, float]:
    polynomials = [_float_polynomial(shape, str(term["op"]), _k(term.get("params"))) for term in terms]
    weights = [float((term.get("coeff") or {}).get("c0") or 0.0) * _multiplier(term.get("coeff") or {}, n)
               for term in terms]
    return _leading(polynomials, weights)


def runaway(terms: list[dict], ladder=DEFAULT_LADDER) -> dict | None:
    polynomials = {shape: [_float_polynomial(shape, str(term["op"]), _k(term.get("params"))) for term in terms]
                   for shape in SHAPES}
    coefficients = [(float((term.get("coeff") or {}).get("c0") or 0.0), term.get("coeff") or {}) for term in terms]
    for n in ladder:
        weights = [c0 * _multiplier(coeff, int(n)) for c0, coeff in coefficients]
        for shape in SHAPES:
            power, value = _leading(polynomials[shape], weights)
            if value < 0:
                return {"shape": shape, "n": int(n), "power": power, "coefficient": value}
    return None
