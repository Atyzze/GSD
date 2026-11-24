#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import rule as R  # noqa: E402


def shown(document: dict) -> str:
    lines = [f"a family without a dimension is refused by every probe from "
             f"{document['a_refusal_is_required_from_nodes']:,} nodes: " + ", ".join(document["without_a_dimension"])]
    for family, held in document["with_a_dimension"].items():
        lines.append(family)
        for probe in R.PROBES:
            if probe not in held:
                lines.append(f"  {probe}: measured and shown")
                continue
            bands = ", ".join(f"{within:g} from {nodes:,}" for nodes, within in held[probe]["bands"])
            lines.append(f"  {probe}: {held[probe]['theory']:.4g} within {bands}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/table_rule.py: see docs/TOOLS.md")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        document = R.write()
        print(shown(document))
        print(f"wrote {R.HOLDS.relative_to(ROOT)}")
        return 0
    derived = R.derive()
    if args.check:
        same = R.HOLDS.is_file() and json.loads(R.HOLDS.read_text(encoding="utf-8")) == derived
        print("the table holds what its rule gives" if same else
              f"{R.HOLDS.relative_to(ROOT)} is not what the rule gives: python3 tools/table_rule.py --write")
        return 0 if same else 1
    print(shown(derived))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
