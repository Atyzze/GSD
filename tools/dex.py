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
    dex = D.merge(parts, science=science, made_by={"study": label, "build": None, "folder": "tools/dex.py"},
                  verify_to=args.verify_to)
    path = D.write(dex, Path(args.out), label)
    print(f"{path}: {len(dex['laws'])} laws, {len(dex['top'])} in the top, {len(dex['regions'])} regions, "
          f"{len(dex['chains'])} chains, from {len(dex['sources'])} sources"
          + (f", read again to N={dex['verify_to']:,}" if dex.get("verify_to") else ""))
    return 0


def show(args) -> int:
    part = D.read_part(args.dex)
    sha = (part.get("science") or {}).get("sha256")
    order = D.ranked(part["laws"], sha)
    print(f"{part['name']} ({part['kind']}): {len(part['laws'])} laws, science {str(sha)[:16]}, "
          f"{len(part.get('regions') or [])} regions, {len(part.get('chains') or [])} chains"
          + (f", read again to N={part['verify_to']:,}" if part.get("verify_to") else ""))
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


def zones(args) -> int:
    from graph_scale_dynamics.operations import dex_check, zone_search
    from graph_scale_dynamics.operations import zone_choice as Z
    part = D.read_part(args.dex)
    sha = (part.get("science") or {}).get("sha256")
    held = dex_check.controls()
    laws = {}
    for law, entry in part["laws"].items():
        checks = entry.get("verified") or []
        verdict = (Z.CONFIRMED if args.as_verified else
                   dex_check.verdict_of({"agree": sum(int(v.get("agree") or 0) for v in checks),
                                         "differ": sum(int(v.get("differ") or 0) for v in checks)}))
        laws[law] = {"spec": entry["spec"], "verdict": verdict, "code": (entry.get("codes") or [law[:10]])[0],
                     "score": D.standing(entry, sha), "control": law in held}
    mapped = [zone for region in part.get("regions") or [] for zone in region.get("zones") or []]
    over = zone_search.passed_over(mapped, {law: entry["spec"] for law, entry in laws.items()})
    for zone in mapped:
        edges = zone.get("edges") or {}
        print(f"  {zone.get('region') or '-'} {zone.get('label')}: {zone.get('stage')}, {zone.get('kind')}, "
              f"{len(zone.get('members') or [])} laws alike, {sum(1 for e in edges.values() if e.get('held'))} of "
              f"{len(edges)} edges held to {zone.get('held_to') or '-'}, central law "
              f"{(zone.get('central') or {}).get('label') or '-'}")
    laws = {law: entry for law, entry in laws.items() if law not in over}
    found = Z.first(laws, radius=args.radius)
    tally = found["counts"]
    print(f"{part['name']}: {tally['laws']} laws, {tally[Z.CONFIRMED]} confirmed, {tally[Z.DENIED]} denied, "
          f"{tally[Z.UNMATCHED]} unmatched" + (" (every law taken as confirmed)" if args.as_verified else "")
          + f", {tally['controls']} standing controls")
    for place, group in enumerate(Z.groups(laws, args.radius)[:args.top]):
        print(f"  {place + 1:>3} {group['near']:>3} within {args.radius:g} of {group['code']} ({group['laws']} of "
              f"{', '.join(group['terms'])}, {group['dynamics']}; mean {group['mean']:.3f}, widest "
              f"{group['widest']:.3f}, best score {group['best']})")
    said = f" ({len(over)} laws passed over: inside or at the centre of a zone the dex holds)" if over else ""
    print(f"the next zone: {found['chosen']['code'] if found['chosen'] else 'none'}{said}: {found['why']}")
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/dex.py")
    sub = parser.add_subparsers(dest="command", required=True)
    made = sub.add_parser("make", help="merge dexes and study bundles into one new dex")
    made.add_argument("parts", nargs="+")
    made.add_argument("--out", required=True)
    made.add_argument("--label")
    made.add_argument("--science-of", help="a part whose science the dex is read under (default: this tree's)")
    made.add_argument("--verify-to", type=int,
                      help="the size a study reading the dex in runs its laws again to (default: the ladder's base, "
                           "N=4,096); a level below the base is the base")
    shown = sub.add_parser("show", help="a dex's or a study bundle's laws, best first")
    shown.add_argument("dex")
    shown.add_argument("--top", type=int, default=25)
    shown.add_argument("--json")
    zoned = sub.add_parser("zones", help="the zones the dex holds, its other laws grouped by term set, and the next "
                                         "zone the rule chooses")
    zoned.add_argument("dex")
    zoned.add_argument("--radius", type=float, default=0.1)
    zoned.add_argument("--as-verified", action="store_true",
                       help="every law taken as confirmed, as a study reading the dex in will find it if none differs")
    zoned.add_argument("--top", type=int, default=10)
    zoned.add_argument("--json")
    args = parser.parse_args(argv)
    try:
        return {"make": make, "show": show, "zones": zones}[args.command](args)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
