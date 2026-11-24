#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import margins as M  # noqa: E402

TABLE = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / M.BANDS_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/calibrate_margins.py: see docs/TOOLS.md")
    parser.add_argument("--write", action="store_true", help="derive the bands from the seed table and commit them")
    args = parser.parse_args(argv)
    derived = M.seed_bands(ROOT)
    if args.write:
        TABLE.write_text(json.dumps(derived, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {TABLE.relative_to(ROOT)} from {M.SEED_TABLE} ({derived['cells_with_margins']} cells)")
        return 0
    current = M.committed_bands() == derived
    print(f"{TABLE.relative_to(ROOT)}: {'current' if current else 'STALE: run with --write'}")
    for rung, entry in sorted(derived["bands"].items(), key=lambda kv: int(kv[0])):
        plateau = entry["plateau"]
        print(f"  {int(rung):>9,}  geometry {plateau['geometry']}  no finite dimension "
              f"{plateau['no_finite_dimension']}  separated {plateau['separated']}")
    return 0 if current else 1


if __name__ == "__main__":
    raise SystemExit(main())
