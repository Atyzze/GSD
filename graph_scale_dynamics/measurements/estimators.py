from __future__ import annotations
import math
import time
import os
from collections import deque

import numpy as np

from graph_scale_dynamics.measurements.fits import aicc, line

MIN_DH_WINDOW_POINTS = 4
BALL_SATURATION = 0.55


def build_adjacency(n: int, edges) -> list[np.ndarray]:
    neighbors: list[list[int]] = [[] for _ in range(n)]
    for u, v in edges:
        neighbors[u].append(v)
        neighbors[v].append(u)
    return [np.asarray(sorted(row), dtype=np.int32) for row in neighbors]


def largest_component(n: int, adj) -> np.ndarray:
    seen = np.full(n, -1, dtype=np.int32)
    best: np.ndarray | None = None
    label = 0
    for start in range(n):
        if seen[start] >= 0:
            continue
        queue = deque([start])
        seen[start] = label
        members = [start]
        while queue:
            node = queue.popleft()
            for other in adj[node]:
                if seen[other] < 0:
                    seen[other] = label
                    members.append(other)
                    queue.append(other)
        if best is None or len(members) > len(best):
            best = np.asarray(members, dtype=np.int32)
        label += 1
    return best if best is not None else np.zeros(0, dtype=np.int32)


def _bfs_layers(adj, source: int, r_max: int) -> tuple[np.ndarray, bool]:
    dist = {source: 0}
    frontier = [source]
    sizes = [1]
    truncated = True
    for radius in range(1, r_max + 1):
        nxt = []
        for node in frontier:
            for other in adj[node]:
                if other not in dist:
                    dist[other] = radius
                    nxt.append(other)
        sizes.append(sizes[-1] + len(nxt))
        frontier = nxt
        if not frontier:
            sizes.extend([sizes[-1]] * (r_max - radius))
            truncated = False
            break
    return np.asarray(sizes, dtype=float), truncated


def _bfs_target_radius(adj, source: int, target_vertices: int) -> int:
    if target_vertices <= 1:
        return 0
    seen = {source}
    frontier = [source]
    radius = 0
    while frontier and len(seen) < target_vertices:
        radius += 1
        nxt = []
        for node in frontier:
            for other in adj[node]:
                other = int(other)
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    if len(seen) < target_vertices:
        raise ValueError("half-volume target exceeds the source component")
    return radius


SOURCES_ON_A_SMALL_GRAPH = 128
NODES_THEY_MAY_VISIT = 524288


def sources_for_the_verdict(n_component: int) -> int:
    usual = min(64, max(24, 2 * math.ceil(math.log2(max(2, n_component)))))
    return max(usual, min(SOURCES_ON_A_SMALL_GRAPH, NODES_THEY_MAY_VISIT // max(1, n_component)))


def volume_growth(adj, component: np.ndarray, rng: np.random.Generator,
                  sources: int | None = None, r_max: int | None = None, keep_sources: bool = False) -> dict:
    n_component = len(component)
    sources = sources or min(64, max(24, 2 * math.ceil(math.log2(max(2, n_component)))))
    r_max = r_max or min(128, max(40, 4 * math.ceil(math.log2(max(2, n_component)))))
    picks = rng.choice(component, size=min(sources, n_component), replace=False)
    layers = [_bfs_layers(adj, int(s), r_max) for s in picks]
    balls = np.stack([row for row, _ in layers])
    incomplete = [bool(row[-1] < n_component) for row, _ in layers]
    truncated_sources = int(sum(incomplete))
    mean = balls.mean(axis=0)
    se = balls.std(axis=0, ddof=1) / math.sqrt(len(picks)) if len(picks) > 1 else np.zeros_like(mean)
    apart = np.log(balls).std(axis=0, ddof=1) if len(picks) > 1 else np.zeros_like(mean)

    exact_eccentricities: list[int] = []
    eccentricity_lower_bounds: list[int] = []
    for row, cut in zip(balls, incomplete):
        if not cut:
            eccentricity = int(np.searchsorted(row, n_component))
            exact_eccentricities.append(eccentricity)
            eccentricity_lower_bounds.append(eccentricity)
        else:
            eccentricity_lower_bounds.append(int(r_max) + 1)

    half_target = int(math.ceil(0.5 * n_component))
    half_radii: list[float] = []
    extended_sources = 0
    for source, row in zip(picks, balls):
        if row[-1] >= half_target:
            half_radii.append(float(np.searchsorted(row, half_target)))
        else:
            extended_sources += 1
            half_radii.append(float(_bfs_target_radius(adj, int(source), half_target)))
    half_fraction = len(half_radii) / max(1, len(balls))
    half_radius = float(np.mean(half_radii)) if half_radii else None
    half_radius_se = (float(np.std(half_radii, ddof=1) / math.sqrt(len(half_radii)))
                      if len(half_radii) > 1 else None)

    diameter_lower = int(max(eccentricity_lower_bounds)) if eccentricity_lower_bounds else None
    diameter_upper = (min(n_component - 1, 2 * min(exact_eccentricities))
                      if exact_eccentricities else None)
    result = {"radii": list(range(len(mean))), "mean_ball": mean.tolist(), "se": se.tolist(),
              "sources_apart": apart.tolist(), "sources": int(len(picks)), "r_max": int(r_max),
              "truncated_sources": truncated_sources,
              "truncated": bool(truncated_sources),
              "half_volume_radius": half_radius,
              "half_volume_radius_se": half_radius_se,
              "half_volume_radius_source_fraction": half_fraction,
              "half_volume_radius_extended_sources": int(extended_sources),
              "eccentricity_lower_bound": diameter_lower,
              "diameter_upper_bound": diameter_upper}
    if truncated_sources:
        result["eccentricity_max"] = None
    else:
        result["eccentricity_max"] = int(max(exact_eccentricities))
    result["mean_distance_proxy"] = half_radius
    if keep_sources:
        result["balls_per_source"] = balls
    return result


SOURCE_BOOTSTRAP_REPLICATES = 100
SOURCE_BOOTSTRAP_SEED = 691


def _source_bootstrap_se(balls, n_component: int) -> dict | None:
    if balls is None:
        return None
    balls = np.asarray(balls, dtype=float)
    if balls.ndim != 2 or balls.shape[0] < 8:
        return None
    stream = np.random.default_rng(SOURCE_BOOTSTRAP_SEED)
    sources = balls.shape[0]
    estimates = []
    for _ in range(SOURCE_BOOTSTRAP_REPLICATES):
        mean = balls[stream.integers(0, sources, sources)].mean(axis=0)
        upto = last_radius_of_the_window(mean, n_component)
        mean = mean if upto is None else mean[:upto + 1]
        radii = np.arange(len(mean), dtype=float)
        idx = np.where((radii >= 1) & (mean > 1.0) & (mean < BALL_SATURATION * n_component))[0]
        if len(idx) < MIN_DH_WINDOW_POINTS:
            continue
        upper_start = (len(idx) - 1) // 2
        estimates.append(line(np.log(half_width(radii[idx]))[upper_start:], np.log(mean[idx])[upper_start:])["slope"])
    if len(estimates) < SOURCE_BOOTSTRAP_REPLICATES // 2:
        return None
    return {"method": "bootstrap over sources, the window found again in each", "sources": int(sources),
            "replicates": len(estimates), "se": float(np.std(np.asarray(estimates), ddof=1))}


GROWTH_AICC_MARGIN = 4.0
RISES_AT_MOST = 1.0 / 3.0
SOURCES_APART_AT_MOST = 0.85
WITHIN_OF_THE_STEEPEST = 0.05
THE_FALL_SHRINKS_TO = 0.65
SETTLING_IS_READ_FROM = 8
SETTLED_WITHIN = 0.1
POWER, EXPONENTIAL, UNDECIDED, UNEVEN = "power", "exponential", "undecided", "uneven"
UNTESTED, TOO_SMALL = "untested", "too small"
NO_DIMENSION = {
    EXPONENTIAL: ("EXPONENTIAL_GROWTH", "the balls grow exponentially with the radius: no dimension exists on this "
                                        "geometry"),
    UNDECIDED: ("GROWTH_UNDECIDED", "the balls grow neither clearly as a power of the radius nor clearly "
                                    "exponentially: no dimension is read where the growth cannot be told"),
    UNEVEN: ("GROWTH_UNEVEN", "the balls of one node and another differ by more than a geometry's do: a dimension is "
                              "the same from every node, and none is read where the nodes do not agree"),
}
TOO_FEW_RADII = (f"the balls hold more than {BALL_SATURATION:g} of the component within {MIN_DH_WINDOW_POINTS} steps: "
                 "the graph is too small to tell how they grow, and no probe reads")
WINDOW_TOO_SHORT_TO_TEST = (f"fewer than {MIN_DH_WINDOW_POINTS} radii before the balls' growth falls away: too few to "
                            "tell how they grow, and no probe reads")
NOT_CLEARLY_A_POWER = {**NO_DIMENSION, TOO_SMALL: ("NO_SCALING_WINDOW", TOO_FEW_RADII),
                       UNTESTED: ("NO_SCALING_WINDOW", WINDOW_TOO_SHORT_TO_TEST)}


def half_width(radii) -> np.ndarray:
    return np.asarray(radii, dtype=float) + 0.5


def _exponent_between(log_width: np.ndarray, log_ball: np.ndarray, lower: int, upper: int) -> float:
    return float((log_ball[upper] - log_ball[lower]) / (log_width[upper] - log_width[lower]))


def last_radius_of_the_window(mean_ball, n_component: int) -> int | None:
    ball = np.asarray(mean_ball, dtype=float)
    radii = np.arange(len(ball))
    usable = np.where((radii >= 1) & (ball > 1.0) & (ball < BALL_SATURATION * n_component))[0]
    if len(usable) < 2:
        return None
    top = int(usable[-1])
    log_width, log_ball = np.log(half_width(radii)), np.log(ball)
    exponent = np.full(top + 1, -np.inf)
    exponent[2:] = np.diff(log_ball[1:top + 1]) / np.diff(log_width[1:top + 1])
    steepest_so_far = np.maximum.accumulate(exponent)
    for radius in range(top, 1, -1):
        if exponent[radius] >= (1.0 - WITHIN_OF_THE_STEEPEST) * steepest_so_far[radius]:
            return radius
        if radius >= SETTLING_IS_READ_FROM:
            half, quarter, eighth = radius // 2, radius // 4, radius // 8
            late = _exponent_between(log_width, log_ball, half, radius)
            before = _exponent_between(log_width, log_ball, quarter, half)
            first = _exponent_between(log_width, log_ball, eighth, quarter)
            if 0.0 < before - late <= THE_FALL_SHRINKS_TO * (first - before):
                return radius
    return None


def radius_the_exponent_has_settled_from(mean_ball, last: int, exponent: float) -> int:
    ball = np.asarray(mean_ball, dtype=float)
    log_width, log_ball = np.log(half_width(np.arange(len(ball)))), np.log(ball)
    for radius in range(2, int(last) + 1):
        over_the_octave_below = _exponent_between(log_width, log_ball, radius // 2, radius)
        if abs(over_the_octave_below - exponent) <= SETTLED_WITHIN * abs(exponent):
            return radius - 1
    return int(last)


def growth_of_the_balls(radii, mean_ball, sources_apart=None) -> dict:
    radii, log_ball = np.asarray(radii, dtype=float), np.log(np.asarray(mean_ball, dtype=float))
    if len(radii) < MIN_DH_WINDOW_POINTS:
        return {"verdict": UNTESTED, "radii": int(len(radii))}
    log_width = np.log(half_width(radii))
    as_a_power = line(log_width, log_ball)
    as_an_exponential = line(radii, log_ball)
    delta = aicc(as_a_power["residuals"], 2) - aicc(as_an_exponential["residuals"], 2)
    third = max(2, len(radii) // 3)
    early = line(log_width[:third + 1], log_ball[:third + 1])["slope"]
    late = line(log_width[-third - 1:], log_ball[-third - 1:])["slope"]
    rises = float((late - early) / late) if late > 0 else 0.0
    apart = None if sources_apart is None else float(np.max(np.asarray(sources_apart, dtype=float)))
    a_power = delta <= -GROWTH_AICC_MARGIN and rises <= RISES_AT_MOST
    verdict = (EXPONENTIAL if delta >= GROWTH_AICC_MARGIN and as_an_exponential["slope"] > 0
               else UNDECIDED if not a_power
               else UNEVEN if apart is not None and apart > SOURCES_APART_AT_MOST else POWER)
    return {"verdict": verdict, "delta_aicc": float(delta), "radii": int(len(radii)),
            "as_a_power": as_a_power["slope"], "as_an_exponential": as_an_exponential["slope"],
            "early_exponent": float(early), "late_exponent": float(late), "rises": rises,
            **({} if apart is None else {"sources_apart": apart})}


def _se_without_sources(volume: dict, idx: np.ndarray, half_widths: np.ndarray, ball: np.ndarray,
                        upper: np.ndarray) -> float:
    of_the_mean = np.asarray(volume.get("se") or np.zeros(int(idx[-1]) + 1), dtype=float)[idx]
    of_a_slope = (np.sqrt((of_the_mean[1:] / np.maximum(ball[1:], 1e-12)) ** 2
                          + (of_the_mean[:-1] / np.maximum(ball[:-1], 1e-12)) ** 2)
                  / np.log(half_widths[1:] / half_widths[:-1]))
    scatter = float(np.std(upper, ddof=1) / math.sqrt(len(upper))) if len(upper) > 1 else 0.0
    return math.sqrt(scatter ** 2 + float(np.median(of_a_slope[len(of_a_slope) - len(upper):])) ** 2)


def fit_dh(volume: dict, n_component: int) -> dict:
    every_radius = np.asarray(volume["radii"], dtype=float)
    every_ball = np.asarray(volume["mean_ball"], dtype=float)
    reached = int(np.sum((every_radius >= 1) & (every_ball > 1.0) & (every_ball < BALL_SATURATION * n_component)))
    if reached < MIN_DH_WINDOW_POINTS:
        return {"valid": False, "refusal": "NO_SCALING_WINDOW", "reason": TOO_FEW_RADII,
                "volume_growth": {"verdict": TOO_SMALL, "radii": reached}, "window_cut_at": None}
    upto = last_radius_of_the_window(every_ball, n_component)
    last = len(every_radius) if upto is None else upto + 1
    radii, mean = every_radius[:last], every_ball[:last]
    idx = np.where((radii >= 1) & (mean > 1.0) & (mean < BALL_SATURATION * n_component))[0]
    apart = volume.get("sources_apart")
    growth = growth_of_the_balls(radii[idx], mean[idx], None if apart is None else np.asarray(apart, dtype=float)[idx])
    windowed = len(idx) >= MIN_DH_WINDOW_POINTS
    if windowed:
        x_w, b_w = half_width(radii[idx]), mean[idx]
        local = np.log(b_w[1:] / b_w[:-1]) / np.log(x_w[1:] / x_w[:-1])
        upper_start = len(local) // 2
        upper = local[upper_start:]
        estimate = float(line(np.log(x_w[upper_start:]), np.log(b_w[upper_start:]))["slope"])
    if growth["verdict"] in NO_DIMENSION:
        refusal, why = NO_DIMENSION[growth["verdict"]]
        return {"valid": False, "refusal": refusal, **({"would_have_reported": estimate} if windowed else {}),
                "reason": (f"{why} (delta AICc {growth['delta_aicc']:+.1f} for the exponential over the power law, "
                           f"{GROWTH_AICC_MARGIN:g} asked either way; the exponent rises by {growth['rises']:.2f} of "
                           f"itself from the first third of the window to the last, {RISES_AT_MOST:.2f} allowed"
                           + ("" if "sources_apart" not in growth else
                              f"; the sources' balls lie {growth['sources_apart']:.2f} apart in their logarithms at "
                              f"the radius of the window where they differ most, {SOURCES_APART_AT_MOST:g} allowed")
                           + ")"),
                "volume_growth": growth, "window_cut_at": upto}
    if growth["verdict"] == UNTESTED or not windowed:
        return {"valid": False, "refusal": "NO_SCALING_WINDOW", "reason": WINDOW_TOO_SHORT_TO_TEST,
                "volume_growth": growth, "window_cut_at": upto}
    bootstrap = _source_bootstrap_se(volume.get("balls_per_source"), n_component)
    return {"valid": True, "d_V_window": estimate,
            "se": bootstrap["se"] if bootstrap is not None else _se_without_sources(volume, idx, x_w, b_w, upper),
            **({"se_method": bootstrap} if bootstrap is not None else {}),
            "window": {"r_lo": int(radii[idx][0]), "r_hi": int(radii[idx][-1]), "points": int(len(idx)),
                       "settled_from": radius_the_exponent_has_settled_from(every_ball, int(radii[idx][-1]), estimate)},
            "local_slopes": [float(v) for v in local],
            "volume_growth": growth, "window_cut_at": upto}


LONGEST_WALK = 1024
SHORTEST_WALK = 260


MOST_PROBES = 256
PROBES_TIMES_NODES = 262144


def probes_for(n_component: int) -> int:
    return int(min(MOST_PROBES, max(32, 2 * math.ceil(math.log2(max(2, n_component))),
                                    PROBES_TIMES_NODES // max(1, n_component))))


def walk_length(n_component: int) -> int:
    return int(min(LONGEST_WALK, max(SHORTEST_WALK, n_component // 4)))


def return_probability(adj, component: np.ndarray, rng: np.random.Generator,
                       probes: int | None = None, t_max: int | None = None,
                       keep_probes: bool = False) -> dict:
    from scipy import sparse
    nodes = component
    remap = {int(v): i for i, v in enumerate(nodes)}
    rows, cols, vals = [], [], []
    for v in nodes:
        nbrs = adj[int(v)]
        deg = len(nbrs)
        for w in nbrs:
            rows.append(remap[int(v)])
            cols.append(remap[int(w)])
            vals.append(1.0 / deg)
    n = len(nodes)
    probes = probes or probes_for(n)
    t_max = t_max or walk_length(n)
    configured_block = max(1, int(os.environ.get("GSD_SPECTRAL_PROBE_BLOCK", "8")))
    block_size = min(probes, configured_block)
    walk = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))
    estimate_sum = np.zeros(t_max, dtype=float)
    estimate_sq_sum = np.zeros(t_max, dtype=float)
    per_probe = np.zeros((probes, t_max), dtype=float) if keep_probes else None
    completed = 0
    while completed < probes:
        width = min(block_size, probes - completed)
        z = rng.choice([-1.0, 1.0], size=(width, n)).T
        vec = z.copy()
        for t in range(t_max):
            vec = 0.5 * vec + 0.5 * (walk @ vec)
            estimates = np.sum(z * vec, axis=0) / n
            estimate_sum[t] += float(np.sum(estimates))
            estimate_sq_sum[t] += float(np.dot(estimates, estimates))
            if per_probe is not None:
                per_probe[completed:completed + width, t] = estimates
        completed += width

    p0 = estimate_sum / probes
    if probes > 1:
        sample_var = (estimate_sq_sum - (estimate_sum * estimate_sum) / probes) / (probes - 1)
        p0_se = np.sqrt(np.maximum(sample_var, 0.0) / probes)
    else:
        p0_se = np.zeros(t_max, dtype=float)
    out = {"t": list(range(1, t_max + 1)), "p0": p0.tolist(),
           "p0_se": p0_se.tolist(), "probes": probes, "probe_block_size": block_size,
           "t_max": t_max, "component_size": n,
           "method": "hutchinson_trace_lazy_walk_blocked"}
    if per_probe is not None:
        out["p0_per_probe"] = per_probe
    return out


DIFFUSIVE_WINDOW_MIN_DELTA_AICC = 2.0


def diffusive_window_evidence(t_window: np.ndarray, q_window: np.ndarray) -> dict:
    t_window = np.asarray(t_window, dtype=float)
    q_window = np.asarray(q_window, dtype=float)
    if len(t_window) < 5 or np.any(q_window <= 0.0):
        return {"comparable": False, "reason": "window too short for a model comparison"}
    log_q = np.log(q_window)
    power, exponential = line(np.log(t_window), log_q), line(t_window, log_q)
    delta = aicc(exponential["residuals"], 2) - aicc(power["residuals"], 2)
    return {"comparable": True, "delta_aicc": float(delta),
            "power_law_exponent": power["slope"],
            "gap_decay_rate": -exponential["slope"],
            "is_power_law": bool(delta > DIFFUSIVE_WINDOW_MIN_DELTA_AICC)}


FIRST_RETURN_TIME = 3
RETURNS_ABOVE_IN_UNITS_OF_1_OVER_N = 4.0
RETURN_GRID = 28
LATEST_SHARE = 3
NOT_SETTLED_SHARE = 0.1


def _return_grid(t: np.ndarray, q0: np.ndarray, n_component: int) -> tuple | None:
    idx = np.where((t >= FIRST_RETURN_TIME) & (q0 > RETURNS_ABOVE_IN_UNITS_OF_1_OVER_N / max(2, n_component)))[0]
    if len(idx) < 8:
        return None
    t_use, q_use = t[idx], q0[idx]
    grid = np.unique(np.geomspace(t_use[0], t_use[-1], num=min(RETURN_GRID, len(t_use))).astype(int))
    pick = np.clip(np.searchsorted(t_use, grid), 0, len(t_use) - 1)
    keep = np.concatenate([[True], np.diff(t_use[pick]) > 0])
    return idx[pick][keep], t_use[pick][keep], q_use[pick][keep]


def _latest_slope(tg: np.ndarray, qg: np.ndarray) -> dict:
    points = max(5, (len(tg) - 1) // LATEST_SHARE + 1)
    first = len(tg) - points
    log_t, log_q = np.log(tg[first:]), np.log(qg[first:])
    latest = line(log_t, log_q)
    half = points // 2
    return {"slope": latest["slope"], "first": first, "points": points, "rms": latest["rms"],
            "moves": line(log_t[half:], log_q[half:])["slope"] - line(log_t[:half + 1], log_q[:half + 1])["slope"]}


def _latest_slope_of(t: np.ndarray, p0: np.ndarray, n_component: int) -> float | None:
    found = _return_grid(t, p0, n_component)
    if found is None or len(found[1]) < 6:
        return None
    return float(_latest_slope(found[1], found[2])["slope"])


PROBE_BOOTSTRAP_REPLICATES = 100
PROBE_BOOTSTRAP_SEED = 627


def _probe_bootstrap_se(ret: dict, n_component: int) -> dict | None:
    per_probe = ret.get("p0_per_probe")
    if per_probe is None:
        return None
    per_probe = np.asarray(per_probe, dtype=float)
    probes = per_probe.shape[0]
    if probes < 8:
        return None
    t = np.asarray(ret["t"], dtype=float)
    stream = np.random.default_rng(PROBE_BOOTSTRAP_SEED)
    slopes = []
    for _ in range(PROBE_BOOTSTRAP_REPLICATES):
        slope = _latest_slope_of(t, per_probe[stream.integers(0, probes, probes)].mean(axis=0), n_component)
        if slope is not None and math.isfinite(slope):
            slopes.append(slope)
    if len(slopes) < PROBE_BOOTSTRAP_REPLICATES // 2:
        return None
    return {"method": "bootstrap over probes", "probes": int(probes), "replicates": int(len(slopes)),
            "slope_se": float(np.std(np.asarray(slopes, dtype=float), ddof=1))}


NO_USABLE_TIMES = {"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW",
                   "reason": "no diffusive window: excess return probability reaches "
                             "the mixing floor before a usable range of times"}
TOO_FEW_TIMES = {"valid": False, "refusal": "WINDOW_TOO_SHORT",
                 "reason": "diffusive window too short for a slope plateau"}


def _refusal_of_the_flattest_stretch(ret: dict, n_component: int) -> dict | None:
    t = np.asarray(ret["t"], dtype=float)
    found = _return_grid(t, np.asarray(ret["p0"], dtype=float) - 1.0 / max(2, n_component), n_component)
    if found is None:
        return dict(NO_USABLE_TIMES)
    _picked, tg, qg = found
    if len(tg) < 6:
        return dict(TOO_FEW_TIMES)
    log_steps = np.log(tg[1:] / tg[:-1])
    local = np.log(qg[1:] / qg[:-1]) / log_steps
    width = max(4, len(local) // 3)
    best_lo, best_var = 0, float("inf")
    for lo in range(0, len(local) - width + 1):
        var = float(np.var(local[lo:lo + width]))
        if var < best_var:
            best_lo, best_var = lo, var
    slope = float(np.median(local[best_lo:best_lo + width]))
    hi = min(best_lo + width, len(tg) - 1)
    window = {"t_lo": int(tg[best_lo]), "t_hi": int(tg[hi]), "points": int(width), "plateau_variance": best_var}

    evidence = diffusive_window_evidence(tg[best_lo:hi + 1], qg[best_lo:hi + 1])
    window["diffusive_window_evidence"] = evidence
    if evidence.get("comparable") and not evidence["is_power_law"]:
        delta = evidence["delta_aicc"]
        verdict = (f"is better described by spectral-gap decay than by a power law (delta AICc "
                   f"{delta:+.1f})" if delta <= 0 else
                   f"fits a power law better than spectral-gap decay, but by only {delta:.1f} in AICc, "
                   f"under the {DIFFUSIVE_WINDOW_MIN_DELTA_AICC:g} a dimension needs")
        return {"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW",
                "reason": ("no diffusive window: over the flattest available range "
                           f"t={window['t_lo']}..{window['t_hi']} the excess return "
                           f"probability {verdict}; the slope that would have been reported "
                           "is withheld as a possible mixing rate"),
                "diffusive_window_evidence": evidence,
                "would_have_reported": -2.0 * slope,
                "window": window}

    return None


def fit_ds(ret: dict, n_component: int) -> dict:
    refused = _refusal_of_the_flattest_stretch(ret, n_component)
    return refused if refused is not None else _fit_the_latest_stretch(ret, n_component)


def _fit_the_latest_stretch(ret: dict, n_component: int) -> dict:
    t = np.asarray(ret["t"], dtype=float)
    q0 = np.asarray(ret["p0"], dtype=float)
    q0_se = np.asarray(ret.get("p0_se") or np.zeros_like(q0), dtype=float)
    found = _return_grid(t, q0, n_component)
    if found is None:
        return dict(NO_USABLE_TIMES)
    picked, tg, qg = found
    if len(tg) < 6:
        return dict(TOO_FEW_TIMES)
    qseg = q0_se[picked]
    log_steps = np.log(tg[1:] / tg[:-1])
    local = np.log(qg[1:] / qg[:-1]) / log_steps
    local_probe_se = (np.sqrt((qseg[1:] / np.maximum(qg[1:], 1e-12)) ** 2
                              + (qseg[:-1] / np.maximum(qg[:-1], 1e-12)) ** 2)
                      / np.maximum(np.abs(log_steps), 1e-12))
    latest = _latest_slope(tg, qg)
    best_lo = latest["first"]
    slope = float(latest["slope"])
    centred = np.log(tg[best_lo:]) - np.log(tg[best_lo:]).mean()
    plateau_se = float(latest["rms"] * math.sqrt(latest["points"] / max(1, latest["points"] - 2))
                       / math.sqrt(float(np.sum(centred ** 2))))
    probe_se = float(np.median(local_probe_se[best_lo:]))
    probe_error = _probe_bootstrap_se(ret, n_component)
    se = math.sqrt(plateau_se ** 2 + probe_se ** 2)
    measured_se = (math.sqrt(plateau_se ** 2 + probe_error["slope_se"] ** 2)
                   if probe_error is not None else None)
    hi = len(tg) - 1
    drift = float(-2.0 * latest["moves"])
    window = {"t_lo": int(tg[best_lo]), "t_hi": int(tg[hi]), "points": int(latest["points"]),
              "moves_across_it": drift}
    if probe_error is not None:
        window["probe_error"] = probe_error

    evidence = diffusive_window_evidence(tg[best_lo:hi + 1], qg[best_lo:hi + 1])
    window["diffusive_window_evidence"] = evidence
    if evidence.get("comparable") and not evidence["is_power_law"]:
        delta = evidence["delta_aicc"]
        verdict = (f"is better described by spectral-gap decay than by a power law (delta AICc "
                   f"{delta:+.1f})" if delta <= 0 else
                   f"fits a power law better than spectral-gap decay, but by only {delta:.1f} in AICc, "
                   f"under the {DIFFUSIVE_WINDOW_MIN_DELTA_AICC:g} a dimension needs")
        return {"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW",
                "reason": ("no diffusive window: over the latest range "
                           f"t={window['t_lo']}..{window['t_hi']} the excess return "
                           f"probability {verdict}; the slope that would have been reported "
                           "is withheld as a possible mixing rate"),
                "diffusive_window_evidence": evidence,
                "would_have_reported": -2.0 * slope,
                "window": window}

    settled_within = NOT_SETTLED_SHARE * abs(2.0 * slope) + 2.0 * 2.0 * (se if measured_se is None else measured_se)
    if abs(drift) > settled_within:
        return {"valid": False, "refusal": "NOT_SETTLED",
                "reason": (f"the running slope still moves: over t={window['t_lo']}..{window['t_hi']} it reads "
                           f"{-2.0 * slope:.2f} and moves by {drift:+.2f} from its first half to its second, more "
                           f"than the {settled_within:.2f} a settled reading may"),
                "would_have_reported": -2.0 * slope, "window": window}
    out = {"valid": True, "d_s": -2.0 * slope, "se": 2.0 * (se if measured_se is None else measured_se),
           "se_method": "the analytic bound" if measured_se is None else "bootstrap over probes",
           "analytic_se": 2.0 * se,
           "window": window,
           "local_slopes": [float(v) for v in local]}
    if measured_se is not None:
        out["measured_se"] = 2.0 * measured_se
    return out


def graph_structure_metrics(adj, component: np.ndarray) -> dict:
    n = len(adj)
    edge_count = sum(len(row) for row in adj) // 2
    seen = set()
    components = 0
    for start in range(n):
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            for other in adj[node]:
                other = int(other)
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
    global_cycle_rank = max(0, edge_count - n + components)
    component_set = {int(v) for v in component}
    component_edges = sum(sum(1 for other in adj[v] if int(other) in component_set)
                          for v in component_set) // 2
    component_cycle_rank = max(0, component_edges - len(component_set) + (1 if component_set else 0))
    degrees = {v: sum(1 for other in adj[v] if int(other) in component_set) for v in component_set}
    queue = deque(v for v, degree in degrees.items() if degree < 2)
    removed = set(queue)
    while queue:
        v = queue.popleft()
        for other in adj[v]:
            other = int(other)
            if other in degrees and other not in removed:
                degrees[other] -= 1
                if degrees[other] < 2:
                    removed.add(other)
                    queue.append(other)
    two_core_size = len(component_set) - len(removed)
    return {"component_count": components, "cycle_rank": global_cycle_rank,
            "largest_component_edges": component_edges,
            "largest_component_cycle_rank": component_cycle_rank,
            "two_core_size": two_core_size,
            "two_core_fraction": two_core_size / max(1, len(component_set))}


def _would_have_reported(found: dict, key: str) -> dict:
    value = found.get(key) if found.get("valid") else found.get("would_have_reported")
    return {} if value is None else {"would_have_reported": value}


def streams_of(rng: np.random.Generator, count: int) -> list:
    return [np.random.default_rng(child)
            for child in np.random.SeedSequence(int(rng.integers(0, 2 ** 63 - 1))).spawn(count)]


def _refused_for_its_balls(found: dict, key: str, growth: str) -> dict:
    if growth not in NOT_CLEARLY_A_POWER:
        return found
    refusal, why = NOT_CLEARLY_A_POWER[growth]
    return {"valid": False, "refusal": refusal, "reason": f"{why}, by the ball probe's verdict",
            **_would_have_reported(found, key)}


def _measure_geometry(adj, component, rng, mean_ball, timed=None, growth: str = POWER,
                      settled_from: int = 1) -> dict:
    from graph_scale_dynamics.measurements.box_covering import box_covering_profile, fit_box_dimension
    from graph_scale_dynamics.measurements.walk_dimension import fit_walk_dimension, walk_displacement_profile

    for_the_boxes, for_the_walks = streams_of(rng, 2)
    _timed_geometry = timed if timed is not None else (lambda _label, call: call())
    profiles: dict = {}

    def _box():
        profiles["box_covering"] = box_covering_profile(adj, component, for_the_boxes, mean_ball,
                                                        settled_from=settled_from)
        return fit_box_dimension(profiles["box_covering"])

    def _walk():
        profiles["walk_displacement"] = walk_displacement_profile(adj, component, for_the_walks, keep_sources=True)
        found = fit_walk_dimension(profiles["walk_displacement"], settled_from=settled_from)
        profiles["walk_displacement"].pop("source_squares", None)
        return found

    box = _refused_for_its_balls(_timed_geometry("d_B", _box), "box_covering_exponent", growth)
    walk = _refused_for_its_balls(_timed_geometry("d_w", _walk), "walk_dimension", growth)
    return {
        "_geometry_curves": profiles,
        "d_B": ({"valid": True, "d_B": box["box_covering_exponent"], "se": box.get("se"),
                 "power_law_preferred": box.get("power_law_preferred")}
                if box.get("valid") and box.get("power_law_preferred")
                else {"valid": False, "refusal": box.get("refusal") or "NOT_POWER_LAW",
                      "reason": box.get("reason") or "box counts are not power-law in radius",
                      **_would_have_reported(box, "box_covering_exponent")}),
        "d_w": ({"valid": True, "d_w": walk["walk_dimension"], "se": walk.get("se"),
                 "subdiffusive": walk.get("subdiffusive")}
                if walk.get("valid")
                else {"valid": False, "refusal": walk.get("refusal") or "NOT_POWER_LAW",
                      "reason": walk.get("reason") or "walk displacement is not power-law in time",
                      **_would_have_reported(walk, "walk_dimension")}),
    }


def _measure_graph(n: int, edges, rng, *, measure_geometry: bool = False) -> tuple[dict, dict]:
    adj = build_adjacency(n, edges)
    component = largest_component(n, adj)
    result: dict = {"component": len(component)}
    curves: dict = {}
    timings: dict = {}

    def _timed(label, call):
        start = time.perf_counter()
        try:
            return call()
        finally:
            timings[label] = round(timings.get(label, 0.0) + time.perf_counter() - start, 6)

    result["probe_seconds"] = timings
    for_the_balls, for_the_returns, for_the_geometry = streams_of(rng, 3)
    if len(component) >= 16:
        volume = _timed("d_V", lambda: volume_growth(adj, component, for_the_balls, keep_sources=True,
                                                     sources=sources_for_the_verdict(len(component))))
        curves["volume_growth"] = volume
        result["d_V"] = _timed("d_V", lambda: fit_dh(volume, len(component)))
        growth = result["d_V"]["volume_growth"]["verdict"]
        volume.pop("balls_per_source", None)
        ret = _timed("d_s", lambda: return_probability(adj, component, for_the_returns, keep_probes=True))
        curves["return_probability"] = ret
        result["d_s"] = _refused_for_its_balls(_timed("d_s", lambda: fit_ds(ret, len(component))), "d_s", growth)
        ret.pop("p0_per_probe", None)
        result["half_volume_radius"] = volume.get("half_volume_radius")
        result["half_volume_radius_se"] = volume.get("half_volume_radius_se")
        result["half_volume_radius_source_fraction"] = volume.get("half_volume_radius_source_fraction", 0.0)
        result["mean_distance"] = result["half_volume_radius"]
        result["diameter_lower_bound"] = volume.get("eccentricity_lower_bound")
        result["diameter_upper_bound"] = volume.get("diameter_upper_bound")
        result["distance_window_truncated"] = bool(volume.get("truncated"))
        diameter_upper = volume.get("diameter_upper_bound")
        result["log_diameter_flag"] = bool(
            diameter_upper is not None
            and diameter_upper <= 1.6 * math.log2(max(4, len(component)))
        )
        if measure_geometry:
            result.update(_measure_geometry(
                adj, component, for_the_geometry, volume["mean_ball"], timed=_timed, growth=growth,
                settled_from=int((result["d_V"].get("window") or {}).get("settled_from") or 1)))
            curves.update(result.pop("_geometry_curves", {}))
        result["small_world"] = bool(growth == EXPONENTIAL or (growth in (UNTESTED, UNDECIDED, UNEVEN, TOO_SMALL)
                                                               and result.get("log_diameter_flag")))
    else:
        result["d_V"] = {"valid": False, "refusal": "COMPONENT_BELOW_MEASURABLE_SIZE", "reason": "largest component below measurable size"}
        result["d_s"] = {"valid": False, "refusal": "COMPONENT_BELOW_MEASURABLE_SIZE", "reason": "largest component below measurable size"}
        result["log_diameter_flag"] = None
        if measure_geometry:
            below = {"valid": False, "refusal": "COMPONENT_BELOW_MEASURABLE_SIZE", "reason": "largest component below measurable size"}
            result["d_B"] = dict(below)
            result["d_w"] = dict(below)
    return result, curves
