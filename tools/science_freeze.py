#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "science_freeze.json"

import sys
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.domain.science_identity import (
    digest, frozen_paths,
)


def current_manifest(build_number: int) -> dict:
    return {
        "baseline_build": build_number,
        "contract": "gsd-science-freeze-1",
        "note": "Re-anchored whenever science sources change deliberately.",
        "files": {relative: digest(relative) for relative in frozen_paths()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/science_freeze.py: see docs/TOOLS.md")
    parser.add_argument("--write", action="store_true", help="rewrite the manifest")
    args = parser.parse_args(argv)

    build_number = int((ROOT / "BUILD_NUMBER").read_text().strip())
    fresh = current_manifest(build_number)

    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)} with {len(fresh['files'])} frozen sources")
        return 0

    if not MANIFEST.is_file():
        print("no manifest; run with --write")
        return 1
    stored = json.loads(MANIFEST.read_text(encoding="utf-8"))
    drift = [
        name for name, value in stored["files"].items()
        if not (ROOT / name).is_file() or digest(name) != value
    ]
    added = sorted(set(fresh["files"]) - set(stored["files"]))
    for name in drift:
        print(f"CHANGED {name}")
    for name in added:
        print(f"NEW     {name}")
    print(f"science freeze: {len(stored['files'])} frozen sources, {len(drift)} drifted, {len(added)} new "
          f"(baseline {stored.get('baseline_build', '?')})")
    return 1 if (drift or added) else 0


if __name__ == "__main__":
    raise SystemExit(main())
