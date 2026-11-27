#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations import dex as D  # noqa: E402


def _science(args, parts: list[dict]) -> dict:
    if args.science_of:
        return dict(D.read_part(args.science_of)["science"])
    from graph_scale_dynamics.reporting import science_contract
    return science_contract.science()[0]


def make(args) -> int:
    parts = [D.read_part(path) for path in args.parts]
    science = _science(args, parts)
    label = args.label or "_".join(sorted({str(p.get("study") or "x") for p in parts}))
    dex = D.merge(parts, science=science, made_by={"study": label, "build": None, "folder": "tools/dex.py"})
    path = D.write(dex, Path(args.out), label)
    print(f"{path}: {len(dex['laws'])} laws, {len(dex['top'])} in the top, {len(dex['regions'])} regions, "
          f"{len(dex['chains'])} chains, from {len(dex['sources'])} sources")
    return 0


def show(args) -> int:
    part = D.read_part(args.dex)
    sha = (part.get("science") or {}).get("sha256")
    order = D.ranked(part["laws"], sha)
    print(f"{part['name']} ({part['kind']}): {len(part['laws'])} laws, science {str(sha)[:16]}, "
          f"{len(part.get('regions') or [])} regions, {len(part.get('chains') or [])} chains")
    for source in part.get("sources") or []:
        print(f"  from {source.get('name')} ({source.get('kind')}, study {source.get('study')}, "
              f"{source.get('laws')} laws, science {str(source.get('science'))[:16]})")
    for place, law in enumerate(order[:args.top]):
        entry = part["laws"][law]
        here = D.standing(entry, sha)
        checks = entry.get("verified") or []
        said = ", ".join(f"{v.get('agree')} agree {v.get('differ')} differ by {v.get('by')}" for v in checks)
        print(f"  {place + 1:>4} {law[:12]} score {here if here is not None else '-':>3} "
              f"best {D.best_score(entry):>3} {', '.join(entry.get('codes') or [])[:60]}"
              + (f" · verified: {said}" if said else ""))
    if args.json:
        Path(args.json).write_text(json.dumps({"laws": [part["laws"][law] for law in order]}, indent=1, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/dex.py")
    sub = parser.add_subparsers(dest="command", required=True)
    made = sub.add_parser("make", help="merge dexes and study bundles into one new dex")
    made.add_argument("parts", nargs="+")
    made.add_argument("--out", required=True)
    made.add_argument("--label")
    made.add_argument("--science-of", help="a part whose science the dex is read under (default: this tree's)")
    shown = sub.add_parser("show", help="a dex's or a study bundle's laws, best first")
    shown.add_argument("dex")
    shown.add_argument("--top", type=int, default=25)
    shown.add_argument("--json")
    args = parser.parse_args(argv)
    try:
        return make(args) if args.command == "make" else show(args)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
