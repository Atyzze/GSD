#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import finite_size as F  # noqa: E402

SEED = ROOT / "calibration" / "seed_table.json"
RUNGS = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/finite_size_tolerance.py: see docs/TOOLS.md")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    fresh = F.measure(json.loads(SEED.read_text(encoding="utf-8")))
    if args.write:
        F.COMMITTED.parent.mkdir(parents=True, exist_ok=True)
        F.COMMITTED.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    current = F.COMMITTED.is_file() and F.committed() == fresh
    for low, high in zip(RUNGS, RUNGS[1:], strict=False):
        print(f"  {low:>9,} -> {high:>9,}: {F.tolerance(low, high, fresh):.3f}")
    print("committed fits are current" if current else "committed fits differ from the seed table's: --write")
    return 0 if current else 1


if __name__ == "__main__":
    raise SystemExit(main())
