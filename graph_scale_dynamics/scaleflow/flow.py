from __future__ import annotations
import math
import numpy as np

from graph_scale_dynamics.domain.model import EVIDENCE_SUMMARY_CONTRACT


EPS = 1e-9
UNCODED_REFUSAL = "UNCODED"


SUMMARY_OBSERVABLES: tuple[str, ...] = ("d_s", "d_V", "d_B", "d_w")


def summary_dimensions(summary: dict, *, digits: int = 3) -> dict:
    from graph_scale_dynamics.scaleflow.observables import IMPLAUSIBLE_ABOVE

    withheld: dict[str, str] = {}

    def pick(key: str):
        stat = (summary or {}).get(key)
        if not isinstance(stat, dict) or stat.get("mean") is None:
            return None
        value = float(stat["mean"])
        ceiling = IMPLAUSIBLE_ABOVE.get(key)
        if ceiling is not None and abs(value) > ceiling:
            withheld[key] = (
                f"stored {key}={value:.4g} exceeds {ceiling:g}, which the current "
                "estimator cannot emit; recorded before the scaling-premise "
                "precondition existed"
            )
            return None
        return round(value, digits)

    values = {name: pick(name) for name in SUMMARY_OBSERVABLES}
    for name in SUMMARY_OBSERVABLES:
        values[f"{name}_valid"] = (summary or {}).get(f"{name}_valid_fraction")
    if withheld:
        values["withheld_implausible"] = withheld
    return values


def _worst_split(per_seed_metrics: list[dict], key: str):
    worst = None
    for metrics in per_seed_metrics:
        split = ((metrics.get("health") or {}).get("equilibration") or {}).get(key) or {}
        for value in split.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                worst = float(value) if worst is None else max(worst, float(value))
    return None if worst is None else round(worst, 3)


def _probe_refusal_counts(per_seed_metrics: list[dict]) -> dict[str, dict[str, int]]:
    from graph_scale_dynamics.scaleflow.probes import PROBES, RefusalCode
    out: dict[str, dict[str, int]] = {}
    for probe in PROBES:
        counts: dict[str, int] = {}
        for metrics in per_seed_metrics:
            entry = metrics.get(probe)
            if entry is None:
                code = RefusalCode.NOT_MEASURED.value
            elif isinstance(entry, dict) and entry.get("valid"):
                continue
            else:
                code = str((entry or {}).get("refusal") or UNCODED_REFUSAL)
            counts[code] = counts.get(code, 0) + 1
        out[probe] = counts
    return out


def _diffusive_evidence(per_seed_metrics: list[dict]) -> dict:
    rows = [(m.get("d_s") or {}).get("diffusive_window_evidence") for m in per_seed_metrics]
    rows = [r for r in rows if isinstance(r, dict) and r.get("comparable")]
    if not rows:
        return {"seeds_comparable": 0, "seeds": len(per_seed_metrics),
                "reading": "no seed produced a window long enough to compare two models"}

    def _mean(key):
        vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 6) if vals else None

    return {
        "seeds_comparable": len(rows), "seeds": len(per_seed_metrics),
        "delta_aicc": _mean("delta_aicc"),
        "power_law_exponent": _mean("power_law_exponent"),
        "gap_decay_rate": _mean("gap_decay_rate"),
        "seeds_calling_it_a_power_law": sum(1 for r in rows if r.get("is_power_law")),
        "reading": ("delta_aicc is the power law's AICc advantage over spectral-gap "
                    "decay on the same points; positive past 2 accepts d_s. "
                    "gap_decay_rate is the exponential's fitted rate and is a "
                    "property of the graph rather than of N, so a rung-to-rung "
                    "change in it is a change in the object"),
    }


def _structural_split_record(per_seed_metrics: list[dict]) -> dict | None:
    values: dict[str, list] = {}
    judged: dict[str, list] = {}
    limits = None
    for metrics in per_seed_metrics:
        health = metrics.get("health") or {}
        split = (health.get("equilibration") or {}).get("structural_split") or {}
        last = next((row.get("certificate") or {} for row in reversed(health.get("sampling_checkpoints") or [])
                     if (row.get("certificate") or {}).get("structural_limits")), {})
        limits = last.get("structural_limits") or limits
        for key, value in split.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                values.setdefault(key, []).append(float(value))
                judged.setdefault(key, []).append((last.get("structural_thresholds") or {}).get(key))
    if not values:
        return None
    return {key: {"per_seed": vals, "max": max(vals), "mean": float(np.mean(vals)),
                  "seed_sd": (float(np.std(vals, ddof=1)) if len(vals) > 1 else None),
                  "limit": (limits or {}).get(key), "judged_by": judged.get(key)}
            for key, vals in sorted(values.items())}


def _withheld_readings(per_seed_metrics: list[dict]) -> dict:
    out = {}
    for probe in ("d_s", "d_V", "d_B", "d_w"):
        rows = []
        for metrics in per_seed_metrics:
            entry = metrics.get(probe) or {}
            value = entry.get("would_have_reported")
            if (not entry.get("valid") and isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value)):
                rows.append((float(value), str(entry.get("refusal") or "UNCODED")))
        if rows:
            vals = [v for v, _ in rows]
            reasons: dict[str, int] = {}
            for _, code in rows:
                reasons[code] = reasons.get(code, 0) + 1
            out[probe] = {"values": vals, "mean": float(np.mean(vals)), "seeds": len(vals), "reasons": reasons}
    return out


def _census_summary(per_seed_metrics: list[dict]) -> dict | None:
    rows = [((m.get("census") or {}).get("empty")) for m in per_seed_metrics]
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return None

    def mean(getter):
        vals = []
        for row in rows:
            try:
                value = getter(row)
            except (KeyError, TypeError):
                value = None
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                vals.append(float(value))
        return {"mean": float(np.mean(vals)), "seeds": len(vals),
                "seed_sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else None} if vals else None

    return {
        "largest_component_diameter": mean(lambda r: r["largest_component"]["diameter"]["lower_bound"]),
        "largest_component_diameter_upper": mean(lambda r: r["largest_component"]["diameter"]["upper_bound"]),
        "largest_component_size": mean(lambda r: r["largest_component"]["size"]),
        "largest_component_cycle_rank": mean(lambda r: r["largest_component"]["cycle_rank"]),
        "spectral_gap": mean(lambda r: r["largest_component"]["spectral_gap"]["value"]),
        "component_count": mean(lambda r: r["components"]["count"]),
        "triangles": mean(lambda r: r["cliques"]["triangles"]),
        "largest_clique": mean(lambda r: r["cliques"]["largest_clique"]),
        "squares": mean(lambda r: r["squares"]),
        "assortativity": mean(lambda r: r["assortativity"]),
        "degeneracy": mean(lambda r: r["k_core"]["degeneracy"]),
    }


def _small_world_fraction(per_seed_metrics: list[dict]) -> float | None:
    flags = [bool((m.get("small_world") or {}).get("flag")) for m in per_seed_metrics
             if isinstance(m.get("small_world"), dict)]
    return (sum(flags) / len(flags)) if flags else None


def _giant_mean_degrees(per_seed_metrics: list[dict]) -> list[float]:
    out = []
    for metrics in per_seed_metrics:
        health = metrics.get("health") or {}
        edges, fraction, n = (health.get(k) for k in ("largest_component_edges", "connected_fraction", "n"))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (edges, fraction, n)):
            continue
        size = round(float(fraction) * float(n))
        if size > 0:
            out.append(2.0 * float(edges) / size)
    return out


def rung_summary(per_seed_metrics: list[dict]) -> dict:
    def collect(path):
        vals = []
        for metrics in per_seed_metrics:
            node = metrics
            for key in path[:-1]:
                node = node.get(key) or {}
            value = node.get(path[-1])
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                vals.append(float(value))
        return vals

    def stat(vals, within_ses=None):
        if not vals:
            return None
        arr = np.asarray(vals, dtype=float)
        k = len(arr)
        between_var = float(arr.var(ddof=1)) if k > 1 else 0.0
        within = []
        for value in within_ses or []:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                within.append(float(value))
        within_var_of_mean = sum(value * value for value in within) / (k * k) if within else 0.0
        between_var_of_mean = between_var / k if k > 1 else 0.0
        se = math.sqrt(within_var_of_mean + between_var_of_mean)
        return {"mean": float(arr.mean()), "se": float(se) if se > 0 else None,
                "n_seeds": k, "within_seeds_with_se": len(within),
                "between_seed_sd": math.sqrt(between_var) if k > 1 else None}

    dh_valid = [m for m in per_seed_metrics if (m.get("d_V") or {}).get("valid")]
    ds_valid = [m for m in per_seed_metrics if (m.get("d_s") or {}).get("valid")]
    db_valid = [m for m in per_seed_metrics if (m.get("d_B") or {}).get("valid")]
    dw_valid = [m for m in per_seed_metrics if (m.get("d_w") or {}).get("valid")]
    summary = {
        "summary_contract": EVIDENCE_SUMMARY_CONTRACT,
        "seeds": len(per_seed_metrics),
        "d_V": stat([m["d_V"]["d_V_window"] for m in dh_valid],
                    [m["d_V"].get("se") for m in dh_valid]),
        "d_V_valid_fraction": len(dh_valid) / max(1, len(per_seed_metrics)),
        "d_s": stat([m["d_s"]["d_s"] for m in ds_valid],
                    [m["d_s"].get("se") for m in ds_valid]),
        "d_s_valid_fraction": len(ds_valid) / max(1, len(per_seed_metrics)),
        "d_B": stat([m["d_B"]["d_B"] for m in db_valid],
                    [m["d_B"].get("se") for m in db_valid]),
        "d_B_valid_fraction": len(db_valid) / max(1, len(per_seed_metrics)),
        "d_w": stat([m["d_w"]["d_w"] for m in dw_valid],
                    [m["d_w"].get("se") for m in dw_valid]),
        "d_w_valid_fraction": len(dw_valid) / max(1, len(per_seed_metrics)),
        "d_w_subdiffusive_fraction": (
            len([m for m in dw_valid if (m.get("d_w") or {}).get("subdiffusive")])
            / max(1, len(dw_valid))) if dw_valid else None,
        "small_world_fraction": _small_world_fraction(per_seed_metrics),
        "probe_refusals": _probe_refusal_counts(per_seed_metrics),
        "d_s_no_window_fraction": (
            len([m for m in per_seed_metrics
                 if (m.get("d_s") or {}).get("diffusive_window_evidence") is not None
                 and not (m.get("d_s") or {}).get("valid")])
            / max(1, len(per_seed_metrics))),
        "d_s_diffusive_evidence": _diffusive_evidence(per_seed_metrics),
        "half_volume_radius": stat(
            collect(("half_volume_radius",)),
            collect(("half_volume_radius_se",)),
        ),
        "half_volume_radius_source_fraction": stat(
            collect(("half_volume_radius_source_fraction",))
        ),
        "mean_distance": stat(
            collect(("half_volume_radius",)) or collect(("mean_distance",)),
            collect(("half_volume_radius_se",)),
        ),
        "diameter": stat(collect(("diameter_lower_bound",))),
        "diameter_upper_bound": stat(collect(("diameter_upper_bound",))),
        "distance_window_truncated_fraction": (
            sum(1 for m in per_seed_metrics if m.get("distance_window_truncated"))
            / max(1, len(per_seed_metrics))
        ),
        "connected_fraction": stat(collect(("health", "connected_fraction"))),
        "mean_degree": stat(collect(("health", "mean_degree"))),
        "giant_mean_degree": stat(_giant_mean_degrees(per_seed_metrics)),
        "density": stat(collect(("health", "density"))),
        "degree_heterogeneity": stat(collect(("health", "degree_heterogeneity"))),
        "cycle_rank": stat(collect(("health", "cycle_rank"))),
        "largest_component_cycle_rank": stat(collect(("health", "largest_component_cycle_rank"))),
        "two_core_fraction": stat(collect(("health", "two_core_fraction"))),
        "clustering": stat(collect(("health", "clustering"))),
        "accepted_topology_changes_per_node_late": stat(
            collect(("health", "activity", "accepted_topology_changes_per_node_late"))
        ),
        "accepted_topology_changes_per_node_cumulative": stat(
            collect(("health", "activity", "accepted_topology_changes_per_node_cumulative"))
        ),
        "late_edge_jaccard": stat(collect(("health", "activity", "late_edge_jaccard"))),
        "iat_sweeps": stat(collect(("health", "equilibration", "tau_int_sweeps"))),
        "effective_samples": stat(collect(("health", "equilibration", "effective_samples"))),
        "equilibration_split_z": _worst_split(per_seed_metrics, "split"),
        "equilibration_structural_delta": _worst_split(per_seed_metrics, "structural_split"),
        "stationarity_drift": stat(collect(("health", "stationarity", "normalized_drift"))),
        "log_diameter_flags": sum(1 for m in per_seed_metrics if m.get("log_diameter_flag")),
        "log_diameter_false": sum(1 for m in per_seed_metrics if m.get("log_diameter_flag") is False),
        "log_diameter_unknown": sum(1 for m in per_seed_metrics
                                    if "log_diameter_flag" in m and m.get("log_diameter_flag") is None),
        "equilibration_structural_split": _structural_split_record(per_seed_metrics),
        "withheld": _withheld_readings(per_seed_metrics),
        "census": _census_summary(per_seed_metrics),
        "couplings": next((m.get("couplings") for m in per_seed_metrics if m.get("couplings")), None),
        "exponential_growth_flags": sum(1 for m in per_seed_metrics
                                        if ((m.get("d_V") or {}).get("volume_growth") or {}).get("verdict")
                                        == "exponential"),
    }
    for probe, valid, key in (("d_V", dh_valid, "d_V_window"), ("d_s", ds_valid, "d_s"), ("d_B", db_valid, "d_B"),
                              ("d_w", dw_valid, "d_w")):
        measured = _measured_se([m[probe] for m in valid], key)
        if measured is not None:
            summary[f"{probe}_measured_se"] = measured
    return summary


def _measured_se(blocks: list[dict], key: str) -> float | None:
    errors = [block.get("measured_se") for block in blocks]
    values = [block.get(key) for block in blocks]
    if not blocks or not all(isinstance(e, (int, float)) and not isinstance(e, bool) and math.isfinite(e)
                             for e in errors):
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        return None
    k = len(values)
    between = float(np.var(np.asarray(values, dtype=float), ddof=1)) / k if k > 1 else 0.0
    return float(math.sqrt(sum(float(e) ** 2 for e in errors) / (k * k) + between))


def _delta(metric_a, metric_b):
    if not metric_a or not metric_b:
        return None
    delta = metric_b["mean"] - metric_a["mean"]
    sigma = math.sqrt((metric_a.get("se") or 0.0) ** 2 + (metric_b.get("se") or 0.0) ** 2)
    return {"delta": delta, "sigma": sigma,
            "normalized": delta / sigma if sigma > EPS else None}


def transition_record(n_from: int, summary_from: dict, n_to: int, summary_to: dict,
                      previous_transition: dict | None = None) -> dict:
    record = {"n_from": n_from, "n_to": n_to, "metric_deltas": {}, "d_eff": {}}
    for key in ("d_V", "d_s", "mean_degree", "connected_fraction", "density",
                "degree_heterogeneity"):
        record["metric_deltas"][key] = _delta(summary_from.get(key), summary_to.get(key))
    def incomplete_half_volume(summary: dict) -> bool:
        completion = (summary.get("half_volume_radius_source_fraction") or {}).get("mean")
        return (isinstance(completion, (int, float))
                and math.isfinite(float(completion))
                and float(completion) < 1.0 - 1e-12)

    record["d_eff_reasons"] = {}
    census_from = (summary_from.get("census") or {}).get("largest_component_diameter")
    census_to = (summary_to.get("census") or {}).get("largest_component_diameter")
    if census_from is not None and census_to is not None:
        summary_from = dict(summary_from, census_diameter={"mean": census_from["mean"], "se": None})
        summary_to = dict(summary_to, census_diameter={"mean": census_to["mean"], "se": None})
    for key in ("half_volume_radius", "mean_distance", "diameter", "census_diameter"):
        a, b = summary_from.get(key), summary_to.get(key)
        record["metric_deltas"][key] = _delta(a, b)
        truncated = bool(
            (key == "diameter" and (
                (summary_from.get("distance_window_truncated_fraction") or 0) > 0
                or (summary_to.get("distance_window_truncated_fraction") or 0) > 0
            ))
            or (key in ("half_volume_radius", "mean_distance") and (
                incomplete_half_volume(summary_from)
                or incomplete_half_volume(summary_to)
            ))
        )
        if truncated:
            record["d_eff"][key] = None
            record["d_eff_reasons"][key] = ("a sampled BFS stopped at its radius cap"
                                            if key == "diameter" else
                                            "a sampled source did not reach half the component")
        elif a and b and a["mean"] > EPS and b["mean"] > a["mean"] * (1 + 1e-6):
            frac_a = (summary_from.get("connected_fraction") or {}).get("mean") or 1.0
            frac_b = (summary_to.get("connected_fraction") or {}).get("mean") or 1.0
            size_a = max(2.0, n_from * frac_a)
            size_b = max(size_a * (1 + 1e-9), n_to * frac_b)
            record["d_eff"][key] = math.log(size_b / size_a) / math.log(b["mean"] / a["mean"])
        else:
            record["d_eff"][key] = None
            record["d_eff_reasons"][key] = ("not measured at one of the two rungs" if not (a and b)
                                            else "did not grow between the rungs")
    if previous_transition:
        accel = {}
        for key, delta in record["metric_deltas"].items():
            prev = (previous_transition.get("metric_deltas") or {}).get(key)
            if delta and prev and prev.get("delta") is not None:
                accel[key] = abs(delta["delta"]) / (abs(prev["delta"]) + EPS)
        record["acceleration"] = accel
    record["window_quality"] = {"d_V_valid_fraction": [summary_from.get("d_V_valid_fraction"),
                                                       summary_to.get("d_V_valid_fraction")],
                                "d_s_valid_fraction": [summary_from.get("d_s_valid_fraction"),
                                                       summary_to.get("d_s_valid_fraction")]}
    return record
