from __future__ import annotations

from graph_scale_dynamics.scheduling.base_block import base_sizes
from graph_scale_dynamics.scaleflow.equilibration import CHAINS_DISAGREED_CODES, certificate_pass as _b143_certificate_pass, failure_codes, activity_label as _b143_activity_label


SPECTRAL_NULL_MIN_TRAILING_RUNGS = 3

STRUCTURAL_SUBSTRATE_CONTRACT = "structural-substrate-maturity-1"


def _b143_terminal_at_ceiling(policy: dict, health: dict, failures: list[dict]) -> str:
    from graph_scale_dynamics.scaleflow.equilibration import terminal_at_ceiling
    return terminal_at_ceiling(health, failures)

def _b143_rung_sampling_state(campaign_spec: dict, n: int, summary: dict,
                              measurement_history: list[dict]) -> dict:
    policy = campaign_spec.get("policy") or {}
    if str(summary.get("rung_terminal_classification") or "").startswith("OPERATIONAL_"):
        return {"terminal": True, "classification": summary["rung_terminal_classification"],
                "history": [], "current_multiplier": None}
    rows = [m for m in measurement_history if int((m.get("health") or {}).get("n") or -1) == int(n)]

    def _multiplier(metrics: dict) -> int:
        health = metrics.get("health") or {}
        cert = health.get("equilibration") or {}
        return int(cert.get("sweeps_multiplier", health.get("sweeps_multiplier", 1)))

    rows.sort(key=_multiplier)
    if not rows:
        stored = summary.get("rung_terminal_classification")
        if stored:
            return {"terminal": True, "classification": str(stored), "history": [],
                    "current_multiplier": summary.get("sweeps_multiplier")}
        return {"terminal": True, "classification": "OPERATIONAL_UNRESOLVED",
                "history": [], "current_multiplier": None}

    recorded = [(m.get("health") or {}) for m in rows if (m.get("health") or {}).get("rung_terminal")]
    if recorded:
        def _rank(health: dict) -> int:
            reason = str((health.get("rung_terminal") or {}).get("reason") or "")
            return {"mean_degree_cap": 0, "budget": 1, "ceiling": 2, "completed": 3}.get(reason, 2)
        recorded.sort(key=_rank)
        worst = recorded[0]
        terminal = worst["rung_terminal"]
        checkpoints = []
        for row in (worst.get("sampling_checkpoints") or []):
            checkpoints.append({"multiplier": int(row.get("multiplier") or 1),
                                "passed": bool(row.get("passed")),
                                "failures": list(row.get("failures") or []),
                                "health": worst})
        return {"terminal": True, "classification": str(terminal.get("classification")),
                "history": checkpoints,
                "current_multiplier": int(terminal.get("final_multiplier") or _multiplier({"health": worst})),
                "failures": list(terminal.get("failures") or []),
                "one_shot": {k: terminal.get(k) for k in ("reason", "chunks", "wall_seconds",
                                                          "budget_seconds", "mean_degree_cap")}}

    checkpoints = []
    for metrics in rows:
        health = metrics.get("health") or {}
        cert = health.get("equilibration") or {}
        multiplier = int(cert.get("sweeps_multiplier", health.get("sweeps_multiplier", 1)))
        passed, failures = _b143_certificate_pass(policy, health)
        checkpoints.append({"multiplier": multiplier, "passed": passed,
                            "failures": failures, "health": health})
    by_multiplier = {row["multiplier"]: row for row in checkpoints}
    checkpoints = [by_multiplier[key] for key in sorted(by_multiplier)]
    current = checkpoints[-1]
    required_passes = max(1, int((campaign_spec.get("sampling_contract") or {})
                                 .get("required_consecutive_passes", 2)))
    consecutive = 0
    for row in reversed(checkpoints):
        if row["passed"]:
            consecutive += 1
        else:
            break
    if consecutive >= required_passes:
        return {"terminal": True, "classification": _b143_activity_label(current["health"]),
                "history": checkpoints, "current_multiplier": current["multiplier"]}
    return {"terminal": True,
            "classification": _b143_terminal_at_ceiling(policy, current["health"], current["failures"]),
            "history": checkpoints, "current_multiplier": current["multiplier"],
            "failures": current["failures"]}

def _mean(summary: dict, key: str):
    node = summary.get(key)
    if isinstance(node, dict):
        value = node.get("mean")
        return float(value) if isinstance(value, (int, float)) else None
    return None

def _with_measured(entry: dict, summary: dict, probe: str) -> None:
    value = summary.get(f"{probe}_measured_se")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        entry["measured_se"] = float(value)


def _with_small_world(cell: dict, summary: dict) -> None:
    value = summary.get("small_world_fraction")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell["small_world_fraction"] = float(value)


def _rung_cell(campaign_spec: dict, n: int, summary: dict, state: dict) -> dict:
    from graph_scale_dynamics.scaleflow.probes import PROBES, bucket_for_rung
    from graph_scale_dynamics.scheduling.limits import connectivity_floor as _limits_floor
    _CHAINS_DISAGREED = CHAINS_DISAGREED_CODES
    _conn_floor = _limits_floor(campaign_spec)
    history = state.get("history") or []
    health = (history[-1].get("health") if history else {}) or {}
    activity = health.get("activity") or {}
    radius = _mean(summary, "half_volume_radius")
    connected = _mean(summary, "connected_fraction")
    two_core = _mean(summary, "two_core_fraction")
    clustering = _mean(summary, "clustering")
    heterogeneity = _mean(summary, "degree_heterogeneity")
    ds_no_window = float(summary.get("d_s_no_window_fraction") or 0.0)
    refusals = summary.get("probe_refusals") or {}
    terminal = state["classification"]
    chains_disagreed = bool(failure_codes(state.get("failures")) & _CHAINS_DISAGREED)
    chains_verdict_now = "CHAINS_DISAGREED" if chains_disagreed else None
    probes_at_n = {}
    for probe in PROBES:
        node = summary.get(probe) if isinstance(summary.get(probe), dict) else None
        value = _mean(summary, probe)
        se = node.get("se") if node else None
        valid_fraction = float(summary.get(f"{probe}_valid_fraction") or 0.0)
        codes = dict(refusals.get(probe) or {})
        entry = {"valid": value is not None}
        if value is None and codes:
            entry["refusal"] = max(sorted(codes), key=lambda c: codes[c])
        bucket = bucket_for_rung(
            entry if (value is not None or codes) else None,
            terminal_classification=terminal, chains_verdict=chains_verdict_now,
            connectivity_floor_failed=bool(connected is not None and float(connected) < _conn_floor),
        )
        probes_at_n[probe] = {
            "value": value, "se": float(se) if isinstance(se, (int, float)) else None,
            "valid_fraction": valid_fraction, "refusals": codes,
            "bucket": bucket.value if bucket is not None else None,
        }
        _with_measured(probes_at_n[probe], summary, probe)
    cell = {
        "n": n,
        "measurement_seed_count": int(summary.get("seeds") or 0),
        "cumulative_sweeps": health.get("sweeps"),
        "sweeps_multiplier": state.get("current_multiplier"),
        "rung_terminal_classification": terminal,
        "chains_verdict": chains_verdict_now,
        "certificate_failures": list(state.get("failures") or []),
        "iat_sweeps": ((health.get("equilibration") or {}).get("tau_int_sweeps")),
        "effective_samples": ((health.get("equilibration") or {}).get("effective_samples")),
        "stationarity_drift": ((health.get("stationarity") or {}).get("normalized_drift")),
        "chains_split": ((health.get("equilibration") or {}).get("split")),
        "structural_split": ((health.get("equilibration") or {}).get("structural_split")),
        "accepted_changes_per_node_late": activity.get("accepted_topology_changes_per_node_late"),
        "accepted_changes_per_node_cumulative": activity.get("accepted_topology_changes_per_node_cumulative"),
        "late_edge_jaccard": activity.get("late_edge_jaccard"),
        "edge_count": health.get("edge_count"),
        "mean_degree": _mean(summary, "mean_degree"),
        "giant_mean_degree": _mean(summary, "giant_mean_degree"),
        "max_degree": health.get("max_degree"),
        "isolated_fraction": health.get("isolated_fraction"),
        "density": _mean(summary, "density"),
        "degree_second_moment": health.get("degree_second_moment"),
        "degree_heterogeneity": heterogeneity,
        "component_count": health.get("component_count"),
        "cycle_rank": _mean(summary, "cycle_rank"),
        "largest_component_cycle_rank": _mean(summary, "largest_component_cycle_rank"),
        "two_core_fraction": two_core,
        "connected_fraction": connected,
        "half_volume_radius": radius,
        "clustering": clustering,
        "probes": probes_at_n,
        "d_s_no_window_fraction": ds_no_window,
        "withheld": summary.get("withheld") or {},
        "census": summary.get("census"),
        "log_diameter_unknown": summary.get("log_diameter_unknown"),
        "equilibration_structural_split": summary.get("equilibration_structural_split"),
        "couplings": summary.get("couplings"),
    }
    _with_small_world(cell, summary)
    for probe in PROBES:
        cell[probe] = probes_at_n[probe]["value"]
        cell[f"{probe}_valid_fraction"] = probes_at_n[probe]["valid_fraction"]
        cell[f"{probe}_bucket"] = probes_at_n[probe]["bucket"]
    return cell


def _build_four_rung_phenotype(campaign_spec: dict, summaries: dict[int, dict],
                               rung_states: dict[int, dict]) -> dict:
    from graph_scale_dynamics.scaleflow.probes import PROBES, bucket_for_rung
    _CHAINS_DISAGREED = CHAINS_DISAGREED_CODES

    per_n = {}
    probe_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    probe_se_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    probe_valid_fraction_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    probe_refusal_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    probe_bucket_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    radius_vector = []
    connected_vector = []
    two_core_vector = []
    clustering_vector = []
    heterogeneity_vector = []
    activity_vector = []
    equilibration_vector = []
    chains_verdict_vector = []
    no_window_vector = []
    from graph_scale_dynamics.scheduling.limits import connectivity_floor as _limits_floor
    _conn_floor = _limits_floor(campaign_spec)
    for n in base_sizes(campaign_spec):
        cell = _rung_cell(campaign_spec, n, summaries[n], rung_states[n])
        per_n[str(n)] = cell
        for probe in PROBES:
            probe_cell = cell["probes"][probe]
            probe_vectors[probe].append(probe_cell["value"])
            probe_se_vectors[probe].append(probe_cell["se"])
            probe_valid_fraction_vectors[probe].append(probe_cell["valid_fraction"])
            probe_refusal_vectors[probe].append(probe_cell["refusals"])
            probe_bucket_vectors[probe].append(probe_cell["bucket"])
        radius_vector.append(cell["half_volume_radius"])
        connected_vector.append(cell["connected_fraction"])
        two_core_vector.append(cell["two_core_fraction"])
        clustering_vector.append(cell["clustering"])
        heterogeneity_vector.append(cell["degree_heterogeneity"])
        activity_vector.append(cell["accepted_changes_per_node_late"])
        equilibration_vector.append(cell["rung_terminal_classification"])
        chains_verdict_vector.append(cell["chains_verdict"])
        no_window_vector.append(cell["d_s_no_window_fraction"] >= 1.0)
    ds_vector = probe_vectors["d_s"]
    recovered_ds_64 = ds_vector[0] is None and ds_vector[-1] is not None
    recovered_ds_64_256 = ds_vector[0] is None and ds_vector[1] is None and ds_vector[-1] is not None
    low_connected_recovery = (connected_vector[0] is not None and connected_vector[-1] is not None
                              and connected_vector[0] < 0.5 <= connected_vector[-1])
    low_activity_recovery = (isinstance(activity_vector[0], (int, float))
                             and isinstance(activity_vector[-1], (int, float))
                             and activity_vector[0] <= 0.05 < activity_vector[-1])
    finite_differences = {
        probe: [None if a is None or b is None else b - a
                for a, b in zip(vector, vector[1:])]
        for probe, vector in probe_vectors.items()
    }
    base = [int(n) for n in base_sizes(campaign_spec)]
    top_base = base[-1] if base else 0
    extension_sizes = sorted(int(n) for n in summaries if int(n) > top_base)
    extension_per_n: dict[str, dict] = {}
    extension_probe_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    extension_probe_bucket_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    extension_probe_se_vectors: dict[str, list] = {probe: [] for probe in PROBES}
    extension_connected_vector: list = []
    extension_clustering_vector: list = []
    extension_radius_vector: list = []
    extension_mean_degree_vector: list = []
    extension_giant_mean_degree_vector: list = []
    for n in extension_sizes:
        summary = summaries[n]
        try:
            ext_state = rung_states.get(n) or _b143_rung_sampling_state(campaign_spec, n, summary, [])
            terminal_ext = ext_state.get("classification")
            chains_verdict_ext = ("CHAINS_DISAGREED"
                        if failure_codes(ext_state.get("failures")) & _CHAINS_DISAGREED else None)
        except Exception:
            terminal_ext, chains_verdict_ext = None, None
        connected_ext = _mean(summary, "connected_fraction")
        clustering_ext = _mean(summary, "clustering")
        radius_ext = _mean(summary, "half_volume_radius")
        degree_ext = _mean(summary, "mean_degree")
        cell = {"n": n,
                "rung_terminal_classification": terminal_ext,
                "chains_verdict": chains_verdict_ext,
                "mean_degree": degree_ext,
                "giant_mean_degree": _mean(summary, "giant_mean_degree"),
                "connected_fraction": connected_ext,
                "clustering": clustering_ext,
                "two_core_fraction": _mean(summary, "two_core_fraction"),
                "degree_heterogeneity": _mean(summary, "degree_heterogeneity"),
                "half_volume_radius": radius_ext,
                "density": _mean(summary, "density"),
                "effective_samples": _mean(summary, "effective_samples"),
                "iat_sweeps": _mean(summary, "iat_sweeps"),
                "stationarity_drift": _mean(summary, "stationarity_drift"),
                "measurement_seed_count": summary.get("seeds"),
                "probes": {}}
        refusals_ext = summary.get("probe_refusals") or {}
        floor_failed_ext = bool(connected_ext is not None
                                and float(connected_ext) < _conn_floor)
        for probe in PROBES:
            node = summary.get(probe) if isinstance(summary.get(probe), dict) else {}
            value = node.get("mean")
            se = node.get("se")
            codes = dict(refusals_ext.get(probe) or {})
            valid_fraction = float(summary.get(f"{probe}_valid_fraction") or 0.0)
            entry = {"valid": value is not None}
            if value is None and codes:
                entry["refusal"] = max(sorted(codes), key=lambda c: codes[c])
            bucket = bucket_for_rung(
                entry if (value is not None or codes) else None,
                terminal_classification=terminal_ext, chains_verdict=chains_verdict_ext,
                connectivity_floor_failed=floor_failed_ext,
            )
            cell["probes"][probe] = {
                "value": value, "se": float(se) if isinstance(se, (int, float)) else None,
                "valid_fraction": valid_fraction, "refusals": codes,
                "bucket": bucket.value if bucket is not None else None,
                "n_seeds": node.get("n_seeds"),
            }
            _with_measured(cell["probes"][probe], summary, probe)
            extension_probe_vectors[probe].append(value)
            extension_probe_bucket_vectors[probe].append(cell["probes"][probe]["bucket"])
            extension_probe_se_vectors[probe].append(cell["probes"][probe]["se"])
        for probe in PROBES:
            cell[probe] = cell["probes"][probe]["value"]
            cell[f"{probe}_bucket"] = cell["probes"][probe]["bucket"]
            cell[f"{probe}_valid_fraction"] = cell["probes"][probe]["valid_fraction"]
        _with_small_world(cell, summary)
        extension_per_n[str(n)] = cell
        extension_connected_vector.append(connected_ext)
        extension_clustering_vector.append(clustering_ext)
        extension_radius_vector.append(radius_ext)
        extension_mean_degree_vector.append(degree_ext)
        extension_giant_mean_degree_vector.append(cell["giant_mean_degree"])
    return {
        "contract": "rung-phenotype-3",
        "probes": list(PROBES),
        "base_sizes": base,
        "per_n": per_n,
        "extension_sizes": extension_sizes,
        "extension_per_n": extension_per_n,
        "extension_probe_vectors": extension_probe_vectors,
        "extension_probe_bucket_vectors": extension_probe_bucket_vectors,
        "extension_probe_se_vectors": extension_probe_se_vectors,
        "extension_connected_fraction_vector": extension_connected_vector,
        "extension_clustering_vector": extension_clustering_vector,
        "extension_half_volume_radius_vector": extension_radius_vector,
        "extension_mean_degree_vector": extension_mean_degree_vector,
        "extension_giant_mean_degree_vector": extension_giant_mean_degree_vector,
        "probe_vectors": probe_vectors,
        "probe_se_vectors": probe_se_vectors,
        "probe_valid_fraction_vectors": probe_valid_fraction_vectors,
        "probe_refusal_vectors": probe_refusal_vectors,
        "probe_bucket_vectors": probe_bucket_vectors,
        "probe_finite_differences": finite_differences,
        "half_volume_radius_vector": radius_vector,
        "connected_fraction_vector": connected_vector,
        "two_core_fraction_vector": two_core_vector,
        "clustering_vector": clustering_vector,
        "degree_heterogeneity_vector": heterogeneity_vector,
        "activity_vector": activity_vector,
        "equilibration_state_vector": equilibration_vector,
        "chains_verdict_vector": chains_verdict_vector,
        "spectral_no_window_vector": no_window_vector,
        "recovery": {
            "invalid_ds_at_64_valid_by_4096": recovered_ds_64,
            "invalid_ds_at_64_256_valid_by_4096": recovered_ds_64_256,
            "low_connected_fraction_recovered_by_4096": low_connected_recovery,
            "low_activity_recovered_by_4096": low_activity_recovery,
        },
        "interpretation": "discovery/triage phenotype; not asymptotic confirmation",
    }
