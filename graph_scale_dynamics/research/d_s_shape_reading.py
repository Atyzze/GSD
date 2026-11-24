from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

READING_CONTRACT = "gsd-d-s-shape-reading-1"
FLAT_DRIFT = 0.1
MIN_SEEDS = 3


def _rows(measurements: list[dict]) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    by_law = defaultdict(list)
    for row in measurements or []:
        by_law[str(row.get("candidate_id"))].append(row)
    out = defaultdict(list)
    for law, rows in by_law.items():
        kept = [r for r in rows if not ((((r.get("metrics") or {}).get("health") or {}).get("sampler") or {})
                                        .get("sampler_audit"))]
        for row in select_best_runs(kept):
            if row.get("n") is not None:
                out[(law, int(row["n"]))].append(row.get("metrics") or {})
    return out


def _reading(metrics: dict) -> tuple[float, float] | None:
    block = metrics.get("d_s") or {}
    value, se = block.get("d_s"), block.get("se")
    if block.get("valid") and isinstance(value, (int, float)) and isinstance(se, (int, float)) and se > 0:
        return float(value), float(se)
    return None


def record_section(measurements: list[dict] | None) -> dict:
    cells = _rows(measurements or [])
    by_rung: dict = defaultdict(lambda: {"laws": 0, "drifts": [], "z": []})
    per_law: dict = defaultdict(dict)
    for (law, n), seeds in cells.items():
        rung = by_rung[n]
        rung["laws"] += 1
        drifts = [s["drift_in_window"] for s in ((m.get("d_s_shape") or {}) for m in seeds)
                  if s.get("measured") and isinstance(s.get("drift_in_window"), (int, float))]
        rung["drifts"] += drifts
        readings = [r for r in (_reading(m) for m in seeds) if r is not None]
        if len(readings) >= MIN_SEEDS:
            for i, (value, se) in enumerate(readings):
                others = [r for j, r in enumerate(readings) if j != i]
                mean = sum(v for v, _ in others) / len(others)
                error = math.sqrt(se ** 2 + sum(s ** 2 for _, s in others) / len(others) ** 2)
                rung["z"].append(abs(value - mean) / error)
        if readings:
            k = len(readings)
            per_law[law][n] = {"d_s": sum(v for v, _ in readings) / k,
                               "se": math.sqrt(sum(s ** 2 for _, s in readings)) / k,
                               "drift": sum(drifts) / len(drifts) if drifts else None}
    steps = {"flat": {"settled": 0, "moved": 0}, "drifting": {"settled": 0, "moved": 0}}
    for rungs in per_law.values():
        ns = sorted(rungs)
        for low, high in zip(ns, ns[1:], strict=False):
            if high != 4 * low or rungs[low]["drift"] is None:
                continue
            a, b = rungs[low], rungs[high]
            kind = "flat" if abs(a["drift"]) < FLAT_DRIFT else "drifting"
            settled = abs(b["d_s"] - a["d_s"]) <= 2.0 * math.sqrt(a["se"] ** 2 + b["se"] ** 2)
            steps[kind]["settled" if settled else "moved"] += 1
    rungs = {}
    for n in sorted(by_rung):
        cell = by_rung[n]
        z = cell["z"]
        rungs[str(n)] = {"laws": cell["laws"], "seeds_with_a_shape": len(cell["drifts"]),
                         "median_abs_drift": round(median(abs(d) for d in cell["drifts"]), 4) if cell["drifts"]
                         else None,
                         "coverage": {"seeds": len(z),
                                      "within_1": round(sum(1 for v in z if v <= 1.0) / len(z), 4) if z else None,
                                      "within_2": round(sum(1 for v in z if v <= 2.0) / len(z), 4) if z else None}}
    return {"contract": READING_CONTRACT, "by_rung": rungs, "flat_before_settled": steps,
            "flat_drift_under": FLAT_DRIFT,
            "reading": ("coverage: each seed's d_s from the others' mean in units of their combined error, about 68% "
                        "within 1 and 95% within 2 if the errors are right; a flat exponent at one rung against a "
                        "settled step to the next (within twice the combined error), a reading and never a rule")}


def render(section: dict, label: str) -> list[str]:
    if not section or section.get("error"):
        return [f"  {label}: the d_s shape not read ({(section or {}).get('error', 'no section')})"] if section else []
    cells = []
    for n, rung in (section.get("by_rung") or {}).items():
        cover = rung.get("coverage") or {}
        if cover.get("seeds"):
            cells.append(f"{int(n):,}: {cover['within_1']:.0%}/{cover['within_2']:.0%} of {cover['seeds']:,}"
                         + (f", drift {rung['median_abs_drift']:.2f}" if rung.get("median_abs_drift") is not None
                            else ""))
    steps = section.get("flat_before_settled") or {}
    flat, drifting = steps.get("flat") or {}, steps.get("drifting") or {}
    tail = ""
    if sum(flat.values()) + sum(drifting.values()):
        tail = (f"; a flat exponent then {flat.get('settled', 0)} settled, {flat.get('moved', 0)} moved, a drifting "
                f"one {drifting.get('settled', 0)} and {drifting.get('moved', 0)}")
    return [f"  {label}: d_s's error covers its seeds (within 1 and 2, of seeds) " + ("; ".join(cells) or "-") + tail]
