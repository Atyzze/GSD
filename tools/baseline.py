#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.domain.science_identity import digest, frozen_paths
from graph_scale_dynamics.domain.version import BUILD_NUMBER
from graph_scale_dynamics.operations import dev_mode
from graph_scale_dynamics.research.compute_efficiency import (
    COMPARISON_MIN_ATTEMPTS, COMPARISON_TOLERANCE, compare_cost_by_n,
)
from graph_scale_dynamics.calibration.instrument_check import (
    GATING_CHANNELS, TOP_RUNG_STANDARD, instrument_check,
)

FREEZE_MANIFEST = ROOT / "tests" / "fixtures" / "science_freeze.json"
CALIBRATION_TABLE = ROOT / "calibration" / "probe_calibration.json"
BASELINE_DIR = ROOT / "calibration" / "baselines"

POPULATION_SHIFT_FACTOR = 2.0

EXIT_OK, EXIT_FREEZE, EXIT_CALIBRATION, EXIT_ESTIMATORS, EXIT_COST, EXIT_UNRUNNABLE = 0, 2, 3, 4, 5, 6

REQUIRED_FAMILIES = (
    "periodic_ring",
    "periodic_square_lattice",
    "periodic_cubic_lattice",
    "periodic_hypercubic_lattice_4d",
    "sierpinski_gasket",
    "uniform_random_tree",
    "random_4_regular",
)

CHECKS = ("freeze", "calibration", "estimators", "cost")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _cost_rows(payload: dict) -> list[dict] | None:
    if isinstance(payload, list):
        return payload
    for candidate in (payload, payload.get("body") or {}):
        rows = candidate.get("cost_by_n")
        if isinstance(rows, list):
            return rows
    return None


def check_freeze() -> dict:
    if not FREEZE_MANIFEST.exists():
        return {"ok": False, "reason": f"no freeze manifest at {FREEZE_MANIFEST}"}
    manifest = _load(FREEZE_MANIFEST)
    recorded = manifest.get("files") or {}
    stale_build = manifest.get("baseline_build") != BUILD_NUMBER
    moved, missing = [], []
    for relative in frozen_paths():
        if relative not in recorded:
            missing.append(relative)
        elif digest(relative) != recorded[relative]:
            moved.append(relative)
    advisory = dev_mode.relaxation_active("science_freeze_advisory")
    return {
        "ok": not moved and not missing and not stale_build,
        "stale_build": stale_build,
        "baseline_build": manifest.get("baseline_build"),
        "current_build": BUILD_NUMBER,
        "frozen_sources": len(recorded),
        "moved": sorted(moved),
        "unrecorded": sorted(missing),
        "advisory": advisory,
    }


def check_calibration() -> dict:
    if not CALIBRATION_TABLE.exists():
        return {"ok": False, "reason": f"no calibration table at {CALIBRATION_TABLE}"}
    table = _load(CALIBRATION_TABLE)
    result = instrument_check(table)
    present = set(result.get("top_rung") or {}) | {
        name for name in (table.get("families") or {})}
    absent = [name for name in REQUIRED_FAMILIES if name not in present]
    gating = result.get("gating_misses") or []
    return {
        "ok": bool(result.get("ok")) and not absent,
        "ladder_verdict": result.get("ladder_verdict"),
        "standard": TOP_RUNG_STANDARD,
        "gates_on": list(GATING_CHANNELS),
        "families_absent": absent,
        "failing_families": result.get("failing_families"),
        "theory_drift": result.get("theory_drift"),
        "false_confidence": result.get("false_confidence"),
        "gating_misses": gating,
        "misses": result.get("misses"),
        "top_rung": result.get("top_rung"),
        "estimator_fingerprint": table.get("estimator_fingerprint"),
        "science_fingerprint": table.get("science_fingerprint"),
    }


def check_estimators(sample: int) -> dict:
    command = [sys.executable, str(ROOT / "tools" / "adopt_calibration.py"),
               "--sample", str(sample)]
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "command": command}
    return {
        "ok": done.returncode == 0,
        "returncode": done.returncode,
        "command": " ".join(command),
        "tail": (done.stdout or done.stderr or "").strip().splitlines()[-6:],
    }


def check_cost(baseline_path: Path, candidate_path: Path | None,
               tolerance: float, min_attempts: int) -> dict:
    if not baseline_path.exists():
        return {"ok": False, "reason": f"no stored baseline at {baseline_path}; "
                                       "seed one with --adopt"}
    baseline_payload = _load(baseline_path)
    baseline_rows = _cost_rows(baseline_payload)
    if baseline_rows is None:
        return {"ok": False, "reason": f"{baseline_path} carries no cost_by_n"}
    if candidate_path is None:
        return {"ok": None, "reason": "no candidate bundle given; pass --candidate "
                                      "to compare a fresh run",
                "baseline_cells": len(baseline_rows)}
    if not candidate_path.exists():
        return {"ok": False, "reason": f"no candidate bundle at {candidate_path}"}
    candidate_rows = _cost_rows(_load(candidate_path))
    if candidate_rows is None:
        return {"ok": False, "reason": f"{candidate_path} carries no cost_by_n"}
    comparison = compare_cost_by_n(baseline_rows, candidate_rows,
                                   min_attempts=min_attempts, tolerance=tolerance)
    shifted = []
    for record in (comparison["regressions"] + comparison["improvements"]
                   + comparison["unchanged"]):
        before, after = record["baseline_attempts"], record["candidate_attempts"]
        if before and after and max(after / before, before / after) >= POPULATION_SHIFT_FACTOR:
            record["population_shift"] = round(after / before, 2)
            shifted.append(record)
    comparison["population_shifted_cells"] = shifted
    real = [r for r in comparison["regressions"] if "population_shift" not in r]
    comparison["regressions_excluding_shifted"] = real
    comparison["ok"] = not real
    comparison["baseline"] = str(baseline_path)
    comparison["candidate"] = str(candidate_path)
    return comparison


def _adopt(source: Path, destination: Path) -> int:
    if not source.exists():
        print(f"baseline: no such bundle {source}")
        return EXIT_UNRUNNABLE
    payload = _load(source)
    stamp = ((payload.get("producer") or {}).get("run_provenance")
             or payload.get("run_mode") or {})
    certified = stamp.get("certified_run")
    if certified is False or dev_mode.enabled():
        print("baseline: refusing to adopt from a development-mode run.")
        print("  A baseline taken with gates open cannot say whether a later change")
        print("  moved the science or whether the gates did. Re-run certified first.")
        return EXIT_UNRUNNABLE
    rows = _cost_rows(payload)
    if rows is None:
        print(f"baseline: {source} carries no cost_by_n")
        return EXIT_UNRUNNABLE
    thin = [(row.get("n"), cell.get("sweeps_multiplier"), cell.get("attempts"))
            for row in rows for cell in (row.get("by_sweeps_multiplier") or [])
            if int(cell.get("attempts") or 0) < COMPARISON_MIN_ATTEMPTS]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(
        {"contract": "gsd-cost-baseline-1", "source": str(source),
         "adopted_from_build": (payload.get("build_number") or (payload.get("producer") or {}).get("build_number")),
         "certified_run": certified, "cost_by_n": rows},
        indent=1, sort_keys=True))
    cells = sum(len(row.get("by_sweeps_multiplier") or []) for row in rows)
    print(f"baseline: adopted {cells} cells from {source} -> {destination}")
    if thin:
        print(f"  {len(thin)} cell(s) below the {COMPARISON_MIN_ATTEMPTS}-attempt floor "
              "and unusable for comparison:")
        for n, multiplier, attempts in thin:
            print(f"    N={n} multiplier={multiplier} attempts={attempts}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/baseline.py: see docs/TOOLS.md")
    parser.add_argument("--baseline", type=Path, default=BASELINE_DIR / "276-certified.json")
    parser.add_argument("--candidate", type=Path,
                        help="a fresh 16-efficiency.json (or report bundle) to compare on cost")
    parser.add_argument("--adopt", type=Path, metavar="BUNDLE",
                        help="store BUNDLE as the cost baseline and exit; refuses a relaxed run")
    parser.add_argument("--skip", action="append", default=[], choices=CHECKS,
                        help="skip a check; repeatable")
    parser.add_argument("--sample", type=int, default=2, help="cells for the estimator gate")
    parser.add_argument("--tolerance", type=float, default=COMPARISON_TOLERANCE)
    parser.add_argument("--min-attempts", type=int, default=COMPARISON_MIN_ATTEMPTS)
    parser.add_argument("--json", action="store_true", help="emit the full result payload")
    args = parser.parse_args(argv)

    if args.adopt is not None:
        return _adopt(args.adopt, args.baseline)

    banner = dev_mode.banner()
    if banner:
        print(banner)

    results: dict[str, dict] = {}
    if "freeze" not in args.skip:
        results["freeze"] = check_freeze()
    if "calibration" not in args.skip:
        results["calibration"] = check_calibration()
    if "estimators" not in args.skip:
        results["estimators"] = check_estimators(args.sample)
    if "cost" not in args.skip:
        results["cost"] = check_cost(args.baseline, args.candidate,
                                     args.tolerance, args.min_attempts)

    exit_for = {"freeze": EXIT_FREEZE, "calibration": EXIT_CALIBRATION,
                "estimators": EXIT_ESTIMATORS, "cost": EXIT_COST}
    code = EXIT_OK
    lines = []
    for name in CHECKS:
        outcome = results.get(name)
        if outcome is None:
            lines.append(f"  {name:<12} skipped")
            continue
        if outcome["ok"] is None:
            lines.append(f"  {name:<12} n/a      {outcome.get('reason', '')}")
            continue
        if outcome["ok"]:
            lines.append(f"  {name:<12} pass     {_summary(name, outcome)}")
            continue
        lines.append(f"  {name:<12} FAIL     {_summary(name, outcome)}")
        if name == "freeze" and outcome.get("advisory"):
            lines[-1] = f"  {name:<12} advisory {_summary(name, outcome)}"
            continue
        if code == EXIT_OK:
            code = exit_for[name]

    print(f"baseline (build {BUILD_NUMBER}, "
          f"{'development' if dev_mode.enabled() else 'certified'} run)")
    print("\n".join(lines))
    print("GREEN: the science is where it was" if code == EXIT_OK
          else f"RED: see above (exit {code})")
    if args.json:
        print(json.dumps({"exit_code": code, "checks": results,
                          "run_mode": dev_mode.provenance()}, indent=1, sort_keys=True))
    return code


def _summary(name: str, outcome: dict) -> str:
    if name == "freeze":
        if outcome.get("reason"):
            return outcome["reason"]
        if outcome["ok"]:
            return f"{outcome['frozen_sources']} sources unchanged"
        parts = []
        if outcome.get("stale_build"):
            parts.append(f"manifest anchored at build {outcome['baseline_build']}, "
                         f"running {outcome['current_build']}: re-run "
                         "tools/science_freeze.py --write")
        if outcome["moved"]:
            parts.append(f"{len(outcome['moved'])} moved: {', '.join(outcome['moved'][:3])}"
                         + (" ..." if len(outcome["moved"]) > 3 else ""))
        if outcome["unrecorded"]:
            parts.append(f"{len(outcome['unrecorded'])} unrecorded")
        return "; ".join(parts)
    if name == "calibration":
        if outcome.get("reason"):
            return outcome["reason"]
        standard = float(outcome.get("standard") or 0.0)
        gates = ", ".join(outcome.get("gates_on") or [])
        charted = [m for m in (outcome.get("misses") or []) if not m.get("gates")]
        if outcome["ok"]:
            tail = (f"; {len(charted)} charted outside the standard ("
                    + ", ".join(f"{m['family']}/{m['channel']} {m['relative_deviation']:.1%}"
                                for m in sorted(charted, key=lambda m: -m["relative_deviation"])[:3])
                    + (" ..." if len(charted) > 3 else "") + ")") if charted else ""
            return (f"ladder {outcome.get('ladder_verdict')}, {gates} within "
                    f"{standard:.0%} on every analytic family, refusals held{tail}")
        parts = []
        if outcome.get("families_absent"):
            parts.append("families absent: " + ", ".join(outcome["families_absent"]))
        if outcome.get("theory_drift"):
            parts.append(f"{len(outcome['theory_drift'])} theory values differ from the "
                         "frozen declaration")
        if outcome.get("failing_families"):
            parts.append("ladder FAIL: " + ", ".join(str(f) for f in outcome["failing_families"]))
        for miss in outcome.get("gating_misses") or []:
            parts.append(f"{miss['family']}/{miss['channel']} at N={miss['n']} reads "
                         f"{miss['measured']:.4f} against {miss['theory']:.4f} "
                         f"({miss['relative_deviation']:.1%}, standard {standard:.0%})")
        for entry in outcome.get("false_confidence") or []:
            parts.append(f"{entry['family']}/{entry['channel']} answered at N={entry['n']} "
                         "where it must decline")
        return "; ".join(parts)
    if name == "estimators":
        return outcome.get("reason") or f"adopt_calibration exit {outcome.get('returncode')}"
    if outcome.get("reason"):
        return outcome["reason"]
    shifted = outcome.get("population_shifted_cells") or []
    real = outcome.get("regressions_excluding_shifted", outcome["regressions"])
    parts = [f"{outcome['compared_cells']} cells", f"{len(real)} regressed"]
    if shifted:
        parts.append(f"{len(shifted)} not comparable (population moved "
                     + ", ".join(f"N={r['n']} x{r['population_shift']}" for r in shifted) + ")")
    parts.append(f"{len(outcome['improvements'])} improved")
    if outcome["too_thin_to_compare"]:
        parts.append(f"{len(outcome['too_thin_to_compare'])} too thin")
    return ", ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
