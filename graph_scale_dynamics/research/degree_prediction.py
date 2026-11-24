from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.dsl.dsl import coefficient, dynamics_regime

NODE_ENERGY = {
    "degree_anchor": lambda d, k: (d - k) ** 2,
    "degree_anchor_abs": lambda d, k: np.abs(d - k),
    "degree_cube_sum": lambda d, k: d ** 3,
    "degree_fourth_sum": lambda d, k: d ** 4,
    "degree_square_sum": lambda d, k: d * d,
    "edge_count": lambda d, k: d / 2.0,
    "wedge_count": lambda d, k: d * (d - 1) / 2.0,
}
DEGREE_OPS = frozenset(NODE_ENERGY)
CYCLE_OPS = frozenset({"triangle_count", "triangle_edge_overlap", "square_count", "induced_square_count",
                       "square_edge_overlap"})

KIND_DEGREES = "degree sequence only"
KIND_CORRELATIONS = "degree correlations"
KIND_CYCLES = "sees cycles"

ZERO_T_METHOD = "zero temperature: every node at the degree that minimises its energy"
GIBBS_METHOD = "finite temperature: the Gibbs measure's saddle point"
_GRID_STEP = 0.01


def law_kind(spec: dict) -> str:
    ops = {term.get("op") for term in (spec or {}).get("terms") or []}
    if ops & CYCLE_OPS:
        return KIND_CYCLES
    if ops <= DEGREE_OPS:
        return KIND_DEGREES
    return KIND_CORRELATIONS


def node_energy(spec: dict, degrees, n: int) -> np.ndarray:
    d = np.asarray(degrees, dtype=float)
    total = np.zeros_like(d)
    for term in spec.get("terms") or []:
        functional = NODE_ENERGY[term["op"]]
        k = (term.get("params") or {}).get("k", 0)
        total = total + coefficient(term, int(n)) * functional(d, float(k))
    return total


def gibbs_mean_degree(spec: dict, n: int, cap: float, beta: float) -> float:
    from scipy.special import gammaln, logsumexp
    degrees = np.arange(0, int(math.ceil(float(cap))) + 2, dtype=float)
    log_weights = -float(beta) * node_energy(spec, degrees, n) - gammaln(degrees + 1.0)

    def free(m) -> np.ndarray:
        m = np.atleast_1d(np.asarray(m, dtype=float))
        log_y = 0.5 * np.log(float(n) * m)
        return logsumexp(log_weights[None, :] + log_y[:, None] * degrees[None, :], axis=1) - m / 2.0

    grid = np.arange(_GRID_STEP, float(cap) + _GRID_STEP / 2, _GRID_STEP)
    best = float(grid[int(np.argmax(free(grid)))])
    lo, hi = max(1e-6, best - _GRID_STEP), min(float(cap), best + _GRID_STEP)
    for _ in range(40):
        a = hi - (hi - lo) / 1.618033988749895
        b = lo + (hi - lo) / 1.618033988749895
        if free(a)[0] > free(b)[0]:
            hi = b
        else:
            lo = a
    return round((lo + hi) / 2.0, 4)


def predicted_mean_degree(spec: dict, n: int, cap: float) -> dict | None:
    if law_kind(spec) != KIND_DEGREES:
        return None
    cap = float(cap)
    if dynamics_regime(spec) == "zero_temperature":
        degrees = np.arange(0, int(math.floor(cap)) + 1, dtype=float)
        energies = node_energy(spec, degrees, n)
        value, method = float(degrees[int(np.argmin(energies))]), ZERO_T_METHOD
    else:
        beta = float(((spec.get("dynamics") or {}).get("beta")) or 1.0)
        value, method = gibbs_mean_degree(spec, n, cap, beta), GIBBS_METHOD
    return {"mean_degree": value, "method": method, "too_dense": value >= cap - 0.5}


def accuracy(pairs) -> dict:
    pairs = [(float(p), float(m)) for p, m in pairs if p is not None and m is not None]
    if not pairs:
        return {"compared": 0}
    predicted = np.array([p for p, _ in pairs])
    measured = np.array([m for _, m in pairs])
    miss = np.abs(measured - predicted)
    spread = float(((measured - measured.mean()) ** 2).sum())
    return {"compared": len(pairs),
            "r2": (round(1.0 - float(((measured - predicted) ** 2).sum()) / spread, 4) if spread > 0 else None),
            "within_a_quarter": round(float(np.mean(miss <= 0.25)), 4),
            "within_one": round(float(np.mean(miss <= 1.0)), 4),
            "median_miss": round(float(np.median(miss)), 4)}
