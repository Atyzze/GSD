from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.domain.randomness import derive_seed
from graph_scale_dynamics.measurements.estimators import (
    _measure_graph, build_adjacency, graph_structure_metrics, largest_component)
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION, PROBE_STREAM

CLUSTERING_MAX_N = 262144


def select_best_runs(measurements: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for measurement in measurements:
        metrics = measurement.get("metrics", measurement)
        multiplier = ((metrics.get("health") or {}).get("equilibration") or {})             .get("sweeps_multiplier", 1)
        key = (measurement.get("n", metrics.get("health", {}).get("n")), measurement.get("seed"))
        current = best.get(key)
        if current is None or multiplier >= current[0]:
            best[key] = (multiplier, measurement)
    return [pair[1] for pair in best.values()]


def health_metrics(envelope: dict, adj, component: np.ndarray) -> dict:
    from graph_scale_dynamics.scaleflow.equilibration import chains_health
    n = envelope["n"]
    from_empty = CL.record(envelope, CL.FROM_EMPTY)
    final = from_empty["final"]
    acceptance = (from_empty.get("acceptance") or {}).get("rate", {})
    proposal_model = envelope.get("proposal_model") or {}
    proposal_locality = float(proposal_model.get("proposal_locality", 0.0) or 0.0)
    sampler = {
        "kernel": proposal_model.get("kernel", "canonical_global_add_delete_swap"),
        "proposal_locality": proposal_locality,
        "sampler_audit": proposal_locality > 0.0,
    }
    density = final["edge_count"] / max(1, n * (n - 1) / 2)
    structure = graph_structure_metrics(adj, component)
    degree_square_sum = (final.get("ledgers") or {}).get("degree_square_sum")
    second_moment = (float(degree_square_sum) / n
                     if degree_square_sum is not None else None)
    mean_degree = final["mean_degree"]
    heterogeneity = (second_moment / (mean_degree * mean_degree)
                     if second_moment is not None and mean_degree else None)

    clustering = None
    if n <= CLUSTERING_MAX_N:
        adjacency_sets = [set(int(v) for v in row) for row in adj]
        wedges = sum(len(row) * (len(row) - 1) / 2 for row in adjacency_sets)
        if wedges > 0:
            edge_common_sum = 0
            for u, neighbors in enumerate(adjacency_sets):
                for v in neighbors:
                    if v > u:
                        edge_common_sum += len(neighbors & adjacency_sets[v])
            clustering = float(edge_common_sum / wedges)
    numerics_ok = all(math.isfinite(v) for v in (final["energy"], final["mean_degree"]))
    rung = chains_health(envelope, None, numerics_ok)
    return {
        "n": n, "edge_count": final["edge_count"], "mean_degree": final["mean_degree"],
        "max_degree": final["max_degree"], "isolated_fraction": final.get("isolated_vertices", 0) / n,
        "density": density, "connected_fraction": len(component) / n,
        "degree_second_moment": second_moment, "degree_heterogeneity": heterogeneity,
        **structure,
        "acceptance_add": acceptance.get("add"), "acceptance_delete": acceptance.get("delete"),
        "acceptance_swap": acceptance.get("swap"),
        "activity": rung["activity"], "clustering": clustering, "sampler": sampler,
        "stationarity": rung["stationarity"],
        "sweeps": envelope.get("sweeps"),
        "sweeps_multiplier": int(envelope.get("sweeps_multiplier", 1)),
        "equilibration": rung["equilibration"],
        "numerics_ok": numerics_ok,
    }


def _a_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _one_configuration(values: list[float], read: int) -> dict:
    return {"k": 1, "valid_k": int(read), **({"independence_certified": False, "spread": 0.0,
                                               "values": [round(value, 4) for value in values]} if read else {})}


def _of_the_last_state(read: dict, key: str) -> dict:
    out = dict(read)
    if not read.get("valid"):
        out["snapshots"] = _one_configuration([], 0)
        return out
    value, error = float(read[key]), float(read.get("se") or 0.0)
    out[key] = value
    out["se"] = float(math.sqrt(error * error))
    measured = read.get("measured_se")
    if _a_number(measured):
        out["measured_se"] = float(math.sqrt(float(measured) * float(measured)))
    out["snapshots"] = _one_configuration([value], 1)
    return out


def analyze_envelope(envelope: dict, *, seed: int = 0) -> tuple[dict, dict]:
    n = envelope["n"]
    rng = np.random.default_rng(
        derive_seed("analysis-estimators", PROBE_STREAM, int(seed), int(n))
        % (2 ** 63))
    edges = CL.edges(envelope, CL.FROM_EMPTY)
    adj = build_adjacency(n, edges)
    component = largest_component(n, adj)
    health = health_metrics(envelope, adj, component)
    final, final_curves = _measure_graph(n, edges, rng, measure_geometry=True)
    curves = dict(final_curves)
    curves["configurations"] = [{"move": "final", "curves": final_curves}]
    probe_seconds = {label: round(seconds, 6) for label, seconds in (final.get("probe_seconds") or {}).items()}
    metrics: dict = {"analysis_version": ANALYSIS_VERSION, "health": health,
                     "probe_seconds": probe_seconds,
                     "probe_seconds_snapshots": 1,
                     "d_V": _of_the_last_state(final["d_V"], "d_V_window"),
                     "d_s": _of_the_last_state(final["d_s"], "d_s"),
                     "log_diameter_flag": final.get("log_diameter_flag")}
    if "d_B" in final and "d_w" in final:
        metrics["d_B"] = _of_the_last_state(final["d_B"], "d_B")
        metrics["d_w"] = _of_the_last_state(final["d_w"], "d_w")
        metrics["geometry_snapshot_mode"] = "final_state_only"
    else:
        absent = {"valid": False, "refusal": "NOT_MEASURED", "reason": "geometry channels not measured"}
        metrics["d_B"] = dict(absent)
        metrics["d_w"] = dict(absent)
        metrics["geometry_snapshot_mode"] = "not_measured"
    small_world = bool(final.get("small_world"))
    metrics["snapshot_selection"] = {"contract": "final-chunk-2", "configurations": 1}
    metrics["small_world"] = {"flag": small_world, "configurations": 1, "flagged": int(small_world)}
    for probe in ("d_V", "d_s", "d_B", "d_w"):
        if isinstance(metrics.get(probe), dict):
            metrics[probe]["small_world"] = small_world
    if _a_number(final.get("half_volume_radius")):
        half = float(final["half_volume_radius"])
        error = final.get("half_volume_radius_se")
        error = float(error) if _a_number(error) else 0.0
        fraction = final.get("half_volume_radius_source_fraction")
        metrics["half_volume_radius"] = half
        metrics["half_volume_radius_se"] = float(math.sqrt(error * error))
        metrics["half_volume_radius_snapshots"] = _one_configuration([half], 1)
        metrics["half_volume_radius_source_fraction"] = float(fraction) if _a_number(fraction) else None
        metrics["mean_distance"] = half
        metrics["diameter_lower_bound"] = final.get("diameter_lower_bound")
        metrics["diameter_upper_bound"] = final.get("diameter_upper_bound")
        metrics["distance_window_truncated"] = final.get("distance_window_truncated", False)
    return metrics, curves
