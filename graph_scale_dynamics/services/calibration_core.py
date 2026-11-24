from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

from graph_scale_dynamics.domain import chain_list as CL


def run_trial(*, seeds: int = 2, verbose: bool = True) -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements.calibration import ANCHORS
    from graph_scale_dynamics.measurements.estimators import _measure_graph
    from graph_scale_dynamics.scaleflow.flow import rung_summary

    stages: list[dict] = []
    failures: list[str] = []

    def note(stage, ok, detail=""):
        stages.append({"stage": stage, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append(f"{stage}: {detail}")
        if verbose:
            print(f"  [{'ok ' if ok else 'FAIL'}] {stage}" + (f"  {detail}" if detail else ""))

    measured: dict[str, dict] = {}
    for anchor in ANCHORS:
        name = anchor["name"]
        n, edges = anchor["build"]()
        per_seed = []
        for seed in range(seeds):
            result, _curves = _measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)
            per_seed.append(result)
        summary = rung_summary(per_seed)
        got = {}
        for channel in ("d_s", "d_B", "d_w"):
            stat = summary.get(channel)
            if isinstance(stat, dict) and isinstance(stat.get("mean"), (int, float)):
                got[channel] = float(stat["mean"])
        measured[name] = got
        for channel, expected in anchor["expect"].items():
            tolerance = anchor["tolerance"][channel]
            actual = got.get(channel)
            if actual is None:
                note(f"{name}: {channel} measured", False,
                     f"no estimate; the estimator refused a graph whose {channel} is known")
                continue
            drift = abs(actual - expected)
            note(f"{name}: {channel} = {actual:.4f} (theory {expected:.4f})", drift <= tolerance,
                 "" if drift <= tolerance else f"drift {drift:.4f} exceeds {tolerance}")
    return {"contract": "gsd-pipeline-trial-2", "anchors": len(ANCHORS), "measured": measured,
            "stages": stages, "failures": failures, "passed": not failures}


CONTRACT = "gsd-probe-calibration-1"
DEFAULT_NS = (64, 256, 1024, 4096)
DEFAULT_RAMP = (30, 60, 120, 240, 480, 960, 1920)
DEFAULT_FLOOR = 8.0
DEFAULT_CANDIDATE = "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json"

def _df_theory(anchor_name: str) -> float | None:
    if anchor_name == "periodic_square_lattice_48":
        return 2.0
    if anchor_name == "sierpinski_gasket_level_7":
        from graph_scale_dynamics.measurements.calibration import SIERPINSKI_DF
        return float(SIERPINSKI_DF)
    return None


def probe_section(trial: dict) -> dict:
    from graph_scale_dynamics.measurements.calibration import ANCHORS

    rows: list[dict] = []
    einstein: list[dict] = []
    for anchor in ANCHORS:
        name = anchor["name"]
        got = (trial.get("measured") or {}).get(name) or {}
        for channel, expected in anchor["expect"].items():
            tolerance = float(anchor["tolerance"][channel])
            measured = got.get(channel)
            drift = None if measured is None else abs(float(measured) - float(expected))
            rows.append({
                "anchor": name,
                "channel": channel,
                "measured": None if measured is None else float(measured),
                "theory": float(expected),
                "drift": drift,
                "tolerance": tolerance,
                "status": ("REFUSED" if measured is None
                           else ("PASS" if drift <= tolerance else "DRIFT")),
                "why": anchor.get("why", ""),
            })
        closure = einstein_closure(name, got)
        if closure is not None:
            einstein.append(closure)
    return {
        "rows": rows,
        "einstein": einstein,
        "pipeline_passed": bool(trial.get("passed")),
        "stage_failures": list(trial.get("failures") or ()),
    }


def einstein_closure(anchor_name: str, measured: dict) -> dict | None:
    d_s = measured.get("d_s")
    d_w = measured.get("d_w")
    if d_s is None or d_w is None or not d_w:
        return None
    closures = []
    theory_df = _df_theory(anchor_name)
    if theory_df is not None:
        predicted = 2.0 * theory_df / float(d_w)
        closures.append({"d_f_source": "theory d_f", "d_f": theory_df,
                         "d_s_from_relation": predicted,
                         "residual": float(d_s) - predicted})
    if measured.get("d_B") is not None:
        d_f = float(measured["d_B"])
        predicted = 2.0 * d_f / float(d_w)
        closures.append({"d_f_source": "measured d_B", "d_f": d_f,
                         "d_s_from_relation": predicted,
                         "residual": float(d_s) - predicted})
    if not closures:
        return None
    return {
        "anchor": anchor_name,
        "d_s_measured": float(d_s),
        "d_w_measured": float(d_w),
        "closures": closures,
    }


def run_probes(seeds: int) -> dict:
    started = time.monotonic()
    trial = run_trial(seeds=seeds, verbose=False)
    section = probe_section(trial)
    section["seeds"] = int(seeds)
    section["seconds"] = round(time.monotonic() - started, 2)
    return section


def scan_point(spec: dict, n: int, seed: int, sweeps: int,
               record_points: int = 240) -> dict:
    from graph_scale_dynamics.scaleflow.engine_door import run_simulation
    from graph_scale_dynamics.measurements.certificate import equilibration_certificate, integrated_autocorrelation_time

    started = time.monotonic()
    envelope = run_simulation(spec, int(n), int(seed), target_sweeps=int(sweeps),
                              record_points=int(record_points))
    certificate = equilibration_certificate(envelope) or {}
    trajectory = CL.trajectory(envelope, CL.FROM_EMPTY)
    late = trajectory[int(len(trajectory) * 0.4):]
    tau_points = integrated_autocorrelation_time(
        [row["energy"] for row in late]) if len(late) >= 10 else None
    tau_rel_se = (math.sqrt(2.0 * (2.0 * tau_points + 1.0) / len(late))
                  if tau_points is not None and len(late) else None)
    return {
        "n": int(n),
        "seed": int(seed),
        "sweeps": int(sweeps),
        "record_points": int(record_points),
        "tau_sweeps": certificate.get("tau_int_sweeps"),
        "tau_rel_se": None if tau_rel_se is None else round(float(tau_rel_se), 4),
        "ess": certificate.get("effective_samples"),
        "tau_points": None if tau_points is None else float(tau_points),
        "resolved": bool(tau_points is not None and tau_points >= 1.0),
        "wall_seconds": round(time.monotonic() - started, 3),
    }


def summarize_scan(points: list[dict], *, floor: float, record_points: int = 240) -> dict:
    grid: dict[int, dict[int, dict]] = {}
    for point in points:
        cell = grid.setdefault(int(point["n"]), {}).setdefault(int(point["sweeps"]), {
            "ess_values": [], "resolved_all": True, "tau_sweeps": []})
        if point.get("ess") is not None:
            cell["ess_values"].append(float(point["ess"]))
        if point.get("tau_sweeps") is not None:
            cell["tau_sweeps"].append(float(point["tau_sweeps"]))
        cell["resolved_all"] = cell["resolved_all"] and bool(point.get("resolved"))

    by_n: list[dict] = []
    required: dict[int, float] = {}
    for n in sorted(grid):
        cells = []
        crossing = None
        any_crossing = None
        all_crossing = None
        for sweeps in sorted(grid[n]):
            cell = grid[n][sweeps]
            values = cell["ess_values"]
            median_ess = statistics.median(values) if values else None
            median_tau = (statistics.median(cell["tau_sweeps"])
                          if cell["tau_sweeps"] else None)
            meets = bool(median_ess is not None and median_ess >= floor
                         and cell["resolved_all"])
            if meets and crossing is None:
                crossing = sweeps
            if (values and max(values) >= floor and cell["resolved_all"]
                    and any_crossing is None):
                any_crossing = sweeps
            if (values and min(values) >= floor and cell["resolved_all"]
                    and all_crossing is None):
                all_crossing = sweeps
            cells.append({"sweeps": sweeps, "median_ess": median_ess,
                          "ess_min": min(values) if values else None,
                          "ess_max": max(values) if values else None,
                          "median_tau_sweeps": median_tau,
                          "resolved": cell["resolved_all"], "meets_floor": meets})
        if crossing is not None:
            required[n] = float(crossing)
        by_n.append({"n": n, "cells": cells, "required_sweeps": crossing,
                     "crossing_band": [any_crossing, all_crossing]})

    return {"by_n": by_n, "floor": float(floor),
            "ess_recording_ceiling": round(0.6 * record_points / 2.0, 1),
            "required_sweeps": {str(k): v for k, v in required.items()},
            "law": suggest_law(required)}


def suggest_law(required: dict[int, float]) -> dict:
    pairs = sorted((int(n), float(s)) for n, s in required.items() if s > 0)
    if len(pairs) < 2:
        return {"status": "insufficient",
                "detail": f"{len(pairs)} rung(s) crossed the floor; need at least 2"}
    shapes = {
        "constant": lambda n: 1.0,
        "log2(N)": lambda n: math.log2(n),
        "sqrt(N)": lambda n: math.sqrt(n),
        "linear(N)": lambda n: float(n),
    }
    fits = []
    for name, shape in shapes.items():
        logs = [math.log(s) - math.log(shape(n)) for n, s in pairs]
        a = math.exp(sum(logs) / len(logs))
        rms = math.sqrt(sum((math.log(s) - math.log(a * shape(n))) ** 2
                            for n, s in pairs) / len(pairs))
        fits.append({"law": name, "coefficient": round(a, 2),
                     "log_rms": round(rms, 4)})
    fits.sort(key=lambda f: f["log_rms"])
    return {"status": "fitted", "fits": fits, "best": fits[0]["law"],
            "points_used": [{"n": n, "required_sweeps": s} for n, s in pairs]}


def run_sweep_scan(*, spec_path: Path, ns, ramp, seeds: int, floor: float,
                   record_points: int = 2000, verbose: bool = True) -> dict:
    spec = json.loads(Path(spec_path).read_text())
    points: list[dict] = []
    started = time.monotonic()
    for n in ns:
        for sweeps in ramp:
            for seed in range(seeds):
                point = scan_point(spec, n, seed, sweeps,
                                   record_points=record_points)
                points.append(point)
                if verbose:
                    ess = point["ess"]
                    print(f"  N={n:>5} sweeps={sweeps:>5} seed={seed} "
                          f"ess={'—' if ess is None else f'{ess:7.2f}'} "
                          f"{'resolved' if point['resolved'] else 'UNRESOLVED'} "
                          f"({point['wall_seconds']}s)")
    summary = summarize_scan(points, floor=floor, record_points=record_points)
    summary.update({
        "reference": Path(spec_path).stem,
        "candidate_spec": str(spec_path),
        "candidate_dynamics": spec.get("dynamics"),
        "ns": [int(n) for n in ns],
        "ramp": [int(s) for s in ramp],
        "seeds": int(seeds),
        "points": points,
        "seconds": round(time.monotonic() - started, 1),
    })
    return summary


CALIBRATION_MIN_AVAILABLE_BYTES = 12 * 1024 ** 3
CALIBRATION_BYTES_PER_NODE = 4 * 1024
CALIBRATION_MEMORY_WAIT_SECONDS = 20 * 60


def _wait_for_host_memory(nodes: int) -> str | None:
    import os
    from graph_scale_dynamics.measurements.calibration import STANDARD_LADDER_MAX_NODES
    if int(nodes) <= STANDARD_LADDER_MAX_NODES:
        return None
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return None
    floor = int(os.environ.get("GSD_CALIBRATION_MIN_AVAILABLE_GIB",
                               CALIBRATION_MIN_AVAILABLE_BYTES // 1024 ** 3)) * 1024 ** 3
    need = max(floor, int(nodes) * CALIBRATION_BYTES_PER_NODE + floor // 2)
    deadline = time.monotonic() + CALIBRATION_MEMORY_WAIT_SECONDS
    while True:
        available = int(psutil.virtual_memory().available)
        if available >= need:
            return None
        if time.monotonic() >= deadline:
            return (f"host memory {available / 1024 ** 3:.1f} GiB available, rung needs "
                    f"{need / 1024 ** 3:.1f} GiB; deferred after "
                    f"{CALIBRATION_MEMORY_WAIT_SECONDS // 60} min")
        time.sleep(30)


SUMMARY_DROPS = {
    "d_s": "restructured into channels['d_s'] beside theory, drift, tolerance and status",
    "d_B": "restructured into channels['d_B']",
    "d_w": "restructured into channels['d_w']",
    "d_V": "restructured into channels['d_V'] (its per-seed key is d_V_window)",
    "seeds": "the cell states its own seed count, from the argument rather than the summary",
    "summary_contract": "a property of the summary, not a measurement of this graph",
}


def probe_ladder_point(family: dict, parameter, seeds: int) -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements.estimators import _measure_graph
    from graph_scale_dynamics.scaleflow.flow import rung_summary

    n, edges = family["build"](parameter)
    per_seed = []
    started = time.monotonic()
    for seed in range(int(seeds)):
        result, _curves = _measure_graph(n, edges, np.random.default_rng(seed),
                                         measure_geometry=True)
        per_seed.append(result)
    summary = rung_summary(per_seed)
    measured = {}
    per_seed_values: dict[str, list] = {}
    value_keys = {"d_s": "d_s", "d_B": "d_B", "d_w": "d_w", "d_V": "d_V_window"}
    for channel, value_key in value_keys.items():
        stat = summary.get(channel)
        if isinstance(stat, dict) and isinstance(stat.get("mean"), (int, float)):
            measured[channel] = float(stat["mean"])
        per_seed_values[channel] = [
            (float(r[channel][value_key]) if isinstance(r.get(channel), dict)
             and r[channel].get("valid") and isinstance(r[channel].get(value_key), (int, float))
             else None)
            for r in per_seed]
    diffusive = summary.get("d_s_diffusive_evidence")
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance

    theory = dict(family.get("theory") or {})
    refusal_expected = family.get("expectation") == "REFUSE"
    channels = {}
    for channel in sorted(set(theory) | set(measured)):
        value = measured.get(channel)
        expected = theory.get(channel)
        drift = (abs(value - expected)
                 if value is not None and expected is not None else None)
        tolerance = (None if refusal_expected
                     else ladder_tolerance(family["name"], channel, n))
        if refusal_expected:
            gating = family.get("refusal_gated_from") or {}
            if value is None:
                status = "REFUSED_OK"
            elif channel not in gating or int(n) < int(gating[channel]):
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
        seeds_values = per_seed_values.get(channel, [])
        finite = [v for v in seeds_values if v is not None]
        channels[channel] = {
            "measured": value,
            "theory": expected,
            "drift": drift,
            "tolerance": tolerance,
            "status": status,
            "per_seed": seeds_values,
            "seed_std": (statistics.pstdev(finite) if len(finite) >= 2 else None),
            "seed_refusals": sum(1 for v in seeds_values if v is None),
        }
        if channel == "d_s" and diffusive:
            channels[channel]["diffusive_evidence"] = diffusive
    if refusal_expected and not channels:
        for channel in ("d_s", "d_B", "d_w", "d_V"):
            channels[channel] = {"measured": None, "theory": None,
                                 "drift": None, "status": "REFUSED_OK"}
    cell = {"parameter": parameter, "n": int(n), "channels": channels,
            "seeds": int(seeds),
            "wall_seconds": round(time.monotonic() - started, 2)}
    for key, value in summary.items():
        if key in SUMMARY_DROPS or key in cell or value is None:
            continue
        cell[key] = value
    return cell


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
        "asymptote_gap": (round(best["d_star"] - float(theory), 4)
                          if theory is not None else None),
        "contracting": bool(not at_bound and best["omega"] > 0),
    }


def _ladder_trend(rows: list[dict], channel: str) -> str | None:
    drifts = [(row["n"], row["channels"][channel]["drift"]) for row in rows
              if channel in row["channels"]
              and row["channels"][channel]["drift"] is not None]
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


def run_probe_ladders(families=None, *, seeds: int = 2, max_nodes: int | None = None,
                      verbose: bool = True, on_rung=None) -> dict:
    from graph_scale_dynamics.measurements.calibration import (
        CALIBRATION_FAMILIES, STANDARD_LADDER_MAX_NODES, family_rung_size,
    )

    selected = list(families) if families else [f["name"] for f in CALIBRATION_FAMILIES]
    by_name = {f["name"]: f for f in CALIBRATION_FAMILIES}
    out_families = {}
    started = time.monotonic()
    tier = ("deep" if max_nodes is None
            else "standard" if int(max_nodes) >= STANDARD_LADDER_MAX_NODES
            else "truncated")
    planned = {name: [p for p in by_name[name]["ladder"]
                      if max_nodes is None
                      or family_rung_size(by_name[name], p) <= int(max_nodes)]
               for name in selected}
    total_rungs = sum(len(v) for v in planned.values())
    done_rungs = 0
    deferred: list[dict] = []
    for name in selected:
        family = by_name[name]
        rows = []
        for parameter in planned[name]:
            shortfall = _wait_for_host_memory(family_rung_size(family, parameter))
            if shortfall is not None:
                deferred.append({"family": name, "n": family_rung_size(family, parameter),
                                 "reason": shortfall})
                if verbose:
                    print(f"  {name:<26} n={family_rung_size(family, parameter):>8} DEFERRED: {shortfall}")
                continue
            row = probe_ladder_point(family, parameter, seeds)
            rows.append(row)
            done_rungs += 1
            if on_rung is not None:
                partial = dict(out_families)
                partial[name] = {
                    "expectation": family["expectation"], "why": family.get("why", ""),
                    "theory": dict(family.get("theory") or {}), "rows": list(rows),
                    "trends": {}, "finite_size_flow": {},
                    "false_confidence_readings": sum(
                        1 for r in rows for v in r["channels"].values()
                        if v["status"] == "FALSE_CONFIDENCE"),
                    "gated_failures": [], "verdict": None, "partial": True,
                }
                on_rung({
                    "families": partial, "seeds": int(seeds), "max_nodes": max_nodes,
                    "tier": tier, "verdict": "IN_PROGRESS", "failing_families": [],
                    "in_progress": {"family": name, "n": row["n"],
                                    "rungs_done": done_rungs, "rungs_total": total_rungs,
                                    "elapsed_seconds": round(time.monotonic() - started, 1)},
                    "seconds": round(time.monotonic() - started, 1),
                })
            if verbose:
                summary = " ".join(
                    f"{ch}={'—' if v['measured'] is None else format(v['measured'], '.3f')}"
                    f"({v['status'][0]})" for ch, v in sorted(row["channels"].items()))
                print(f"  {name:<26} n={row['n']:>6} {summary} "
                      f"({row['wall_seconds']}s)")
        channels = sorted({ch for row in rows for ch in row["channels"]})
        trends = {ch: _ladder_trend(rows, ch) for ch in channels}
        flow = ({ch: finite_size_fit(rows, ch) for ch in channels}
                if family["expectation"] == "MEASURE" else {})
        false_confidence = sum(
            1 for row in rows for v in row["channels"].values()
            if v["status"] == "FALSE_CONFIDENCE")
        gated_failures = [
            {"n": row["n"], "channel": ch, "status": v["status"],
             "drift": v["drift"], "tolerance": v["tolerance"]}
            for row in rows for ch, v in row["channels"].items()
            if v["status"] in ("OUT_OF_TOLERANCE", "REFUSED", "FALSE_CONFIDENCE")]
        out_families[name] = {
            "expectation": family["expectation"],
            "why": family.get("why", ""),
            "theory": dict(family.get("theory") or {}),
            "rows": rows,
            "trends": trends,
            "finite_size_flow": flow,
            "false_confidence_readings": false_confidence,
            "gated_failures": gated_failures,
            "verdict": "PASS" if not gated_failures else "FAIL",
        }
    failures = {name: fam["gated_failures"] for name, fam in out_families.items()
                if fam["verdict"] == "FAIL"}
    return {"families": out_families, "seeds": int(seeds),
            "max_nodes": max_nodes, "tier": tier,
            "deferred_rungs": deferred,
            "verdict": "PASS" if not failures else "FAIL",
            "failing_families": sorted(failures),
            "seconds": round(time.monotonic() - started, 1)}


def load_waivers(var: "Path") -> list[dict]:
    path = Path(var) / "calibration" / "waivers.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [w for w in (data if isinstance(data, list) else data.get("waivers", []))
            if isinstance(w, dict) and w.get("family") and w.get("channel")]
