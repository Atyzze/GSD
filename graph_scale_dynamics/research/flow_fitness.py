from __future__ import annotations

import math

FLOW_FITNESS_VERSION = "flow-contraction-fitness-1"

from graph_scale_dynamics.scaleflow.probes import PROBES

METRICS = PROBES

DEFAULT_DRIFT_TOLERANCE = 0.25

WEIGHTS = {"plateau": 0.30, "trend": 0.24, "depth": 0.12,
           "reproducibility": 0.16, "fit_quality": 0.18}

NEUTRAL = 0.5

DEFAULT_SEED_SD_TOLERANCE = 0.30

FIT_SCALES = {
    "reduced_chi2": 9.0,
    "max_standardized_residual": 4.0,
    "ci_width": 2.5,
    "model_spread": 1.0,
    "drop_smallest_shift": 0.75,
}

MIN_RUNGS = 3


def _series(rungs: dict, metric: str) -> list[tuple[int, float, float | None]]:
    out = []
    for n in sorted(rungs):
        stat = (rungs[n] or {}).get(metric)
        if not isinstance(stat, dict):
            continue
        mean = stat.get("mean")
        if isinstance(mean, (int, float)) and not isinstance(mean, bool) \
                and math.isfinite(float(mean)):
            se = stat.get("se")
            out.append((int(n), float(mean),
                        float(se) if isinstance(se, (int, float)) else None))
    return out


def _half_score(value, scale: float) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    magnitude = abs(float(value))
    if not math.isfinite(magnitude):
        return 0.0
    return 1.0 / (1.0 + magnitude / max(float(scale), 1e-9))


def seed_reproducibility(rungs: dict, metric: str,
                         tolerance: float = DEFAULT_SEED_SD_TOLERANCE) -> dict:
    spreads = []
    for n in sorted(rungs):
        stat = (rungs[n] or {}).get(metric)
        if not isinstance(stat, dict):
            continue
        if int(stat.get("n_seeds") or 0) < 2:
            continue
        spread = stat.get("between_seed_sd")
        if isinstance(spread, (int, float)) and not isinstance(spread, bool) \
                and math.isfinite(float(spread)):
            spreads.append(abs(float(spread)))
    if not spreads:
        return {"measured": False, "score": None,
                "reason": "no rung has two or more seeds with a usable estimate"}
    ordered = sorted(spreads)
    median = ordered[len(ordered) // 2]
    return {"measured": True, "score": _half_score(median, tolerance),
            "median_between_seed_sd": round(median, 4),
            "worst_between_seed_sd": round(ordered[-1], 4),
            "rungs_with_replicates": len(spreads), "tolerance": float(tolerance)}


def fit_quality(record: dict | None) -> dict:
    if not isinstance(record, dict) or not record.get("fitted"):
        return {"measured": False, "score": None,
                "reason": "no published free fit for this metric yet"}
    interval = record.get("ci_width")
    if interval is None and isinstance(record.get("ci"), (list, tuple)) \
            and len(record["ci"]) == 2:
        try:
            interval = float(record["ci"][1]) - float(record["ci"][0])
        except (TypeError, ValueError):
            interval = None
    raw = {
        "reduced_chi2": _half_score(
            max(0.0, float(record["reduced_chi2"]) - 1.0)
            if isinstance(record.get("reduced_chi2"), (int, float)) else None,
            FIT_SCALES["reduced_chi2"]),
        "max_standardized_residual": _half_score(
            record.get("max_standardized_residual"),
            FIT_SCALES["max_standardized_residual"]),
        "ci_width": _half_score(interval, FIT_SCALES["ci_width"]),
        "model_spread": _half_score(record.get("model_spread"),
                                    FIT_SCALES["model_spread"]),
        "drop_smallest_shift": _half_score(record.get("drop_smallest_shift"),
                                           FIT_SCALES["drop_smallest_shift"]),
    }
    present = {key: value for key, value in raw.items() if value is not None}
    if not present:
        return {"measured": False, "score": None,
                "reason": "published fit carries no scorable quality fields"}
    return {"measured": True, "score": sum(present.values()) / len(present),
            "components": {key: round(value, 4) for key, value in present.items()},
            "decision_ready": bool(record.get("robustness", {})
                                   .get("rung_identification_ok", False))}


def _valid_fraction(rungs: dict, metric: str, measured: list[int]) -> float:
    key = f"{metric}_valid_fraction"
    values = []
    for n in measured:
        fraction = (rungs.get(n) or {}).get(key)
        if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
            values.append(max(0.0, min(1.0, float(fraction))))
    return sum(values) / len(values) if values else 1.0


def metric_flow_contraction(rungs: dict, metric: str, *, ladder=None,
                         drift_tolerance: float = DEFAULT_DRIFT_TOLERANCE,
                         fit_record: dict | None = None,
                         seed_sd_tolerance: float = DEFAULT_SEED_SD_TOLERANCE) -> dict:
    series = _series(rungs, metric)
    if len(series) < MIN_RUNGS:
        return {"metric": metric, "scored": False,
                "reason": f"{len(series)} usable rungs; need {MIN_RUNGS}",
                "score": 0.0, "measured_rungs": [n for n, _, _ in series]}

    ns = [n for n, _, _ in series]
    values = [v for _, v, _ in series]
    drifts = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
    last_drift = drifts[-1]
    first_drift = max(drifts[0], 1e-9)

    tolerance = max(1e-6, float(drift_tolerance))
    plateau = tolerance / (tolerance + last_drift)

    reference = max(drifts[:-1]) if len(drifts) > 1 else first_drift
    ratio = last_drift / max(reference, 1e-9)
    trend = 1.0 / (1.0 + ratio)

    ladder = [int(n) for n in (ladder or ns)]
    lo, hi = min(ladder), max(ladder)
    span = math.log2(max(hi, lo * 2) / max(lo, 1))
    depth = min(1.0, max(0.0, math.log2(max(ns[-1], lo) / max(lo, 1)) / max(span, 1e-9)))

    window = _valid_fraction(rungs, metric, ns)
    reproducibility = seed_reproducibility(rungs, metric, seed_sd_tolerance)
    quality = fit_quality(fit_record)

    scores = {"plateau": plateau, "trend": trend, "depth": depth,
              "reproducibility": (reproducibility["score"]
                                  if reproducibility["score"] is not None else NEUTRAL),
              "fit_quality": (quality["score"]
                              if quality["score"] is not None else NEUTRAL)}
    measured = {"plateau", "trend", "depth"}
    if reproducibility["score"] is not None:
        measured.add("reproducibility")
    if quality["score"] is not None:
        measured.add("fit_quality")
    core = sum(WEIGHTS[key] * value for key, value in scores.items())
    score = window * core

    components = {key: round(value, 4) for key, value in scores.items()}
    components["window"] = round(window, 4)
    return {
        "metric": metric, "scored": True, "score": float(score),
        "measured_rungs": ns, "values": [round(v, 4) for v in values],
        "drifts": [round(d, 4) for d in drifts],
        "last_drift": float(last_drift),
        "components": components,
        "imputed_components": sorted(set(scores) - measured),
        "weights": dict(WEIGHTS),
        "reproducibility": reproducibility,
        "fit_quality": quality,
        "drift_tolerance": tolerance,
        "settled": bool(last_drift <= tolerance and ratio <= 1.05),
    }


def flow_fitness(rungs: dict, *, ladder=None,
                          drift_tolerance: float = DEFAULT_DRIFT_TOLERANCE,
                          fit_records: dict | None = None,
                          seed_sd_tolerance: float = DEFAULT_SEED_SD_TOLERANCE) -> dict:
    records = fit_records or {}
    per_metric = {metric: metric_flow_contraction(
        rungs, metric, ladder=ladder, drift_tolerance=drift_tolerance,
        fit_record=records.get(metric), seed_sd_tolerance=seed_sd_tolerance)
        for metric in METRICS}
    scored = [detail for detail in per_metric.values() if detail["scored"]]
    if not scored:
        return {"version": FLOW_FITNESS_VERSION, "score": 0.0, "best_metric": None,
                "scored": False, "metrics": per_metric,
                "reason": "no metric has enough measured rungs yet"}
    best = max(scored, key=lambda detail: detail["score"])
    settled = [detail["metric"] for detail in scored if detail["settled"]]
    return {
        "version": FLOW_FITNESS_VERSION,
        "score": float(best["score"]),
        "best_metric": best["metric"],
        "scored": True,
        "settled_metrics": settled,
        "both_settled": len(settled) == len(METRICS),
        "metrics": per_metric,
    }


def selection_value(fitness: dict, *, attempts: int, total_attempts: int,
                    exploration: float = 0.35, floor: float = 0.05) -> float:
    score = float(fitness.get("score") or 0.0)
    bonus = float(exploration) * math.sqrt(
        math.log(1.0 + max(0, int(total_attempts))) / (1.0 + max(0, int(attempts)))
    )
    return max(float(floor), score + bonus)


