#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research import small_world_reach as W  # noqa: E402


def render(found: dict) -> str:
    lines = [f"# The random reach of the small-world rule ({found['contract']})", "",
             f"{found['read']} of {found['random_graphs']} random starts read a reach; the widest is "
             f"{found['widest_off']} steps off ln(N/2)/ln(k) + the offset, within {found['within']}: "
             f"{'yes' if found['random_within'] else 'no'}; the largest reach is {found['largest_ratio']} times it, "
             f"inside the rule's {found['reach_at_most']:g}: {'yes' if found['random_inside_the_band'] else 'no'}.", "",
             "| lattice | N | reach | random reach | ratio |", "|---|---|---|---|---|"]
    for row in found["lattices"]:
        lines.append(f"| {row['start']} | {row['n']:,} | {row['reach']:g} | {row['random_reach']:g} | {row['ratio']:g} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the random start's reach against the small-world rule's random reach")
    parser.add_argument("--json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)
    found = W.judge(W.random_rows(), W.lattice_rows())
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(found), encoding="utf-8")
    print(render(found))
    return 0 if found["random_within"] and found["random_inside_the_band"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
