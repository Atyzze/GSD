from __future__ import annotations

import math

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.special import jv

GROUP = "quantum_walk"
VERSION = "quantum-walk-1"
CHANNELS = ("q_alpha", "q_decay")
STREAM = 0x51A7
MIN_COMPONENT = 64
STARTS = 4
STEP = 2.0
HORIZON_CAP = 1024.0
EARLIEST = 4.0 * math.pi
SMOOTHING = 4.0 * math.pi
SATURATION = 0.5
MIN_SPAN = 4.0
MIN_POINTS = 6
TOLERANCE = 1e-15


def _refused(reason: str, refusal: str) -> dict:
    return {"valid": False, "value": None, "se": None, "reason": reason, "refusal": refusal}


def _read(value: float, se: float) -> dict:
    return {"valid": True, "value": float(value), "se": float(se), "reason": None, "refusal": None}


def _all_refused(reason: str, refusal: str, **context) -> dict:
    return {"channels": {name: _refused(reason, refusal) for name in CHANNELS}, **context}


def _adjacency(n: int, edges) -> sparse.csr_matrix:
    pairs = np.asarray([(int(a), int(b)) for a, b in edges if int(a) != int(b)], dtype=np.int64).reshape(-1, 2)
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    matrix = sparse.csr_matrix((np.ones(rows.size), (rows, cols)), shape=(int(n), int(n)))
    matrix.sum_duplicates()
    matrix.data[:] = 1.0
    return matrix


def _largest_component(adjacency: sparse.csr_matrix) -> sparse.csr_matrix:
    _count, labels = csgraph.connected_components(adjacency, directed=False)
    keep = np.flatnonzero(labels == np.argmax(np.bincount(labels)))
    return adjacency[keep][:, keep].tocsr()


def _normalized(adjacency: sparse.csr_matrix) -> sparse.csr_matrix:
    scale = sparse.diags(1.0 / np.sqrt(np.asarray(adjacency.sum(axis=1)).ravel()))
    return (scale @ adjacency @ scale).tocsr()


def chebyshev_weights(step: float) -> np.ndarray:
    weights = []
    order = 0
    while True:
        bessel = jv(order, step)
        weights.append((1.0 if order == 0 else 2.0) * bessel * (-1j) ** order)
        if order > step + 4 and abs(bessel) < TOLERANCE:
            return np.asarray(weights, dtype=complex)
        order += 1


def propagate(hamiltonian: sparse.csr_matrix, state: np.ndarray, weights: np.ndarray) -> np.ndarray:
    previous = state
    current = hamiltonian @ state
    total = weights[0] * previous + weights[1] * current
    for weight in weights[2:]:
        previous, current = current, 2.0 * (hamiltonian @ current) - previous
        total = total + weight * current
    return total


def _slope(times: np.ndarray, values: np.ndarray) -> tuple[float, float] | None:
    keep = values > 0
    if int(keep.sum()) < MIN_POINTS:
        return None
    x, y = np.log(times[keep]), np.log(values[keep])
    design = np.vstack([x, np.ones_like(x)]).T
    coefficients, residual, _rank, _sv = np.linalg.lstsq(design, y, rcond=None)
    dof = max(1, x.size - 2)
    variance = (float(residual[0]) if residual.size else 0.0) / dof
    spread = float(((x - x.mean()) ** 2).sum())
    return float(coefficients[0]), math.sqrt(variance / spread) if spread > 0 else float("inf")


def walk(hamiltonian: sparse.csr_matrix, starts: np.ndarray, distances: np.ndarray, horizon: float) -> dict:
    size = hamiltonian.shape[0]
    state = np.zeros((size, starts.size), dtype=complex)
    state[starts, np.arange(starts.size)] = 1.0
    weights = chebyshev_weights(STEP)
    squared = (distances.T ** 2)
    times, returns, spreads = [], [], []
    for index in range(1, int(horizon / STEP) + 1):
        state = propagate(hamiltonian, state, weights)
        density = np.abs(state) ** 2
        times.append(index * STEP)
        returns.append(float(density[starts, np.arange(starts.size)].mean()))
        spreads.append(float((density * squared).sum(axis=0).mean()))
    return {"times": np.asarray(times), "returns": np.asarray(returns), "spreads": np.asarray(spreads)}


def measure(n: int, edges, seed: int) -> dict:
    if not edges:
        return _all_refused("no edges", "EMPTY_GRAPH", component=0)
    adjacency = _largest_component(_adjacency(n, edges))
    size = adjacency.shape[0]
    if size < MIN_COMPONENT:
        return _all_refused(f"the largest component holds {size} nodes, under {MIN_COMPONENT}", "TOO_SMALL",
                            component=int(size))
    rng = np.random.default_rng([int(seed), STREAM])
    starts = np.sort(rng.choice(size, size=min(STARTS, size), replace=False))
    distances = csgraph.shortest_path(adjacency, method="D", unweighted=True, indices=starts)
    eccentricity = float(distances.max(axis=1).mean())
    horizon = min(HORIZON_CAP, max(4.0 * EARLIEST, 4.0 * eccentricity))
    run = walk(_normalized(adjacency), starts, distances, horizon)
    times = run["times"]
    reach = np.sqrt(run["spreads"])
    saturated = np.flatnonzero(reach >= SATURATION * eccentricity)
    latest = float(times[saturated[0]]) if saturated.size else float(times[-1])
    context = {"component": int(size), "eccentricity": eccentricity, "horizon": float(horizon),
               "readable_until": latest}
    if latest / EARLIEST < MIN_SPAN:
        reason = (f"the walk reaches half the graph's eccentricity at t={latest:.1f}, under {MIN_SPAN} times "
                  f"the earliest time read, {EARLIEST:.1f}")
        return _all_refused(reason, "SATURATES_EARLY", **context)
    window = (times >= EARLIEST) & (times <= latest)
    channels = {}
    alpha = _slope(times[window], run["spreads"][window])
    channels["q_alpha"] = _read(*alpha) if alpha else _refused("too few times to fit", "TOO_FEW_POINTS")
    width = max(1, int(round(SMOOTHING / STEP)))
    smooth = np.convolve(run["returns"], np.ones(width) / width, mode="valid")
    centres = times[width // 2: width // 2 + smooth.size]
    inside = (centres >= EARLIEST) & (centres <= latest)
    decay = _slope(centres[inside], smooth[inside])
    channels["q_decay"] = (_read(-decay[0], decay[1]) if decay
                           else _refused("too few times to fit", "TOO_FEW_POINTS"))
    return {"channels": channels, **context}
