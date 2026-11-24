#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import structure  # noqa: E402
from graph_scale_dynamics.calibration.admission import rss_bytes  # noqa: E402
from graph_scale_dynamics.calibration.cells import cell_key, extension_ladder, family_ladder, suite_families  # noqa: E402
from graph_scale_dynamics.calibration.extension import _census_task, _task_process_main  # noqa: E402

TABLE = structure.census_memory_path()
SIZES = (262_144, 1_048_576)
NEAREST_WITHIN = 0.8
SAMPLE_SECONDS = 0.1


def plan(sizes=SIZES) -> list[dict]:
    tasks = []
    for family in suite_families():
        rungs = family_ladder(family) + extension_ladder(family)
        for size in sizes:
            rung = min(rungs, key=lambda r: abs(math.log(r["n"] / size)))
            if abs(math.log(rung["n"] / size)) > NEAREST_WITHIN:
                continue
            task = {"key": cell_key(family["name"], rung["parameter"], 0), "family": family["name"],
                    "parameter": rung["parameter"], "seed": 0, "n": rung["n"]}
            if task not in tasks:
                tasks.append(task)
    return tasks


def measure(task: dict) -> dict:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_task_process_main,
                              args=(dict(task, run=_census_task, parent_pid=os.getpid()), send), daemon=True)
    started = time.monotonic()
    process.start()
    send.close()
    samples, result = [], None
    while True:
        if receive.poll(SAMPLE_SECONDS):
            try:
                result = receive.recv()
            except (EOFError, OSError):
                pass
            break
        if not process.is_alive():
            break
        held = rss_bytes(process.pid)
        if held:
            samples.append(held)
    process.join(timeout=10)
    receive.close()
    census = (result or {}).get("structure") or {}
    return {"family": task["family"], "parameter": task["parameter"], "n": task["n"], "seed": task["seed"],
            "peak_rss_bytes": (result or {}).get("peak_rss_bytes"),
            "mean_rss_bytes": int(sum(samples) / len(samples)) if samples else None,
            "seconds": round(time.monotonic() - started, 1), "census_seconds": census.get("seconds"),
            "gap_method": census.get("gap_method"),
            "error": census.get("error") or (None if result else f"no result (exit code {process.exitcode})")}


def check(table: dict) -> list[str]:
    problems = []
    if table.get("contract") != structure.CENSUS_MEMORY_CONTRACT:
        problems.append(f"contract {table.get('contract')!r}")
    rows = table.get("rows") or []
    families = {f["name"] for f in suite_families()}
    if {r.get("family") for r in rows} != families:
        problems.append(f"families measured: {sorted({r.get('family') for r in rows})}")
    for row in rows:
        if row.get("error") or not isinstance(row.get("peak_rss_bytes"), int) or not isinstance(row.get("n"), int):
            problems.append(f"{row.get('family')} n={row.get('n')}: {row.get('error') or 'no peak'}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/calibrate_census_memory.py: see docs/TOOLS.md")
    parser.add_argument("--check", action="store_true", help="check the committed table; write nothing")
    args = parser.parse_args(argv)
    if args.check:
        table = structure.committed_census_memory()
        problems = check(table or {}) if table else ["no committed table"]
        for line in problems:
            print(f"census memory: {line}")
        print("census memory: " + ("the committed table is whole" if not problems else f"{len(problems)} problem(s)"))
        return 1 if problems else 0
    rows = []
    for task in plan():
        row = measure(task)
        rows.append(row)
        peak = row["peak_rss_bytes"] or 0
        print(f"{row['family']:<30} n={row['n']:>9,} peak {peak / 1024 ** 3:6.2f} GiB, mean "
              f"{(row['mean_rss_bytes'] or 0) / 1024 ** 3:6.2f} GiB, {row['seconds']:7.1f} s, "
              f"{row['gap_method']}{'  ' + row['error'] if row['error'] else ''}", flush=True)
    table = {"contract": structure.CENSUS_MEMORY_CONTRACT, "census_contract": structure.STRUCTURE_CONTRACT,
             "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "host": {"cpus": os.cpu_count(), "python": platform.python_version()},
             "how": ("seed 0 of every family at the rungs nearest 262,144 and 1,048,576, one census at a time, "
                     "each in a process of its own started as the backfill starts one; peak_rss_bytes is the "
                     "process's own peak (getrusage), mean_rss_bytes its resident memory read every 0.1 s"),
             "rows": rows}
    problems = check(table)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"census memory: {len(rows)} censuses -> {TABLE.relative_to(ROOT)}"
          + (f"; {len(problems)} problem(s): " + "; ".join(problems) if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
