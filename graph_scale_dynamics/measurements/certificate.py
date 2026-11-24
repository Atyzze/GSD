from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL


def integrated_autocorrelation_time(series: np.ndarray, window_factor: float = 5.0) -> float | None:
    series = np.asarray(series, dtype=float)
    length = len(series)
    if length < 8:
        return None
    centered = series - series.mean()
    variance = float(np.dot(centered, centered)) / length
    if variance <= 0 or not math.isfinite(variance):
        return None
    tau = 1.0
    for lag in range(1, length // 2):
        rho = float(np.dot(centered[:-lag], centered[lag:])) / ((length - lag) * variance)
        tau += 2.0 * rho
        if lag >= window_factor * tau:
            break
    return max(tau, 1.0)


def _last_chunk(envelope: dict, trajectory: list) -> list:
    start = int(envelope.get("continued_from_sweeps") or 0) * int(envelope.get("n") or 0)
    if start <= 0:
        return trajectory
    own = [row for row in trajectory if float(row.get("move") or 0) >= start]
    return own if len(own) >= 10 else trajectory


BATCH_MEANS_BATCHES = 8


def batch_means_samples(late, batches: int = BATCH_MEANS_BATCHES) -> float | None:
    late = np.asarray(late, dtype=float)
    size = len(late) // batches
    if size < 2 or batches < 2:
        return None
    used = late[len(late) - size * batches:]
    spread = float(used.var(ddof=1))
    if not np.isfinite(spread) or spread <= 0:
        return None
    means = used.reshape(batches, size).mean(axis=1)
    return len(used) / max(1.0, size * float(means.var(ddof=1)) / spread)


LATE_SHARE = 0.70
FROZEN_LATE_CHANGES_PER_NODE = 0.05
FROZEN_EDGES_KEPT = 0.999
SPLIT_MIN_VALUES = 8


def own_count(envelope: dict, name: str) -> dict | None:
    trajectory = CL.trajectory(envelope, name)
    if len(trajectory) < 10:
        return None
    n = envelope["n"]
    trajectory = _last_chunk(envelope, trajectory)
    late = trajectory[int(len(trajectory) * 0.4):]
    tau_observable = "energy"
    tau_points = integrated_autocorrelation_time([row["energy"] for row in late])
    if tau_points is None:
        for fallback_key in ("configuration_probe", "configuration_overlap"):
            values = [row.get(fallback_key) for row in late]
            if all(isinstance(value, (int, float)) and math.isfinite(float(value))
                   for value in values):
                candidate_tau = integrated_autocorrelation_time(values)
                if candidate_tau is not None:
                    tau_points = candidate_tau
                    tau_observable = fallback_key
                    break
    tau_sweeps = None
    effective_samples = None
    if tau_points is not None:
        moves_per_point = max(1.0, (late[-1]["move"] - late[0]["move"]) / max(1, len(late) - 1))
        tau_sweeps = tau_points * moves_per_point / n
        effective_samples = float(len(late) / tau_points)
    counted = None
    if effective_samples is not None:
        by_batches = batch_means_samples([row[tau_observable] for row in late])
        counted = {"windowed": effective_samples, "batch_means": by_batches, "batches": BATCH_MEANS_BATCHES}
        if by_batches is not None:
            effective_samples = min(effective_samples, float(by_batches))
    return {"tau_int_sweeps": tau_sweeps, "effective_samples": effective_samples,
            **({"effective_samples_counted": counted} if counted is not None else {}),
            "autocorrelation_observable": tau_observable if tau_points is not None else None}


DRIFT_MAX_LAG_ONE = 0.8
ROUNDING = 1e-9


def within_rounding(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= ROUNDING * max(1.0, abs(float(a)), abs(float(b)))


def widened_line(moves, values, max_lag_one: float = DRIFT_MAX_LAG_ONE) -> dict | None:
    t, y = np.asarray(moves, dtype=float), np.asarray(values, dtype=float)
    if len(t) < 3:
        return None
    centred = t - t.mean()
    sxx = float(centred @ centred)
    if not sxx > 0.0:
        return None
    slope = float(centred @ (y - y.mean())) / sxx
    window = float(t[-1] - t[0])
    drift = slope * window
    residuals = y - y.mean() - slope * centred
    squares = float(residuals @ residuals)
    lag_one = min(max_lag_one, max(0.0, float(residuals[:-1] @ residuals[1:]) / squares)) if squares > 0 else 0.0
    se = window * math.sqrt(squares / (len(y) - 2) / sxx) * math.sqrt((1.0 + lag_one) / (1.0 - lag_one))
    scale = max(1.0, float(np.max(np.abs(y))))
    if abs(drift) <= ROUNDING * scale:
        drift = 0.0
    se = max(se, ROUNDING * scale)
    return {"slope": slope, "drift": drift, "drift_se": se, "lag_one": lag_one, "z": abs(drift) / se}


def own_drift(envelope: dict, name: str) -> dict | None:
    trajectory = CL.trajectory(envelope, name)
    if len(trajectory) < 10:
        return None
    tail = trajectory[int(len(trajectory) * LATE_SHARE):]
    line = widened_line([row["move"] for row in tail], [row["energy"] for row in tail])
    if line is None:
        return None
    return {"late_energy_slope_per_move": line["slope"], "late_energy_drift": line["drift"],
            "late_energy_drift_se": line["drift_se"],
            "normalized_drift": math.copysign(line["z"], line["drift"])}


def own_activity(envelope: dict, name: str) -> dict:
    from graph_scale_dynamics.engine.engine import late_edge_overlap
    n = max(1, int(envelope["n"]))
    trajectory = CL.trajectory(envelope, name)
    accepted_total = (CL.record(envelope, name).get("acceptance") or {}).get("accepted") or {}
    cumulative = sum(int(accepted_total.get(key, 0)) for key in ("add", "delete", "swap"))
    late_changes = None
    if len(trajectory) >= 2:
        tail = trajectory[int(len(trajectory) * LATE_SHARE):] or trajectory
        first, last = tail[0], tail[-1]
        late_changes = sum(int(last.get(f"accepted_{key}", 0)) - int(first.get(f"accepted_{key}", 0))
                           for key in ("add", "delete", "swap")) / n
    overlap = late_edge_overlap(CL.block(envelope, name).get("late_change"), len(CL.edges(envelope, name)))
    frozen = (None if late_changes is None or overlap is None
              else late_changes <= FROZEN_LATE_CHANGES_PER_NODE and overlap >= FROZEN_EDGES_KEPT)
    return {"accepted_topology_changes_per_node_late": late_changes,
            "accepted_topology_changes_per_node_cumulative": cumulative / n,
            "late_edge_jaccard": overlap, "frozen": frozen}


def own_certificate(envelope: dict, name: str) -> dict:
    return {**(own_count(envelope, name) or {"tau_int_sweeps": None, "effective_samples": None,
                                             "autocorrelation_observable": None}),
            "stationarity": own_drift(envelope, name), "activity": own_activity(envelope, name)}


def pair_name(a: str, b: str) -> str:
    return f"{a}|{b}"


def pair_split(envelope: dict, a: str, b: str) -> dict | None:
    n = envelope["n"]
    sides = []
    for name in (a, b):
        whole = CL.trajectory(envelope, name)
        sides.append(whole[-max(3, len(whole) // 3):])
    split = {}
    for key, extract in (("energy_per_node", lambda r: r["energy"] / n), ("mean_degree", lambda r: r["mean_degree"])):
        first, second = (np.asarray([extract(r) for r in rows], dtype=float) for rows in sides)
        if len(first) < SPLIT_MIN_VALUES or len(second) < SPLIT_MIN_VALUES:
            continue
        tau_a = integrated_autocorrelation_time(first) or 1.0
        tau_b = integrated_autocorrelation_time(second) or 1.0
        var_a = float(first.var(ddof=1)) if len(first) > 1 else 0.0
        var_b = float(second.var(ddof=1)) if len(second) > 1 else 0.0
        a, b = float(first.mean()), float(second.mean())
        rounding = ROUNDING * max(1.0, abs(a), abs(b))
        mean_se = max(math.sqrt(var_a / max(1.0, len(first) / tau_a) + var_b / max(1.0, len(second) / tau_b)), rounding)
        split[f"{key}_z"] = (0.0 if within_rounding(a, b) else abs(a - b)) / mean_se
    return split or None


def pair_structure(envelope: dict, a: str, b: str) -> dict | None:
    n = max(1, int(envelope["n"]))
    first, second = (CL.record(envelope, name).get("final_structure") for name in (a, b))
    if not isinstance(first, dict) or not isinstance(second, dict):
        return None
    out = {}
    for key in ("connected_fraction", "two_core_fraction", "largest_component_cycle_rank_density"):
        x, y = first.get(key), second.get(key)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            out[key] = abs(float(x) - float(y))
    x, y = first.get("component_count"), second.get("component_count")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        out["component_count_per_node"] = abs(float(x) - float(y)) / n
    return out


def pair_certificate(envelope: dict, a: str, b: str) -> dict:
    structural = pair_structure(envelope, a, b)
    return {"chains": [a, b], "split": pair_split(envelope, a, b), "split_method": "correlated_mean_uncertainty",
            "structural_split": structural,
            "structural_noise": structural_noise(envelope, a, b) if structural else None}


def _worst(rows, key: str, pick) -> dict | None:
    found = [row.get(key) for row in rows if isinstance(row.get(key), dict)]
    if not found:
        return None
    keys = sorted({k for block in found for k in block})
    out = {}
    for k in keys:
        values = [float(block[k]) for block in found if isinstance(block.get(k), (int, float))]
        out[k] = pick(values) if values else None
    return out


def equilibration_certificate(envelope: dict, decide: list[str] | None = None,
                              meet: list[str] | None = None) -> dict | None:
    decide = list(decide) if decide is not None else CL.ran_names(envelope)
    meet = [name for name in (meet if meet is not None else decide) if name in decide]
    if len(CL.trajectory(envelope, decide[0] if decide else CL.FROM_EMPTY)) < 10:
        return None
    chains = {name: own_certificate(envelope, name) for name in decide}
    pairs = {pair_name(a, b): pair_certificate(envelope, a, b)
             for index, a in enumerate(meet) for b in meet[index + 1:]}
    counted = [(chains[name]["effective_samples"], name) for name in decide
               if chains[name].get("effective_samples") is not None]
    fewest = min(counted)[1] if len(counted) == len(decide) and counted else None
    taus = [chains[name]["tau_int_sweeps"] for name in decide]
    least = chains[fewest] if fewest is not None else {}
    return {"contract": EVERY_CHAIN_CERTIFICATE, "decide": list(decide), "meet": list(meet),
            "chains": chains, "pairs": pairs,
            "tau_int_sweeps": max(taus) if taus and all(t is not None for t in taus) else None,
            "effective_samples": least.get("effective_samples"),
            **({"effective_samples_counted": least["effective_samples_counted"]}
               if least.get("effective_samples_counted") else {}),
            "autocorrelation_observable": least.get("autocorrelation_observable"),
            "fewest_samples": fewest,
            "split": _worst(list(pairs.values()), "split", max),
            "split_method": "correlated_mean_uncertainty" if pairs else None,
            "structural_split": _worst(list(pairs.values()), "structural_split", max),
            "structural_noise": _worst(list(pairs.values()), "structural_noise", min),
            "sweeps": envelope.get("sweeps"),
            "sweeps_multiplier": envelope.get("sweeps_multiplier", 1),
            "screen_name": "thermalization_screen_v3"}


EVERY_CHAIN_CERTIFICATE = "every-chain-certificate-2"


STRUCTURAL_NOISE_MIN_DOF = 2
_TRAJECTORY_STRUCTURE = {
    "connected_fraction": lambda row, n: row["largest_component"] / n,
    "component_count_per_node": lambda row, n: row["components"] / n,
}


def structural_noise(envelope: dict, a: str, b: str) -> dict:
    n = max(1, int(envelope.get("n") or 1))
    chains = [CL.trajectory(envelope, a), CL.trajectory(envelope, b)]
    out: dict = {}
    for key, extract in _TRAJECTORY_STRUCTURE.items():
        squares, dof = 0.0, 0
        for rows in chains:
            late = rows[int(len(rows) * 0.4):]
            values = [float(extract(row, n)) for row in late
                      if isinstance(row.get("largest_component"), (int, float))
                      and isinstance(row.get("components"), (int, float))]
            if len(values) >= 2:
                mean = sum(values) / len(values)
                squares += sum((v - mean) ** 2 for v in values)
                dof += len(values) - 1
        out[key] = (math.sqrt(2.0 * squares / dof) if dof >= STRUCTURAL_NOISE_MIN_DOF else None)
    return out
