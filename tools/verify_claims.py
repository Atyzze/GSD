#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from graph_scale_dynamics.operations.scratch_namespace import enter as enter_scratch
except ImportError as missing:
    print(f"verify_claims needs the project's environment ({missing}). Run it as\n"
          "    uv run python tools/verify_claims.py", file=sys.stderr)
    raise SystemExit(2)
SCRATCH = enter_scratch(ROOT, create=False)

try:
    from graph_scale_dynamics.research import claim_ledger
except ImportError as missing:
    print(f"verify_claims needs the project's environment ({missing}). Run it as\n"
          "    uv run python tools/verify_claims.py", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/verify_claims.py: see docs/TOOLS.md")
    parser.add_argument("--out", type=Path, default=None, help="write the zip here instead")
    args = parser.parse_args(argv)

    tree = claim_ledger.evaluate_tree()
    lanes = [tree]
    errors: list[str] = []

    claims = [row for lane in lanes for row in lane["claims"]]
    verdicts = (claim_ledger.VERIFIED, claim_ledger.REFUTED, claim_ledger.UNCHECKABLE)
    counts = {verdict: sum(1 for row in claims if row["verdict"] == verdict) for verdict in verdicts}
    lane_names = " and ".join(str(lane["lane"]) for lane in lanes)
    readings = [f"{len(claims)} claims in the {lane_names} lane: {counts[claim_ledger.VERIFIED]} verified, "
                f"{counts[claim_ledger.REFUTED]} refuted, "
                f"{counts[claim_ledger.UNCHECKABLE]} not checkable here."]
    for lane in lanes:
        readings += list(lane["readings"])
    readings += errors

    build = (ROOT / "BUILD_NUMBER").read_text().strip() if (ROOT / "BUILD_NUMBER").exists() else "unknown"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    default = ROOT / "var" / "diagnostics" / f"claims_{build}_{stamp}.zip"
    out = Path(args.out) if args.out else default
    summary = {"readings": readings, "contract": claim_ledger.CLAIM_LEDGER_CONTRACT,
               "offline": True,
               "counts": counts, "by_lane": {str(lane["lane"]): lane["counts"] for lane in lanes},
               "errors": errors, "scratch": SCRATCH, "build": build}

    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("claims.jsonl", "\n".join(json.dumps(row, default=str) for row in claims))
        archive.writestr("summary.json", json.dumps(summary, indent=1, default=str))
        archive.writestr("ABOUT.txt", "The claims ledger read against this tree: claims.jsonl, one row a claim with its verdict; summary.json, the counts. docs/TOOLS.md, tools/verify_claims.py, says how it is made.\n")
    partial.replace(out)

    for line in readings:
        print(line)
    print(f"wrote {out.stat().st_size / 1024:.0f} KiB; hand over this file:", file=sys.stderr)
    print(out)
    if any(row["verdict"] == claim_ledger.REFUTED for row in tree["claims"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
