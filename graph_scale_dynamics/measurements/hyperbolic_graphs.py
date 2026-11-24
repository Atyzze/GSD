from __future__ import annotations

import math

import numpy as np


def _tiling_grown_outward(layers: int, at_the_centre: int, own_children, joined_in_a_layer: bool):
    ring, parents = list(range(1, at_the_centre + 1)), [1] * at_the_centre
    edges = [(0, v) for v in ring]
    n = at_the_centre + 1
    for layer in range(1, layers + 1):
        if joined_in_a_layer:
            edges += [(min(v, w), max(v, w)) for v, w in zip(ring, ring[1:] + ring[:1], strict=True)]
        if layer == layers:
            break
        grown, grown_parents = [], []
        for v, held in zip(ring, parents, strict=True):
            own = list(range(n, n + own_children(held)))
            shared = n + len(own)
            n = shared + 1
            edges += [(v, child) for child in own] + [(v, shared)]
            grown += own + [shared]
            grown_parents += [1] * len(own) + [2]
        edges += [(v, shared) for v, shared in zip(ring, [grown[-1]] + [
            child for child, held in zip(grown, grown_parents, strict=True) if held == 2][:-1], strict=True)]
        ring, parents = grown, grown_parents
    return n, sorted(set(edges))


def hyperbolic_triangles(layers: int, at_a_node: int = 7) -> tuple[int, list[tuple[int, int]]]:
    if at_a_node < 7:
        raise ValueError("fewer than seven triangles at a node close up or lie flat")
    return _tiling_grown_outward(layers, at_a_node, lambda held: at_a_node - 4 - held, True)


def hyperbolic_squares(layers: int, at_a_node: int = 5) -> tuple[int, list[tuple[int, int]]]:
    if at_a_node < 5:
        raise ValueError("fewer than five squares at a node close up or lie flat")
    return _tiling_grown_outward(layers, at_a_node, lambda held: at_a_node - 2 - held, False)


def hyperbolic_points(n: int, disc: float, alpha: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    angle = rng.random(n) * 2.0 * math.pi
    out = np.arccosh(1.0 + (math.cosh(alpha * disc) - 1.0) * rng.random(n)) / alpha
    return out, angle


def hyperbolically_within(out_a, angle_a, out_b, angle_b, within: float) -> np.ndarray:
    apart = math.pi - np.abs(math.pi - np.abs(angle_a - angle_b) % (2.0 * math.pi))
    return (np.cosh(out_a) * np.cosh(out_b) - np.sinh(out_a) * np.sinh(out_b) * np.cos(apart)) <= math.cosh(within)


def _widest_angle(out: np.ndarray, floor: float, ceiling: float, within: float) -> np.ndarray:
    widest_at = np.arccosh(np.maximum(1.0, np.cosh(out) / math.cosh(within)))
    other = np.clip(widest_at, floor, np.minimum(ceiling, out))
    below = np.sinh(out) * np.sinh(other)
    above = np.cosh(out) * np.cosh(other) - math.cosh(within)
    quotient = np.divide(above, below, out=np.zeros_like(above), where=below > 0.0)
    cosine = np.where(below > 0.0, quotient, np.where(above <= 0.0, -1.0, 2.0))
    return np.where(cosine > 1.0, -1.0, np.arccos(np.clip(cosine, -1.0, 1.0)))


def joined_within(out: np.ndarray, angle: np.ndarray, within: float, bands: int | None = None) -> tuple:
    n = len(out)
    bands = bands or max(4, 2 * math.ceil(math.log2(max(2, n))))
    disc = float(out.max()) if n else 0.0
    floors = np.concatenate([[0.0], np.linspace(disc / 2.0, disc, bands)[:-1]])
    ceilings = np.concatenate([floors[1:], [math.inf]])
    band = np.searchsorted(floors, out, side="right") - 1
    order = np.arange(n)
    found_a, found_b = [], []
    for b in range(len(floors)):
        inside = order[band == b]
        if len(inside) == 0:
            continue
        inside = inside[np.argsort(angle[inside], kind="stable")]
        turned = np.concatenate([angle[inside] - 2.0 * math.pi, angle[inside], angle[inside] + 2.0 * math.pi])
        outer = order[band >= b]
        reach = _widest_angle(out[outer], float(floors[b]), float(ceilings[b]), within)
        first = np.searchsorted(turned, angle[outer] - reach, side="left")
        last = np.searchsorted(turned, angle[outer] + reach, side="right")
        count = np.where(reach < 0.0, 0, np.minimum(np.maximum(last - first, 0), len(inside)))
        for begin in range(0, len(outer), 4096):
            some = slice(begin, begin + 4096)
            total = int(count[some].sum())
            if total == 0:
                continue
            a = np.repeat(outer[some], count[some])
            offset = np.arange(total) - np.repeat(np.cumsum(count[some]) - count[some], count[some])
            other = inside[(np.repeat(first[some], count[some]) + offset) % len(inside)]
            keep = (out[other] < out[a]) | ((out[other] == out[a]) & (other < a))
            a, other = a[keep], other[keep]
            near = hyperbolically_within(out[a], angle[a], out[other], angle[other], within)
            found_a.append(a[near])
            found_b.append(other[near])
    if not found_a:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(found_a), np.concatenate(found_b)


def unique_pairs(n: int, a, b) -> list[tuple[int, int]]:
    a, b = np.asarray(a, dtype=np.int64), np.asarray(b, dtype=np.int64)
    keep = a != b
    lo, hi = np.minimum(a[keep], b[keep]), np.maximum(a[keep], b[keep])
    code = np.unique(lo * n + hi)
    return [(int(c // n), int(c % n)) for c in code]


def hyperbolic_geometric_points_joined(n: int, mean_degree: float, within: float,
                                       seed: int) -> tuple[int, list[tuple[int, int]]]:
    disc = math.acosh(1.0 + n * (math.cosh(within) - 1.0) / mean_degree)
    out, angle = hyperbolic_points(n, disc, 1.0, seed)
    return int(n), unique_pairs(n, *joined_within(out, angle, within))
