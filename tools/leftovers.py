#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations import leftovers as L  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/leftovers.py: see docs/TOOLS.md")
    parser.add_argument("--end-gone", action="store_true", help="end every fleet process whose folder is gone")
    parser.add_argument("--end", metavar="FOLDER", help="end every fleet process of this folder")
    args = parser.parse_args(argv)
    rows = L.survey()
    target = str(Path(args.end).resolve()) if args.end else None
    if not rows:
        print("no fleet process of yours is running")
        return 0
    for folder in sorted({str(r["folder"]) for r in rows}):
        mine = [r for r in rows if str(r["folder"]) == folder]
        state = "gone" if all(r["gone"] for r in mine) else "live"
        print(f"{folder}  ({state}, {len(mine)} process(es))")
        for r in mine:
            print(f"  {r['pid']:>8}  {r['kind']:<24} {'gone ' if r['gone'] else ''}{r['command'][:110]}")
    if args.end_gone or target:
        chosen = [r for r in rows if (args.end_gone and r["gone"]) or (target and str(r["folder"]) == target)]
        if not chosen:
            print("nothing to end")
            return 0
        result = L.end(chosen)
        print(f"ended {len(chosen) - len(result['failed'])} of {len(chosen)}"
              + (f"; could not end {result['failed']}" if result["failed"] else ""))
        return 1 if result["failed"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
