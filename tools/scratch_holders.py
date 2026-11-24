#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations import scratch_holders as H  # noqa: E402


def _gib(value) -> str:
    return "?" if value is None else f"{value / 2 ** 30:.1f} GiB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/scratch_holders.py: see docs/TOOLS.md")
    parser.add_argument("--json", action="store_true", help="print the records as JSON")
    args = parser.parse_args(argv)

    found = H.discover(breakdown_of=ROOT)
    if args.json:
        print(json.dumps(found, indent=2, default=str))
        return 0
    if not found:
        print("no folder scratch is mounted in any namespace of this user")
        return 0
    total = sum(int(r.get("used_bytes") or 0) for r in found)
    print(f"{len(found)} folder scratch(es) in RAM, {_gib(total)} in use:")
    for record in found:
        mark = "this tree" if Path(record["folder"]) == ROOT else ("busy" if record["busy"] else "idle")
        print(f"  [{mark}] {H.describe(record)}")
        entries = (record.get("breakdown") or {}).get("entries") or {}
        for name, size in list(entries.items())[:8]:
            print(f"        {_gib(size):>9}  {name}")
        if record.get("breakdown") and not record["breakdown"].get("complete"):
            print("        (the walk stopped at its time limit; the sizes above are lower bounds)")
    idle = [r for r in found if not r["busy"] and Path(r["folder"]) != ROOT]
    if idle:
        print(f"{len(idle)} idle scratch(es) of other folders, left alone: stop that folder, or `kill` its holder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
