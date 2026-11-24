from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.dsl.dsl import coefficient, dynamics_regime
from graph_scale_dynamics.research.degree_prediction import (
    DEGREE_OPS, GIBBS_METHOD, KIND_CORRELATIONS, KIND_CYCLES, KIND_DEGREES, NODE_ENERGY, gibbs_mean_degree,
    law_kind, predicted_mean_degree,
)

PREDICTOR_CONTRACT = "gsd-degree-prediction-l2-1"
GRADIENT_OP = "degree_neighbor_gradient"
CYCLE_OPS = ("triangle_count", "triangle_edge_overlap", "square_count", "induced_square_count",
             "square_edge_overlap")
_ITERATIONS = 30
_SETTLED = 1e-4

ZERO_T_REGULAR = "zero temperature: a regular wiring at the degree its degree terms prefer"
ZERO_T_CLIQUE = "zero temperature: cliques K_(d+1)"
MEAN_FIELD = "finite temperature: the Gibbs saddle point with the gradient in mean field"


def _terms(spec: dict, n: int) -> tuple[list[tuple[dict, float]], float, dict]:
    degree, gradient, cycles = [], 0.0, {op: 0.0 for op in CYCLE_OPS}
    for term in spec.get("terms") or []:
        op, c = term.get("op"), coefficient(term, int(n))
        if op in DEGREE_OPS:
            degree.append((term, c))
        elif op == GRADIENT_OP:
            gradient += c
        elif op in cycles:
            cycles[op] += c
    return degree, gradient, cycles


def _f(degree_terms, d) -> np.ndarray:
    d = np.asarray(d, dtype=float)
    total = np.zeros_like(d)
    for term, c in degree_terms:
        total = total + c * NODE_ENERGY[term["op"]](d, float((term.get("params") or {}).get("k", 0)))
    return total


def clique_cycles_per_node(d: int) -> dict:
    n = d + 1
    if d < 2:
        return {op: 0.0 for op in CYCLE_OPS}
    triangles_per_edge = n - 2
    squares_per_edge = (n - 2) * (n - 3)
    return {
        "triangle_count": math.comb(n, 3) / n,
        "triangle_edge_overlap": (d / 2.0) * math.comb(triangles_per_edge, 2),
        "square_count": 3.0 * math.comb(n, 4) / n,
        "induced_square_count": 0.0,
        "square_edge_overlap": (d / 2.0) * math.comb(squares_per_edge, 2),
    }


def downhill_rest(f: np.ndarray) -> int:
    d = 0
    while d + 1 < len(f) and f[d + 1] < f[d]:
        d += 1
    return d


def _zero_temperature(degree_terms, cycles: dict, cap: float) -> tuple[float, str]:
    top = int(math.floor(float(cap)))
    f = _f(degree_terms, np.arange(0, top + 1, dtype=float))
    rest = downhill_rest(f)
    best = (float(f[rest]), float(rest), ZERO_T_REGULAR)
    if rest >= 2 and any(c < 0.0 for c in cycles.values()):
        for d in range(2, top + 1):
            per_node = clique_cycles_per_node(d)
            energy = float(f[d]) + sum(cycles[op] * per_node[op] for op in CYCLE_OPS)
            if energy < best[0] - 1e-12:
                best = (energy, float(d), ZERO_T_CLIQUE)
    return round(best[1], 4), best[2]


def _gibbs_fixed_point(degree_terms, gradient: float, n: int, cap: float, beta: float) -> float:
    from scipy.special import gammaln, logsumexp
    degrees = np.arange(0, int(math.ceil(float(cap))) + 2, dtype=float)
    base = _f(degree_terms, degrees)
    extra = np.zeros_like(base)
    grid = np.arange(0.01, float(cap) + 0.005, 0.01)
    m = None
    for _ in range(_ITERATIONS):
        log_weights = -float(beta) * (base + extra) - gammaln(degrees + 1.0)
        log_y = 0.5 * np.log(float(n) * grid)
        free = logsumexp(log_weights[None, :] + log_y[:, None] * degrees[None, :], axis=1) - grid / 2.0
        new_m = float(grid[int(np.argmax(free))])
        logp = log_weights + 0.5 * np.log(float(n) * new_m) * degrees
        p = np.exp(logp - logsumexp(logp))
        mean = float((degrees * p).sum())
        q = degrees * p / mean if mean > 0 else p
        second = ((degrees[:, None] - degrees[None, :]) ** 2 * q[None, :]).sum(axis=1)
        new_extra = gradient * degrees / 2.0 * second
        if m is not None and abs(new_m - m) < _SETTLED and np.allclose(new_extra, extra, atol=1e-9):
            m = new_m
            break
        m, extra = new_m, new_extra
    return round(float(m or 0.0), 4)


def predicted_mean_degree_extended(spec: dict, n: int, cap: float) -> dict:
    kind = law_kind(spec)
    if kind == KIND_DEGREES:
        base = predicted_mean_degree(spec, n, cap) or {}
        return {**base, "kind": kind, "step": "538"}
    degree_terms, gradient, cycles = _terms(spec, n)
    rewards_cycles = any(c < 0.0 for c in cycles.values())
    if dynamics_regime(spec) == "zero_temperature":
        value, method = _zero_temperature(degree_terms, cycles, float(cap))
    else:
        beta = float(((spec.get("dynamics") or {}).get("beta")) or 1.0)
        if gradient > 0.0:
            value, method = _gibbs_fixed_point(degree_terms, gradient, int(n), float(cap), beta), MEAN_FIELD
        else:
            degree_only = {"terms": [term for term, _ in degree_terms], "dynamics": spec.get("dynamics") or {}}
            value, method = gibbs_mean_degree(degree_only, int(n), float(cap), beta), GIBBS_METHOD
    return {"mean_degree": value, "method": method, "too_dense": value >= float(cap) - 0.5, "kind": kind,
            "step": "correlations" if kind == KIND_CORRELATIONS else "cycles",
            "rewards_cycles": rewards_cycles}


def stratum(prediction: dict, regime: str) -> str:
    kind = prediction.get("kind")
    label = {KIND_DEGREES: "degrees", KIND_CORRELATIONS: "correlations", KIND_CYCLES: "cycles"}[kind]
    if kind == KIND_CYCLES:
        label += ", rewards cycles" if prediction.get("rewards_cycles") else ", no cycle reward"
    return f"{label} / {'zero temperature' if regime == 'zero_temperature' else 'finite temperature'}"


def ledger_entry(spec: dict, n: int, cap: float) -> list:
    prediction = predicted_mean_degree_extended(spec, n, cap)
    return [prediction.get("mean_degree"), stratum(prediction, dynamics_regime(spec))]
