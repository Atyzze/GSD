from __future__ import annotations

import math
import statistics
import time

from graph_scale_dynamics.calibration.cells import cell_key, family_ladder
from graph_scale_dynamics.calibration.contract import CHANNELS

CAMPAIGN_RUNGS = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)
NOISE_SPREAD = 0.1
FRACTAL_FAMILIES = {"sierpinski_gasket", "sierpinski_carpet"}
LATTICE_FAMILIES = {"periodic_ring", "periodic_square_lattice", "periodic_cubic_lattice",
                    "periodic_triangular_lattice", "periodic_honeycomb_lattice",
                    "periodic_hypercubic_lattice_4d"}

FAILING_STATUSES = ("OUT_OF_TOLERANCE", "REFUSED", "FALSE_CONFIDENCE", "REFUSED_MAJORITY")

AVAILABILITY_FLOOR = 0.5

REFUSAL_GATES = (
    ("AICc", "model selection (AICc)"),
    ("exponential", "exponential growth"),
    ("diffusive window", "no diffusive window"),
    ("scaling window", "no scaling window"),
    ("window", "scaling window"),
    ("saturat", "walk saturated"),
    ("component", "component size"),
    ("usable", "too few points"),
    ("displacement", "displacement growth"),
    ("power law", "not power-law"),
)


def refusal_gate(reason: str | None) -> str:
    text = str(reason or "").lower()
    for needle, label in REFUSAL_GATES:
        if needle.lower() in text:
            return label
    return "other" if text else "unknown"


def dispersion_meaning(family: dict) -> str:
    if family.get("graph_varies_per_seed"):
        return ("ensemble dispersion: each seed measures a different graph draw, "
                "so the spread is graph-to-graph variation plus estimator noise")
    return ("estimator dispersion: every seed measures the same graph, so the "
            "spread is walk and estimator noise only")


def _judge(family: dict, channel: str, n: int, value: float | None,
           expected: float | None) -> tuple[str, float | None, float | None]:
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance

    refusal_expected = family.get("expectation") == "REFUSE"
    drift = (abs(value - expected) if value is not None and expected is not None else None)
    tolerance = None if refusal_expected else ladder_tolerance(family["name"], channel, n)
    if refusal_expected:
        gating = family.get("refusal_gated_from") or {}
        if value is None:
            status = "REFUSED_OK"
        elif channel not in gating:
            status = "UNGATED_MEASURED"
        elif int(n) < int(gating[channel]):
            status = "UNGATED_MEASURED"
        else:
            status = "FALSE_CONFIDENCE"
    elif tolerance is None:
        status = "UNGATED" if value is None else "UNGATED_MEASURED"
    elif value is None:
        status = "REFUSED"
    elif drift is not None and drift <= tolerance:
        status = "WITHIN_TOLERANCE"
    else:
        status = "OUT_OF_TOLERANCE"
    return status, drift, tolerance


def _rung_row(family: dict, rung: dict, cells: dict, seeds: int) -> dict:
    import numpy as np

    present = []
    for seed in range(int(seeds)):
        cell = cells.get(cell_key(family["name"], rung["parameter"], seed))
        if isinstance(cell, dict) and cell.get("status") == "ok":
            present.append(cell)
    theory = dict(family.get("theory") or {})
    n = int(rung["n"])
    channels = {}
    for channel in sorted(set(theory) | set(CHANNELS)):
        per_seed = []
        ses = []
        gates: dict[str, int] = {}
        for cell in present:
            entry = (cell.get("channels") or {}).get(channel) or {}
            if entry.get("valid") and isinstance(entry.get("value"), (int, float)):
                per_seed.append(float(entry["value"]))
                if isinstance(entry.get("se"), (int, float)):
                    ses.append(float(entry["se"]))
            else:
                per_seed.append(None)
                gate = refusal_gate(entry.get("reason"))
                gates[gate] = gates.get(gate, 0) + 1
        finite = [v for v in per_seed if v is not None]
        value = float(np.asarray(finite, dtype=float).mean()) if finite else None
        expected = theory.get(channel)
        status, drift, tolerance = _judge(family, channel, n, value, expected)
        valid_fraction = (len(finite) / len(present)) if present else None
        floor = float(family.get("availability_floor", AVAILABILITY_FLOOR))
        if not present:
            status = "MISSING"
        elif (tolerance is not None and family.get("expectation") != "REFUSE"
              and valid_fraction is not None and valid_fraction < floor and finite):
            status = "REFUSED_MAJORITY"
        channels[channel] = {
            "measured": value,
            "theory": expected,
            "drift": drift,
            "relative_deviation": (drift / abs(expected) if drift is not None and expected else None),
            "tolerance": tolerance,
            "status": status,
            "valid_fraction": (round(valid_fraction, 4) if valid_fraction is not None else None),
            "availability_floor": (floor if tolerance is not None else None),
            "per_seed": per_seed,
            "seed_std": (statistics.pstdev(finite) if len(finite) >= 2 else None),
            "seed_refusals": sum(1 for v in per_seed if v is None),
            "refusal_gates": gates,
            "mean_se": (sum(ses) / len(ses) if ses else None),
            "seeds": len(present),
        }
    from graph_scale_dynamics.calibration.structure import rung_structure
    row = {
        "parameter": rung["parameter"], "n": n,
        "seeds_planned": int(seeds), "seeds_present": len(present),
        "complete": len(present) >= int(seeds),
        "channels": channels,
        "wall_seconds": round(sum(float(c.get("elapsed_seconds") or 0.0) for c in present), 3),
        "structure": rung_structure(present),
    }
    if rung.get("extension"):
        row["extension"] = True
    return row


def readings_judged_as_a_rung(family: dict, parameter, n: int, readings: dict) -> dict:
    seeds = max((len(values) for values in readings.values()), default=0)
    cells = {cell_key(family["name"], parameter, seed): {"status": "ok", "channels": {
        channel: {"valid": values[seed] is not None, "value": values[seed], "se": None, "reason": None}
        for channel, values in readings.items() if seed < len(values)}} for seed in range(seeds)}
    return _rung_row(family, {"parameter": parameter, "n": int(n)}, cells, seeds)["channels"]


def finite_size_fit(rows: list[dict], channel: str) -> dict | None:
    points = [(float(row["n"]), float(row["channels"][channel]["measured"]))
              for row in rows if channel in row["channels"]
              and row["channels"][channel].get("measured") is not None]
    if len(points) < 4:
        return None
    points.sort()
    n_values = [p[0] for p in points]
    d_values = [p[1] for p in points]
    best = None
    for step in range(1, 61):
        omega = step * 0.05
        x = [n ** (-omega) for n in n_values]
        mean_x = sum(x) / len(x)
        mean_d = sum(d_values) / len(d_values)
        sxx = sum((xi - mean_x) ** 2 for xi in x)
        if sxx <= 1e-18:
            continue
        a = sum((xi - mean_x) * (di - mean_d) for xi, di in zip(x, d_values, strict=True)) / sxx
        d_star = mean_d - a * mean_x
        rss = sum((di - (d_star + a * xi)) ** 2 for xi, di in zip(x, d_values, strict=True))
        if best is None or rss < best["rss"]:
            best = {"d_star": d_star, "a": a, "omega": omega, "rss": rss}
    if best is None:
        return None
    theory = rows[0]["channels"][channel].get("theory")
    spread = math.sqrt(best["rss"] / len(points))
    at_bound = best["omega"] >= 2.99 or best["omega"] <= 0.051
    return {
        "d_star": round(best["d_star"], 4),
        "omega": None if at_bound else round(best["omega"], 2),
        "correction_amplitude": None if at_bound else round(best["a"], 4),
        "omega_unresolved": at_bound,
        "residual_rms": round(spread, 4),
        "points": len(points),
        "theory": theory,
        "asymptote_gap": (round(best["d_star"] - float(theory), 4) if theory is not None else None),
        "contracting": bool(not at_bound and best["omega"] > 0),
    }


def ladder_trend(rows: list[dict], channel: str) -> str | None:
    drifts = [(row["n"], row["channels"][channel]["drift"]) for row in rows
              if channel in row["channels"] and row["channels"][channel]["drift"] is not None]
    if len(drifts) < 4:
        return None
    drifts.sort()
    half = len(drifts) // 2
    early = statistics.median(d for _, d in drifts[:half])
    late = statistics.median(d for _, d in drifts[half:])
    if late < 0.8 * early:
        return "IMPROVING_WITH_N"
    if late > 1.25 * early:
        return "WORSENING_WITH_N"
    return "FLAT"


def _measured_cells(rows: list[dict], channel: str) -> list[dict]:
    out = []
    for row in rows:
        cell = (row.get("channels") or {}).get(channel)
        if not cell or cell.get("measured") is None or cell.get("theory") is None:
            continue
        out.append({"n": int(row["n"]), "measured": float(cell["measured"]),
                    "theory": float(cell["theory"]),
                    "bias": float(cell["measured"]) - float(cell["theory"]),
                    "drift": abs(float(cell["measured"]) - float(cell["theory"])),
                    "spread": cell.get("seed_std"), "status": cell.get("status")})
    out.sort(key=lambda c: c["n"])
    return out


def convergence_verdict(rows: list[dict], flow: dict | None, channel: str) -> dict:
    cells = _measured_cells(rows, channel)
    if len(cells) < 4:
        return {"verdict": "INSUFFICIENT", "measured_rungs": len(cells)}
    half = len(cells) // 2
    early = statistics.median(c["drift"] for c in cells[:half])
    late = statistics.median(c["drift"] for c in cells[half:])
    spreads = [c["spread"] for c in cells[half:] if c["spread"] is not None]
    spread = statistics.median(spreads) if spreads else None
    flow = flow or {}
    evidence = {"early_median_drift": round(early, 4), "late_median_drift": round(late, 4),
                "late_median_spread": None if spread is None else round(spread, 4),
                "measured_rungs": len(cells), "n_range": [cells[0]["n"], cells[-1]["n"]],
                "asymptote": flow.get("d_star"), "asymptote_gap": flow.get("asymptote_gap"),
                "omega": flow.get("omega")}
    if spread is not None and spread > NOISE_SPREAD and spread >= late:
        verdict = "NOISE_DOMINATED"
    elif spread is not None and late <= spread:
        verdict = "FLAT_ACCURATE"
    elif late < 0.6 * early:
        verdict = "IMPROVES_WITH_N"
    elif spread is not None and late > 2.0 * spread:
        verdict = "PLATEAU_BIASED"
    else:
        verdict = "FLAT"
    return {"verdict": verdict, **evidence}


def bias_at_rung(rows: list[dict], channel: str, n: int) -> dict | None:
    cells = _measured_cells(rows, channel)
    if not cells:
        return None
    if n <= cells[0]["n"]:
        c = cells[0]
        return {"bias": c["bias"], "spread": c["spread"], "from_n": c["n"], "mode": "nearest"}
    if n >= cells[-1]["n"]:
        c = cells[-1]
        return {"bias": c["bias"], "spread": c["spread"], "from_n": c["n"], "mode": "nearest"}
    for lo, hi in zip(cells, cells[1:], strict=False):
        if lo["n"] <= n <= hi["n"]:
            t = (math.log(n) - math.log(lo["n"])) / (math.log(hi["n"]) - math.log(lo["n"]))
            spread = None
            if lo["spread"] is not None and hi["spread"] is not None:
                spread = (1 - t) * lo["spread"] + t * hi["spread"]
            return {"bias": (1 - t) * lo["bias"] + t * hi["bias"], "spread": spread,
                    "from_n": [lo["n"], hi["n"]], "mode": "log-interpolated"}
    return None


def _waiver_active(waiver: dict, now_iso: str) -> bool:
    expires = str(waiver.get("expires_utc") or "")
    return bool(expires) and expires > now_iso


def _apply_waivers(families: dict, waivers: list[dict], now_iso: str) -> tuple[list, list]:
    active = [w for w in waivers if _waiver_active(w, now_iso)]
    expired = [w for w in waivers if not _waiver_active(w, now_iso)]
    applied = []
    for name, family in families.items():
        for row in family["rows"]:
            for channel, cell in row["channels"].items():
                if cell["status"] not in FAILING_STATUSES:
                    continue
                for waiver in active:
                    if waiver.get("family") != name or waiver.get("channel") != channel:
                        continue
                    if waiver.get("n") is not None and int(waiver["n"]) != int(row["n"]):
                        continue
                    cell["unwaived_status"] = cell["status"]
                    cell["status"] = "WAIVED"
                    cell["waiver"] = {k: waiver.get(k) for k in ("reason", "expires_utc", "declared_by")}
                    applied.append({"family": name, "channel": channel, "n": row["n"],
                                    "reason": waiver.get("reason"),
                                    "expires_utc": waiver.get("expires_utc")})
                    break
    return applied, [{k: w.get(k) for k in ("family", "channel", "n", "reason", "expires_utc")}
                     for w in expired]


def deviation_report(families: list[dict], cells: dict, *, seeds: int,
                     max_nodes: int | None = None, waivers: list[dict] | None = None,
                     now_iso: str | None = None) -> dict:
    now_iso = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out_families: dict[str, dict] = {}
    for family in families:
        rows = [_rung_row(family, rung, cells, seeds) for rung in family_ladder(family, max_nodes)]
        measured_rows = [r for r in rows if r["seeds_present"]]
        channels = sorted({ch for row in measured_rows for ch in row["channels"]})
        flow = ({ch: finite_size_fit(measured_rows, ch) for ch in channels}
                if family["expectation"] == "MEASURE" else {})
        out_families[family["name"]] = {
            "expectation": family["expectation"],
            "why": family.get("why", ""),
            "theory": dict(family.get("theory") or {}),
            "refusal_gated_from": dict(family.get("refusal_gated_from") or {}),
            "graph_varies_per_seed": bool(family.get("graph_varies_per_seed")),
            "dispersion_meaning": dispersion_meaning(family),
            "rows": rows,
            "trends": {ch: ladder_trend(measured_rows, ch) for ch in channels},
            "finite_size_flow": flow,
            "convergence": ({ch: convergence_verdict(measured_rows, flow.get(ch), ch)
                             for ch in channels} if family["expectation"] == "MEASURE" else {}),
            "cells_planned": len(rows) * int(seeds),
            "cells_present": sum(r["seeds_present"] for r in rows),
        }
    applied, expired = _apply_waivers(out_families, list(waivers or []), now_iso)
    _annotate_structure(families, out_families, cells)

    refusals = []
    convergence = []
    for name, family in out_families.items():
        judged = [row for row in family["rows"] if row["complete"]]
        gated = [
            {"n": row["n"], "channel": ch, "status": v["status"], "drift": v.get("drift"),
             "tolerance": v.get("tolerance")}
            for row in judged for ch, v in row["channels"].items()
            if v["status"] in FAILING_STATUSES]
        family["gated_failures"] = gated
        family["false_confidence_readings"] = sum(
            1 for row in judged for v in row["channels"].values()
            if v["status"] == "FALSE_CONFIDENCE")
        complete = all(r["complete"] for r in family["rows"])
        family["complete"] = complete
        family["verdict"] = ("FAIL" if gated else ("PASS" if complete else "INCOMPLETE"))
        for row in family["rows"]:
            for ch, v in row["channels"].items():
                for gate, count in (v.get("refusal_gates") or {}).items():
                    refusals.append({"family": name, "n": row["n"], "channel": ch,
                                     "gate": gate, "count": count,
                                     "status": v["status"]})
        for ch, verdict in (family.get("convergence") or {}).items():
            convergence.append({"family": name, "channel": ch, **verdict})

    bias_table = []
    for name, family in out_families.items():
        if family["expectation"] != "MEASURE":
            continue
        klass = ("fractal" if name in FRACTAL_FAMILIES
                 else "lattice" if name in LATTICE_FAMILIES else "other")
        measured_rows = [r for r in family["rows"] if r["seeds_present"]]
        for ch in sorted({ch for row in measured_rows for ch in row["channels"]}):
            for n in CAMPAIGN_RUNGS:
                at = bias_at_rung(measured_rows, ch, n)
                if at is not None:
                    bias_table.append({"family": name, "class": klass, "channel": ch, "n": n,
                                       "bias": round(at["bias"], 4),
                                       "spread": None if at["spread"] is None else round(at["spread"], 4),
                                       "basis": at["mode"], "from_n": at["from_n"]})
    summary: dict[tuple, list] = {}
    for entry in bias_table:
        summary.setdefault((entry["class"], entry["channel"], entry["n"]), []).append(entry["bias"])
    reading_rule = [{"class": k[0], "channel": k[1], "n": k[2],
                     "median_bias": round(statistics.median(v), 4), "families": len(v)}
                    for k, v in sorted(summary.items())]

    failing = sorted(n for n, f in out_families.items() if f["verdict"] == "FAIL")
    incomplete = sorted(n for n, f in out_families.items() if f["verdict"] == "INCOMPLETE")
    verdict = "FAIL" if failing else ("INCOMPLETE" if incomplete else "PASS")
    planned = sum(f["cells_planned"] for f in out_families.values())
    present = sum(f["cells_present"] for f in out_families.values())
    return {
        "verdict": verdict,
        "failing_families": failing,
        "incomplete_families": incomplete,
        "summary_line": _summary_line(verdict, failing, incomplete, present, planned, seeds, applied),
        "seeds": int(seeds),
        "max_nodes": max_nodes,
        "cells": {"planned": planned, "present": present, "missing": planned - present},
        "families": out_families,
        "refusals": refusals,
        "where_more_nodes_help": [c for c in convergence if c["verdict"] == "IMPROVES_WITH_N"],
        "where_more_nodes_do_not_help": [c for c in convergence if c["verdict"] == "PLATEAU_BIASED"],
        "already_accurate": [c for c in convergence if c["verdict"] == "FLAT_ACCURATE"],
        "needs_more_seeds_not_more_nodes": [c for c in convergence if c["verdict"] == "NOISE_DOMINATED"],
        "bias_at_campaign_rungs": bias_table,
        "reading_rule": reading_rule,
        "waivers_applied": applied,
        "waivers_expired": expired,
        "derived_utc": now_iso,
    }


def _annotate_structure(families: list[dict], out_families: dict, cells: dict) -> None:
    from graph_scale_dynamics.calibration.cells import extension_ladder
    from graph_scale_dynamics.calibration.contract import EXTENSION_SEEDS
    from graph_scale_dynamics.calibration.structure import local_exponents

    for family in families:
        entry = out_families.get(family["name"])
        if entry is None:
            continue
        extension = []
        for rung in extension_ladder(family):
            seeds = max(EXTENSION_SEEDS, sum(1 for k in cells if k.startswith(
                f"{family['name']}:{rung['parameter']}:")))
            row = _rung_row(family, rung, cells, seeds)
            if row["seeds_present"]:
                extension.append(row)
        entry["extension_rows"] = extension
        local_exponents(entry["rows"] + extension)


def _summary_line(verdict, failing, incomplete, present, planned, seeds, applied) -> str:
    if verdict == "FAIL":
        return (f"FAIL: {', '.join(failing)} out of declared tolerance or lost a refusal; "
                "investigate before collecting data")
    if verdict == "INCOMPLETE":
        return (f"INCOMPLETE: {present} of {planned} cells present; "
                f"{', '.join(incomplete)} not fully measured; the fleet must not start")
    waived = f", {len(applied)} cell(s) waived" if applied else ""
    return (f"PASS: every family within declared tolerance and every refusal held, "
            f"{present} cells at {seeds} seed(s){waived}")
