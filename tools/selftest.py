#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "calibration" / "probe_windows.json"
SELFTEST_CONTRACT = "gsd-selftest-1"

WINDOW_K = 3.0
WINDOW_FLOOR = 0.02


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _env() -> dict:
    env = dict(os.environ, GSD_MEMBW_SOURCE="off", PYTHONDONTWRITEBYTECODE="1",
               GSD_REQUIRE_NATIVE_POSTGRES_TESTS="1")
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[name] = "1"
    return env


def _run(cmd: list[str], *, timeout: float, cwd: Path = ROOT) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout after {timeout}s\n{(exc.stdout or '')[-2000:]}"


def _ladders_of(doc: dict) -> dict:
    if isinstance(doc.get("deviation"), dict) and doc["deviation"].get("families"):
        deviation = doc["deviation"]
        return {"families": deviation["families"], "seeds": deviation.get("seeds"),
                "max_nodes": deviation.get("max_nodes")}
    return doc.get("probe_ladders") or doc


def build_windows(ladders_path: Path, *, k: float = WINDOW_K, floor: float = WINDOW_FLOOR) -> dict:
    doc = json.loads(Path(ladders_path).read_text(encoding="utf-8"))
    ladders = _ladders_of(doc)
    out = {"contract": "gsd-probe-windows-2", "source_seeds": ladders.get("seeds"),
           "source_max_nodes": ladders.get("max_nodes"), "k": k, "floor": floor,
           "source_build": doc.get("build_number"),
           "source_science_fingerprint": doc.get("science_fingerprint"),
           "source_estimator_fingerprint": doc.get("estimator_fingerprint"), "families": {}}
    for family, F in (ladders.get("families") or {}).items():
        cells = {}
        for row in F.get("rows") or []:
            for channel, v in (row.get("channels") or {}).items():
                seeds = [s for s in (v.get("per_seed") or []) if s is not None]
                if len(seeds) < 2:
                    continue
                sd = statistics.pstdev(seeds)
                cells[f"{channel}@{row['n']}"] = {
                    "channel": channel, "n": int(row["n"]), "mean": sum(seeds) / len(seeds),
                    "sd": sd, "seeds": len(seeds), "window": max(k * sd, floor),
                    "theory": v.get("theory"),
                }
        out["families"][family] = {"expectation": F.get("expectation"), "cells": cells}
    return out


def check_windows(ladders_path: Path, windows_path: Path = WINDOWS) -> dict:
    windows = json.loads(Path(windows_path).read_text(encoding="utf-8"))
    doc = json.loads(Path(ladders_path).read_text(encoding="utf-8"))
    families = _ladders_of(doc).get("families") or {}
    checked, failures, skipped = 0, [], 0
    for family, W in windows["families"].items():
        rows = {int(r["n"]): r for r in (families.get(family) or {}).get("rows") or []}
        for key, cell in W["cells"].items():
            row = rows.get(cell["n"])
            measured = ((row or {}).get("channels") or {}).get(cell["channel"], {}).get("measured")
            if measured is None:
                skipped += 1
                continue
            checked += 1
            deviation = abs(float(measured) - float(cell["mean"]))
            if deviation > float(cell["window"]):
                failures.append({"family": family, "cell": key, "measured": measured,
                                 "mean": cell["mean"], "window": cell["window"], "deviation": deviation})
    return {"checked": checked, "skipped_unmeasured": skipped, "failures": failures,
            "ok": checked > 0 and not failures}


def step_environment(report: dict) -> bool:
    detail = {"python": sys.version.split()[0], "root": str(ROOT), "uid": os.getuid()}
    ok = True
    for module in ("numpy", "scipy", "psutil", "psycopg", "zstandard"):
        try:
            __import__(module)
            detail[module] = "ok"
        except ImportError:
            detail[module] = "missing"
            ok = ok and module in ("zstandard",)
    detail["zstd"] = shutil.which("zstd") or "missing"
    detail["node"] = shutil.which("node") or "missing (UI smoke will be skipped)"
    if not detail["zstd"].startswith("/"):
        ok = False
    sys.path.insert(0, str(ROOT))
    try:
        from tools import postgres_instance as PI
        override = PI.system_bin_dir()
        detail["postgres_binaries"] = str(override) if override else (
            "pinned image present" if PI._runtime_complete() else
            "pinned image will be downloaded on ensure (needs registry access) or set GSD_POSTGRES_SYSTEM_BIN")
    except Exception as exc:
        detail["postgres_binaries"] = f"error: {exc}"
        ok = False
    if os.getuid() == 0:
        detail["warning"] = "running as root; the folder-local PostgreSQL refuses root. Run as an unprivileged user."
        ok = False
    report["detail"] = detail
    return ok


def step_postgres(report: dict) -> bool:
    code, out = _run([sys.executable, "tools/postgres_instance.py", "ensure"], timeout=600)
    report["detail"] = out[-3000:]
    return code == 0


def step_schema(report: dict, var: str) -> bool:
    code, out = _run([sys.executable, "main.py", "--var", var, "init"], timeout=600)
    report["detail"] = out[-3000:]
    return code == 0


def step_pytest(report: dict, lane: str, *, timeout: float, extra: list[str] = ()) -> bool:
    cmd = [sys.executable, "tools/test_suite.py", "--lane", lane, *extra]
    code, out = _run(cmd, timeout=timeout)
    tail = out.strip().splitlines()[-1:] or [""]
    report["detail"] = {"summary": tail[0], "tail": out[-4000:]}
    return code == 0


def all_family_names() -> str:
    sys.path.insert(0, str(ROOT))
    from graph_scale_dynamics.measurements.calibration import CALIBRATION_FAMILIES
    return ",".join(f["name"] for f in CALIBRATION_FAMILIES)


def step_windows(report: dict, seeds: int, tmp: Path) -> bool:
    if not WINDOWS.is_file():
        report["skipped"] = True
        report["detail"] = {
            "reason": f"{WINDOWS.relative_to(ROOT)} is absent; no variance windows to check against",
            "recovery": "uv run python tools/selftest.py --build-windows --window-seeds 4",
        }
        return True
    out = tmp / f"ladders_seeds{seeds}.json"
    code, log = _run([sys.executable, "tools/probe_calibration.py", "--probe-ladders",
                      "--families", all_family_names(), "--max-nodes", "1100",
                      "--seeds", str(seeds), "--out", str(out)], timeout=1200)
    if code != 0 or not out.is_file():
        report["detail"] = {"error": "ladder run failed", "tail": log[-2000:]}
        return False
    result = check_windows(out)
    report["detail"] = result
    return result["ok"]


def step_calibration_gate(report: dict) -> bool:
    code, log = _run([sys.executable, "tools/adopt_calibration.py", "--sample", "2"], timeout=1800)
    report["detail"] = {"tail": log[-2000:]}
    return code == 0


def step_ui_smoke(report: dict) -> bool:
    node = shutil.which("node")
    if not node:
        report["detail"] = "node not available; skipped"
        report["skipped"] = True
        return True
    ui = ROOT / "graph_scale_dynamics" / "resources" / "ui"
    outs = []
    ok = True
    for script in ("dashboard_smoke.js", "candidate_smoke.js"):
        code, out = _run([node, str(ROOT / "tests" / "ui" / script), str(ui)], timeout=120)
        outs.append(f"{script}: {out.strip()[-200:]}")
        ok = ok and code == 0
    report["detail"] = outs
    return ok


def _build_windows_file(seeds: int) -> int:
    if seeds < 2:
        print(f"--window-seeds must be at least 2 to have a spread to measure; got {seeds}")
        return 2
    tmp = ROOT / "var" / "selftest" / "scratch"
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"ladders_seeds{seeds}.json"
    print(f"[windows] running the probe ladder at {seeds} seeds; this takes a few minutes", flush=True)
    code, log = _run([sys.executable, "tools/probe_calibration.py", "--probe-ladders",
                      "--families", all_family_names(), "--max-nodes", "1100",
                      "--seeds", str(seeds), "--out", str(out)], timeout=3600)
    if code != 0 or not out.is_file():
        print(f"[windows] ladder run failed (exit {code})\n{log[-2000:]}")
        return 1
    windows = build_windows(out)
    cells = sum(len(f.get("cells") or {}) for f in windows["families"].values())
    if not cells:
        print("[windows] the ladder produced no cell with two valid seeds; refusing to write "
              "a file that would check nothing")
        return 1
    WINDOWS.parent.mkdir(parents=True, exist_ok=True)
    WINDOWS.write_text(json.dumps(windows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[windows] wrote {WINDOWS.relative_to(ROOT)}: "
          f"{len(windows['families'])} families, {cells} cells, k={windows['k']}, "
          f"floor={windows['floor']}, from {seeds} seeds")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/selftest.py: see docs/TOOLS.md")
    parser.add_argument("--quick", action="store_true", help="skip the 300-second vertical slice")
    parser.add_argument("--no-postgres", action="store_true", help="skip the PostgreSQL and schema steps and the native lane")
    parser.add_argument("--window-seeds", type=int, default=3, help="seed count for the variance-window run (default 3)")
    parser.add_argument("--build-windows", action="store_true",
                        help="run the ladder and write calibration/probe_windows.json, then exit")
    parser.add_argument("--out", default=None, help="result JSON path (default var/selftest/latest.json)")
    args = parser.parse_args(argv)

    if args.build_windows:
        return _build_windows_file(args.window_seeds)

    started = time.monotonic()
    var = ROOT / "var"
    tmp = var / "selftest" / "scratch"
    tmp.mkdir(parents=True, exist_ok=True)
    steps: list[dict] = []

    def run_step(name: str, fn, required: bool = True) -> None:
        report = {"name": name, "required": required, "started_utc": _utc()}
        t0 = time.monotonic()
        try:
            ok = bool(fn(report))
        except Exception as exc:
            ok = False
            report["detail"] = f"{type(exc).__name__}: {exc}"
        report["ok"] = ok
        report["seconds"] = round(time.monotonic() - t0, 1)
        steps.append(report)
        mark = "skip" if report.get("skipped") else ("PASS" if ok else "FAIL")
        print(f"[selftest] {mark:4s} {name} ({report['seconds']}s)", flush=True)

    run_step("environment", step_environment)
    if not args.no_postgres:
        run_step("postgres ensure", step_postgres)
        run_step("schema init", lambda r: step_schema(r, "var/selftest/state"))
    run_step("science exact (calibration gate)", step_calibration_gate)
    run_step("science windows (different seeds)", lambda r: step_windows(r, args.window_seeds, tmp))
    run_step("lanes unit, contract and scientific", lambda r: step_pytest(r, "hermetic", timeout=3600))
    if not args.no_postgres:
        marker = ["--marker", "not slice"] if args.quick else []
        run_step("lane integration + native postgres" + (" (quick)" if args.quick else ""),
                 lambda r: step_pytest(r, "postgres", timeout=2400, extra=["--require-postgres", *marker]))
    run_step("ui smoke", step_ui_smoke, required=False)

    failed = [s["name"] for s in steps if not s["ok"] and s["required"]]
    result = {
        "contract": SELFTEST_CONTRACT, "root": str(ROOT), "finished_utc": _utc(),
        "seconds": round(time.monotonic() - started, 1), "quick": args.quick,
        "steps": steps, "failed": failed, "ok": not failed,
    }
    try:
        from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
        result["build_number"] = BUILD_NUMBER
        result["runtime_fingerprint"] = runtime_fingerprint()
    except Exception:
        pass
    out_path = Path(args.out) if args.out else var / "selftest" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"[selftest] {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} in {result['seconds']}s; "
          f"report {out_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
