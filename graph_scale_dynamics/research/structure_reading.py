from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

THRESHOLDS_FILE = Path(__file__).resolve().parents[1] / "resources" / "calibration" / "structure_thresholds.json"
READING_CONTRACT = "structure-reading-3"
LOCAL_D_S_WITHIN = 0.4
GIANT_FRACTION_AT_LEAST = 0.5
DIAMETER_EXPONENT_AT_MOST = 1.1
GAP_EXPONENT_AT_LEAST = -2.2


@lru_cache(maxsize=1)
def committed_thresholds() -> dict | None:
    try:
        table = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    t = table.get("thresholds") or {}
    return {"gap_exponent_at_most": t.get("gap_exponent_at_most"),
            "diameter_exponent_at_least": t.get("diameter_exponent_at_least"),
            "gap_window": table.get("gap_window"), "diameter_window": table.get("diameter_window"),
            "census_contract": table.get("census_contract"), "computed_utc": table.get("computed_utc")}


def degree_distribution(histogram: dict | None) -> dict[int, float] | None:
    counts = {int(k): int(v) for k, v in (histogram or {}).items() if int(v) > 0}
    total = sum(counts.values())
    if total == 0:
        return None
    return {k: v / total for k, v in counts.items()}


def configuration_giant_fraction(p: dict[int, float]) -> float:
    mean = sum(k * pk for k, pk in p.items())
    if mean <= 0:
        return 0.0
    u = 0.0
    for _ in range(10000):
        nxt = sum(k * pk * u ** (k - 1) for k, pk in p.items() if k >= 1) / mean
        if abs(nxt - u) < 1e-13:
            u = nxt
            break
        u = nxt
    giant = 1.0 - sum(pk * u ** k for k, pk in p.items())
    return 0.0 if giant < 1e-9 else giant


def seed_structure(n: int, census: dict | None) -> dict | None:
    if not census:
        return None
    p = degree_distribution(census.get("degree_histogram"))
    if p is None:
        return None
    giant = census.get("largest_component") or {}
    gap = (giant.get("spectral_gap") or {}).get("value")
    return {"p0": p.get(0, 0.0), "p1": p.get(1, 0.0), "p2": p.get(2, 0.0),
            "p3_plus": sum(v for k, v in p.items() if k >= 3),
            "mean_degree": sum(k * v for k, v in p.items()),
            "molloy_reed": sum(k * (k - 2) * v for k, v in p.items()),
            "predicted_giant_fraction": configuration_giant_fraction(p),
            "measured_giant_fraction": (giant.get("size") or 0) / max(1, int(n)),
            "cycle_rank_per_node": (giant.get("cycle_rank") or 0) / max(1, int(n)),
            "spectral_gap": gap if isinstance(gap, (int, float)) else None,
            "diameter": (giant.get("diameter") or {}).get("lower_bound")}


def _mean(rows: list[dict], key: str):
    vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float)) and math.isfinite(float(r[key]))]
    if not vals:
        return None
    return {"mean": float(np.mean(vals)), "seeds": len(vals),
            "seed_sd": (float(np.std(vals, ddof=1)) if len(vals) > 1 else None)}


def _slope(points: list[tuple[float, float]]):
    points = [(x, y) for x, y in points if x and y and x > 0 and y > 0]
    if len({x for x, _ in points}) < 2:
        return None
    lx, ly = np.log([p[0] for p in points]), np.log([p[1] for p in points])
    return float(np.polyfit(lx, ly, 1)[0])


def law_structure(measurements: list[dict], chain: str = "empty") -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs

    rows = [m for m in measurements or []
            if not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {}).get("sampler_audit"))]
    by_n: dict[int, list] = {}
    for m in select_best_runs(rows):
        metrics = m.get("metrics") or {}
        seed = seed_structure(int(m["n"]), of_chain(metrics.get("census"), chain))
        if seed is not None:
            seed.update(curvature_values(metrics, chain))
            seed.update(bulk_and_local(metrics, chain))
            by_n.setdefault(int(m["n"]), []).append(seed)
    keys = ("p0", "p1", "p2", "p3_plus", "mean_degree", "molloy_reed", "predicted_giant_fraction",
            "measured_giant_fraction", "cycle_rank_per_node", "spectral_gap", "diameter")
    keys += CURVATURE_KEYS
    keys += ("half_volume_radius", "local_d_s")
    rungs = []
    for n in sorted(by_n):
        row = {"n": n, "seeds": len(by_n[n])}
        row.update({k: _mean(by_n[n], k) for k in keys})
        pred, meas = row["predicted_giant_fraction"], row["measured_giant_fraction"]
        row["giant_excess"] = (None if not pred or not meas else round(meas["mean"] - pred["mean"], 4))
        rungs.append(row)
    reading = {"contract": READING_CONTRACT, "chain": chain, "rungs": rungs, **verdict(rungs)}
    reading = _log_diameter_guard(reading, measurements, chain)
    reading["three_readings"] = three_readings(rungs, reading)
    return reading


CURVATURE_KEYS = ("kappa_mean", "kappa_positive_share", "kappa_negative_share", "kappa_weighted")


def of_chain(section: dict | None, chain: str):
    from graph_scale_dynamics.domain.chain_list import of_chain as found
    return found(section, chain)


def curvature_values(metrics: dict, chain: str = "empty") -> dict:
    reading = of_chain(metrics.get("curvature"), chain) or {}
    fields = ("mean", "positive_share", "negative_share", "degree_weighted_mean")
    return {key: (reading.get(field) if reading.get("measured") and isinstance(reading.get(field), (int, float))
                  else None)
            for key, field in zip(CURVATURE_KEYS, fields, strict=True)}


def bulk_and_local(metrics: dict, chain: str = "empty") -> dict:
    if chain == "empty":
        radius = metrics.get("half_volume_radius")
        fit = metrics.get("d_s") if isinstance(metrics.get("d_s"), dict) else {}
        local = fit.get("d_s") if fit.get("valid") else None
    else:
        from graph_scale_dynamics.domain.chain_list import probes_of
        probes = probes_of(metrics, chain) or {}
        radius = probes.get("half_volume_radius")
        fit = probes.get("d_s") if isinstance(probes.get("d_s"), dict) else {}
        local = fit.get("value") if fit.get("valid") else None
    return {"half_volume_radius": radius if isinstance(radius, (int, float)) else None,
            "local_d_s": local if isinstance(local, (int, float)) else None}


def three_readings(rungs: list[dict], reading: dict, *, thresholds: dict | None = None) -> dict:
    t = thresholds or committed_thresholds() or {}
    window = tuple(int(n) for n in (t.get("diameter_window") or (4096, 262144)))
    floor = float(t.get("diameter_exponent_at_least") or 0.1751)

    def value(row, key):
        cell = row.get(key)
        cell = cell.get("mean") if isinstance(cell, dict) else cell
        return float(cell) if isinstance(cell, (int, float)) and math.isfinite(float(cell)) else None

    points = []
    for row in rungs or []:
        n, giant, radius = int(row["n"]), value(row, "measured_giant_fraction"), value(row, "half_volume_radius")
        if window[0] <= n <= window[1] and radius and giant is not None and giant >= GIANT_FRACTION_AT_LEAST:
            points.append((giant * n, radius))
    bulk = _slope(points) if len(points) >= 3 else None
    local_rows = [row for row in rungs or [] if value(row, "local_d_s") is not None]
    local = value(local_rows[-1], "local_d_s") if local_rows else None
    local_n = int(local_rows[-1]["n"]) if local_rows else None
    implied = reading.get("implied_spectral_dimension")
    implied = float(implied) if isinstance(implied, (int, float)) and math.isfinite(float(implied)) else None
    extremes = reading.get("finite_dimension")
    bulk_says = None if bulk is None else bool(bulk >= floor)
    local_says = None if local is None or implied is None else bool(abs(local - implied) <= LOCAL_D_S_WITHIN)
    says = (extremes, bulk_says, local_says)
    agree = (True if all(x is True for x in says) else False if any(x is False for x in says) else None)
    curved = [row for row in rungs or [] if value(row, "kappa_mean") is not None]
    kappa = value(curved[-1], "kappa_mean") if curved else None
    return {"extremes_finite": extremes, "gap_implied_d_s": None if implied is None else round(implied, 3),
            "kappa_mean": None if kappa is None else round(kappa, 4),
            "kappa_at_n": int(curved[-1]["n"]) if curved else None,
            "bulk_exponent": None if bulk is None else round(bulk, 4),
            "bulk_implied_dimension": None if not bulk or bulk <= 0 else round(1.0 / bulk, 3),
            "bulk_rungs": len(points), "bulk_finite": bulk_says,
            "local_d_s": None if local is None else round(local, 3), "local_d_s_at_n": local_n,
            "local_agrees_with_gap": local_says, "agree": agree,
            "rule": (f"all three: the committed rule reads a finite dimension, the half-volume radius grows at "
                     f"least as N^{floor} over N = {window[0]:,} to {window[1]:,}, and the local d_s at the "
                     f"largest N it reads is within {LOCAL_D_S_WITHIN} of the d_s the gap implies")}


def _log_diameter_guard(reading: dict, measurements: list[dict], chain: str = "empty") -> dict:
    if reading.get("finite_dimension") is not True:
        return reading
    from graph_scale_dynamics.decisions import structure_gate as SG
    from graph_scale_dynamics.domain.chain_list import of_chain as found
    per_n = SG.rung_structure(measurements)
    if not per_n:
        return reading
    top = max(per_n)
    flags = (per_n[top].get("log_diameter") if chain == "empty"
             else (found(per_n[top], chain) or {}).get("log_diameter")) or {}
    raised, unknown = int(flags.get("raised") or 0), int(flags.get("unknown") or 0)
    if not (raised or unknown):
        return reading
    code, state, count = ((SG.LOG_DIAMETER_RAISED, "raised", raised) if raised
                          else (SG.LOG_DIAMETER_UNKNOWN, "unknown", unknown))
    return dict(reading, finite_dimension=None, code=code,
                why=(reading.get("why") or "") + f"; but the log-diameter flag is {state} on {count} seed(s) "
                                                 f"at N={top}, and a {state} flag does not pass")


def verdict(rungs: list[dict]) -> dict:
    t = committed_thresholds()
    if t is None:
        return {"exponents": None, "finite_dimension": None,
                "why": "no committed structure thresholds in this build"}
    from graph_scale_dynamics.decisions import structure_gate as SG
    from graph_scale_dynamics.decisions.engine import Policy

    policy = Policy()
    rule = {"gap_exponent_at_most": float(t["gap_exponent_at_most"]),
            "diameter_exponent_at_least": float(t["diameter_exponent_at_least"]),
            "gap_window": tuple(int(n) for n in t["gap_window"]),
            "diameter_window": tuple(int(n) for n in t["diameter_window"]),
            "giant_fraction_at_least": float(policy.giant_fraction_at_least),
            "gap_exponent_at_least": float(policy.gap_exponent_at_least),
            "diameter_exponent_at_most": float(policy.diameter_exponent_at_most),
            "gap_opens_above": float(policy.gap_opens_above),
            "diameter_shrinks_below": float(policy.diameter_shrinks_below)}
    return dict(SG.verdict(rungs, rule), thresholds=t)


def calibration_readings(deviation_families: dict | None) -> dict:
    out = {}
    for name, family in (deviation_families or {}).items():
        rungs = []
        for row in list(family.get("rows") or []) + list(family.get("extension_rows") or []):
            s = row.get("structure")
            if not isinstance(s, dict) or not s.get("seeds"):
                continue
            rungs.append({"n": int(row["n"]), "spectral_gap": {"mean": s.get("gap")},
                          "diameter": {"mean": s.get("diameter_lower")},
                          "measured_giant_fraction": {"mean": s.get("giant_fraction")}})
        if not rungs:
            out[name] = {"finite_dimension": None,
                         "why": "no rung carries a census yet (tools/probe_calibration.py --structure)"}
            continue
        reading = verdict(rungs)
        out[name] = {k: reading.get(k) for k in ("finite_dimension", "exponents", "implied_spectral_dimension",
                                                 "implied_fractal_dimension", "why")}
    return out
