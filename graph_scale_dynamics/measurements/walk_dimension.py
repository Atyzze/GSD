from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.measurements.fits import line

WALK_DIMENSION_CONTRACT = "gsd-walk-dimension-2"

WALK_DIMENSION = "walk_dimension"
WALK_DIMENSION_ALIAS = "d_w"

EUCLIDEAN_WALK_DIMENSION = 2.0

FIRST_TIME = 8
EQUILIBRIUM_SHARE = 0.25
MIN_WALK_POINTS = 5
SLOWEST_SPREAD = 0.1
TIMES = 24
SOURCES = 48
WALKS_A_SOURCE = 16


def _bfs_distances(adj, source: int, n: int) -> np.ndarray:
    distance = np.full(n, -1, dtype=np.int64)
    distance[source] = 0
    frontier = [source]
    step = 0
    while frontier:
        step += 1
        nxt = []
        for vertex in frontier:
            for neighbour in adj[vertex]:
                neighbour = int(neighbour)
                if distance[neighbour] < 0:
                    distance[neighbour] = step
                    nxt.append(neighbour)
        frontier = nxt
    return distance


def walk_times(n_component: int, max_steps: int | None = None) -> tuple[list[int], int]:
    if max_steps is None:
        max_steps = max(16, int(4 * math.sqrt(n_component)))
    return sorted({int(round(value)) for value in np.geomspace(2, max_steps, num=TIMES)}), int(max_steps)


def walk_displacement_profile(adj, component: np.ndarray, rng: np.random.Generator,
                              *, sources: int = SOURCES, walks_a_source: int = WALKS_A_SOURCE,
                              max_steps: int | None = None, keep_sources: bool = False) -> dict:
    n_component = len(component)
    if n_component < 32:
        return {"valid": False, "refusal": "COMPONENT_BELOW_MEASURABLE_SIZE",
                "reason": f"component has {n_component} vertices"}
    times, max_steps = walk_times(n_component, max_steps)
    max_index = int(component.max()) + 1
    picked = rng.choice(component, size=min(sources, n_component), replace=False)
    degree = np.array([len(adj[v]) for v in range(max_index)], dtype=float)
    squares = np.zeros((len(picked), len(times)), dtype=float)
    equilibrium: list[float] = []
    balls: list[np.ndarray] = []

    for row, source in enumerate(picked):
        source = int(source)
        distance = _bfs_distances(adj, source, max_index)
        reached = distance >= 0
        weights = degree[reached]
        equilibrium.append(float(np.sum(weights * distance[reached].astype(float) ** 2) / weights.sum()))
        balls.append(np.cumsum(np.bincount(distance[reached])).astype(float))
        for _ in range(walks_a_source):
            position = source
            target = 0
            for step in range(1, max_steps + 1):
                neighbours = adj[position]
                position = int(neighbours[rng.integers(len(neighbours))])
                if step == times[target]:
                    squares[row, target] += float(distance[position]) ** 2
                    target += 1
                    if target == len(times):
                        break
    squares /= float(walks_a_source)
    horizon = max(len(ball) for ball in balls)
    padded = np.stack([np.concatenate([ball, np.full(horizon - len(ball), ball[-1])]) for ball in balls])
    mean_ball = padded.mean(axis=0)
    return {
        "valid": True,
        "component_size": int(n_component),
        "times": [int(t) for t in times],
        "mean_square_displacement": squares.mean(axis=0).tolist(),
        "ball_volumes": [[int(radius), float(mean_ball[radius])] for radius in range(1, horizon)],
        "sources": int(len(picked)),
        "walks_a_source": int(walks_a_source),
        "max_steps": int(max_steps),
        "equilibrium_msd": float(np.mean(equilibrium)),
        **({"source_squares": squares.tolist()} if keep_sources else {}),
    }


SOURCE_BOOTSTRAP_REPLICATES = 100
SOURCE_BOOTSTRAP_SEED = 691


def _source_bootstrap_se(squares, log_times: np.ndarray, window: np.ndarray) -> dict | None:
    if squares is None:
        return None
    squares = np.asarray(squares, dtype=float)
    if squares.ndim != 2 or squares.shape[0] < 8:
        return None
    squares = squares[:, window]
    stream = np.random.default_rng(SOURCE_BOOTSTRAP_SEED)
    sources = squares.shape[0]
    exponents = []
    for _ in range(SOURCE_BOOTSTRAP_REPLICATES):
        msd = squares[stream.integers(0, sources, sources)].mean(axis=0)
        if np.any(msd <= 0):
            continue
        slope = line(log_times, np.log(msd))["slope"]
        if slope > 1e-6:
            exponents.append(2.0 / slope)
    if len(exponents) < SOURCE_BOOTSTRAP_REPLICATES // 2:
        return None
    return {"method": "bootstrap over sources", "sources": int(sources), "replicates": len(exponents),
            "se": float(np.std(np.asarray(exponents), ddof=1))}


def walk_window(times, msd, equilibrium_msd: float, settled_from: int = 1) -> np.ndarray:
    times, msd = np.asarray(times, dtype=float), np.asarray(msd, dtype=float)
    inside = []
    for index in range(len(times)):
        if times[index] < FIRST_TIME or msd[index] < float(settled_from) ** 2:
            continue
        if msd[index] > EQUILIBRIUM_SHARE * float(equilibrium_msd):
            break
        inside.append(index)
    return np.asarray(inside, dtype=int)


def fit_walk_dimension(profile: dict, settled_from: int = 1) -> dict:
    if not profile.get("valid"):
        return {"valid": False, "refusal": profile.get("refusal") or "NO_SCALING_WINDOW",
                "reason": profile.get("reason", "no usable profile")}
    times = np.asarray(profile["times"], dtype=float)
    msd = np.asarray(profile["mean_square_displacement"], dtype=float)
    window = walk_window(times, msd, profile["equilibrium_msd"], settled_from)
    if len(window) < MIN_WALK_POINTS:
        saturated = bool(msd[-1] > EQUILIBRIUM_SHARE * float(profile["equilibrium_msd"]))
        return {"valid": False, "refusal": "WALK_SATURATED" if saturated else "WINDOW_TOO_SHORT",
                "reason": (f"{len(window)} times between {FIRST_TIME} steps, a walker {int(settled_from)} steps from "
                           f"its start where the balls' exponent has settled, and "
                           + (f"{EQUILIBRIUM_SHARE:g} of the mean square distance of a walker that has forgotten its "
                              f"start; need {MIN_WALK_POINTS}: the component is explored before a scaling regime can "
                              "form" if saturated else
                              f"the walk's last step; need {MIN_WALK_POINTS}: the walk ends before a scaling regime "
                              "can form")),
                "saturated": saturated}
    times, msd = times[window], msd[window]
    growth = float(msd[-1] / msd[0]) if msd[0] > 0 else 0.0
    fitted = line(np.log(times), np.log(msd))
    slope = fitted["slope"]
    if slope < SLOWEST_SPREAD:
        return {"valid": False, "refusal": "UNPHYSICAL_FIT",
                "reason": (f"the mean square distance grows slower than time to the power {SLOWEST_SPREAD:g}: the "
                           "walker does not spread, and 2/slope would diverge rather than measure a dimension")}

    se = abs(2.0 / slope) * (fitted["rms"] / max(abs(slope), 1e-9)) / math.sqrt(len(times))
    bootstrap = _source_bootstrap_se(profile.get("source_squares"), np.log(times), window)
    if bootstrap is not None:
        se = bootstrap["se"]
    return {
        "valid": True,
        "contract": WALK_DIMENSION_CONTRACT,
        WALK_DIMENSION: 2.0 / slope,
        "msd_slope": slope,
        "se": se,
        **({"se_method": bootstrap} if bootstrap is not None else {}),
        "points_used": int(len(times)),
        "times_used": [int(t) for t in times],
        "subdiffusive": bool(2.0 / slope > EUCLIDEAN_WALK_DIMENSION + 0.15),
        "msd_growth": growth,
        "saturated": False,
    }


def walk_dimension(adj, component: np.ndarray, rng: np.random.Generator,
                   **kwargs) -> dict:
    return fit_walk_dimension(walk_displacement_profile(adj, component, rng, **kwargs))


EINSTEIN_CONSISTENT = "SCALING_RELATION_CONSISTENT"
EINSTEIN_VIOLATED = "SCALING_RELATION_VIOLATED"
EINSTEIN_UNRESOLVED = "SCALING_RELATION_UNRESOLVED"


def einstein_relation_check(*, spectral=None, mass=None, walk=None,
                            tolerance: float = 0.35) -> dict:
    values = {"spectral": spectral, "mass": mass, "walk": walk}
    missing = [name for name, value in values.items()
               if not isinstance(value, (int, float)) or isinstance(value, bool)
               or not math.isfinite(float(value))]
    if missing:
        return {
            "contract": WALK_DIMENSION_CONTRACT,
            "verdict": EINSTEIN_UNRESOLVED,
            "reason": f"channels not measured: {', '.join(sorted(missing))}",
        }

    spectral, mass, walk = float(spectral), float(mass), float(walk)
    if walk <= 0:
        return {
            "contract": WALK_DIMENSION_CONTRACT,
            "verdict": EINSTEIN_UNRESOLVED,
            "reason": "walk dimension must be positive",
        }

    predicted = 2.0 * mass / walk
    residual = spectral - predicted
    consistent = abs(residual) <= tolerance

    return {
        "contract": WALK_DIMENSION_CONTRACT,
        "verdict": EINSTEIN_CONSISTENT if consistent else EINSTEIN_VIOLATED,
        "spectral_measured": spectral,
        "spectral_predicted": predicted,
        "residual": residual,
        "tolerance": tolerance,
        "mass_dimension": mass,
        "walk_dimension": walk,
        "anomalous_diffusion": walk > EUCLIDEAN_WALK_DIMENSION + 0.15,
        "reason": (
            f"d_s measured {spectral:.3f} against 2*d_f/d_w = {predicted:.3f}; "
            f"residual {residual:+.3f} within {tolerance}"
            if consistent else
            f"d_s measured {spectral:.3f} but 2*d_f/d_w predicts {predicted:.3f}; "
            f"residual {residual:+.3f} exceeds {tolerance}, so at least one "
            "channel is not measuring what the relation assumes"
        ),
    }
