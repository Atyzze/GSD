#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

RECORD = "gsd-pilot-record-1"
CONTRACT = "gsd-pilot-difference-1"
QUANTITIES = ("seeds", "mean_degree", "connected_fraction", "d_s", "d_V", "d_B", "d_w")
SIGNIFICANT = 9
LANE = ("deep_lane_full", "lane_resumed")
LISTED = 60


def _rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _value(value):
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return float(f"{value:.{SIGNIFICANT}g}")
    return value


def _batches(study: dict) -> dict:
    out, order = {}, 0
    for campaign in study.get("campaigns") or []:
        if not campaign.get("law_budget"):
            continue
        index = (campaign.get("study_design") or {}).get("campaign")
        out[str(campaign["campaign_id"])] = int(index) if index is not None else order
        order += 1
    return out


def record_of(root: Path) -> dict:
    root = Path(root)
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    batches, laws = _batches(study), {}
    for row in _rows(root / "tables" / "laws.ndjson.gz"):
        campaign = str(row.get("campaign_id"))
        if campaign not in batches:
            continue
        decision = row.get("decision") or {}
        laws[str(row["candidate_id"])] = {
            "batch": batches[campaign], "state": row.get("state"), "action": decision.get("action"),
            "rule": decision.get("rule"), "at_n": decision.get("at_n"), "top_n": row.get("top_n"), "rungs": {}}
    for row in _rows(root / "tables" / "rungs.ndjson.gz"):
        law = laws.get(str(row.get("candidate_id")))
        if law is not None:
            law["rungs"][str(int(row["n"]))] = {name: _value(row.get(name)) for name in QUANTITIES}
    return {"contract": RECORD, "study": str(study.get("study_id")), "build_number": study.get("build_number"),
            "bundle": root.name, "built_utc": study.get("built_utc"), "batches": len(set(batches.values())),
            "significant_figures": SIGNIFICANT, "quantities": list(QUANTITIES),
            "reading": ("each blind law of a pilot's bundle: its batch, its last decision (action, rule, the size it "
                        "names), the largest size it ran, and at each size the seeds measured, the mean degree, the "
                        "largest component and the four probes; what tools/pilot_difference.py holds the next build's "
                        "run of the same seeds to"),
            "laws": dict(sorted(laws.items()))}


def load(path: Path, scratch: Path | None = None) -> dict:
    path = Path(path)
    if path.is_file() and path.suffix == ".json":
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("contract") != RECORD:
            raise ValueError(f"{path} is not a pilot's record ({RECORD})")
        return record
    from read_bundle import scratch_dir, unpacked
    return record_of(unpacked(path, scratch or scratch_dir("gsd-pilot-")))


def _decision(law: dict) -> list:
    return [law.get("action"), law.get("rule"), law.get("at_n")]


def _moved(law: str, before: dict, after: dict, declared: tuple) -> dict | None:
    out = {}
    if _decision(before) != _decision(after):
        out["decision"] = [_decision(before), _decision(after)]
    if before.get("top_n") != after.get("top_n"):
        out["depth"] = [before.get("top_n"), after.get("top_n")]
    readings = []
    for n in sorted(set(before["rungs"]) | set(after["rungs"]), key=int):
        was, now = before["rungs"].get(n) or {}, after["rungs"].get(n) or {}
        readings.extend([int(n), name, was.get(name), now.get(name)] for name in QUANTITIES
                        if _value(was.get(name)) != _value(now.get(name)))
    if readings:
        out["readings"] = readings
    if not out:
        return None
    return {"law": law, "batch": after.get("batch"),
            "lane": any(rule in LANE for rule in (before.get("rule"), after.get("rule"))),
            "declared": any(law.startswith(prefix) for prefix in declared), **out}


def difference(record: dict, run: dict, declared=()) -> dict:
    declared = tuple(str(prefix) for prefix in declared if prefix)
    before, after = record["laws"], run["laws"]
    both = sorted(set(before) & set(after))
    moved = [found for found in (_moved(law, before[law], after[law], declared) for law in both) if found]
    judged = [row for row in moved if not row["lane"] and not row["declared"]]
    only_record, only_run = sorted(set(before) - set(after)), sorted(set(after) - set(before))
    side = lambda found: {key: found.get(key) for key in ("study", "build_number", "bundle", "built_utc")}  # noqa: E731
    return {"contract": CONTRACT, "record": dict(side(record), laws=len(before)), "run": dict(side(run), laws=len(after)),
            "laws_in_both": len(both), "only_in_the_record": only_record, "only_in_the_run": len(only_run),
            "only_in_the_run_first": only_run[:LISTED], "only_in_the_run_laws": only_run, "declared": list(declared),
            "moved": moved,
            "counts": {"moved": len(moved), "by_a_lane": sum(row["lane"] for row in moved),
                       "declared": sum(row["declared"] and not row["lane"] for row in moved),
                       "decision_or_depth": sum(("decision" in row or "depth" in row) for row in judged),
                       "readings_only": sum("readings" in row and "decision" not in row and "depth" not in row
                                            for row in judged)},
            "checks": {"R1": not only_record,
                       "R2": not any("decision" in row or "depth" in row for row in judged),
                       "R3": not any("readings" in row for row in judged)}}


def _side(found: dict) -> str:
    return (f"study {found['study']} on build {found['build_number']}, {found['bundle']} "
            f"(built {found['built_utc']}), {found['laws']:,} laws")


def _what(row: dict) -> str:
    parts = []
    if "decision" in row:
        was, now = row["decision"]
        parts.append(f"decision {was[0]} by {was[1]} at {was[2]} -> {now[0]} by {now[1]} at {now[2]}")
    if "depth" in row:
        parts.append(f"largest size {row['depth'][0]} -> {row['depth'][1]}")
    if "readings" in row:
        shown = "; ".join(f"{name} at {n:,}: {was} -> {now}" for n, name, was, now in row["readings"][:3])
        more = len(row["readings"]) - 3
        parts.append(f"{len(row['readings'])} readings ({shown}{f'; and {more} more' if more > 0 else ''})")
    return "; ".join(parts)


def markdown(found: dict) -> str:
    counts, checks = found["counts"], found["checks"]
    says = lambda passed: "passes" if passed else "fails"  # noqa: E731
    lines = ["# A pilot against the record of the build before", "",
             f"The record: {_side(found['record'])}.", f"The run: {_side(found['run'])}.", "",
             f"Read by {CONTRACT} on every law of both, never a sample; a reading is the same to {SIGNIFICANT} "
             "significant figures. Since 806 no clock ends a seed, so a seed that ended at its budget in work is judged "
             "as any other. A law a deep size's lane held, its last decision a lane's in either run (a "
             "larger run's busier lane), and a law named before the run, are listed and not judged. R1 judges the record's laws alone: a law "
             "only in the run is one a larger budget drew, counted and read as a wide pilot's.", "",
             f"* R1, every law of the record is in the run: {says(checks['R1'])}. {found['laws_in_both']:,} laws "
             f"in both; {len(found['only_in_the_record'])} only in the record; {found['only_in_the_run']:,} only "
             "in the run" + (", not judged: a larger budget draws laws the record never held"
                             if found["only_in_the_run"] else "") + ".",
             f"* R2, no decision or depth moved: {says(checks['R2'])}. {counts['decision_or_depth']} laws.",
             f"* R3, no reading moved: {says(checks['R3'])}. {counts['readings_only']} laws moved in a reading alone.",
             f"* N1: {counts['by_a_lane']} laws moved that a deep size's lane held; {counts['declared']} that were "
             "named before the run.", ""]
    if found["only_in_the_record"]:
        lines += ["Only in the record: " + ", ".join(f"`{law[:12]}`" for law in found["only_in_the_record"][:LISTED]), ""]
    if found["moved"]:
        lines += ["| law | batch | judged | what moved |", "|---|---:|---|---|"]
        lines += [f"| `{row['law'][:12]}` | {int(row['batch']) + 1} | "
                  f"{'no: a lane' if row['lane'] else 'no: named before' if row['declared'] else 'yes'} | {_what(row)} |"
                  for row in found["moved"][:LISTED]]
        if len(found["moved"]) > LISTED:
            lines.append(f"\nand {len(found['moved']) - LISTED} more, in the JSON.")
    else:
        lines.append("No law moved.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="a pilot's bundle against the record of the build before")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--record", type=Path, help="write this bundle's record here and stop")
    parser.add_argument("--against", type=Path, help="a record, or another bundle of the same seeds")
    parser.add_argument("--declared", default="", help="laws named before the run, by id or its first characters")
    parser.add_argument("--md", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    run = load(args.bundle)
    if args.record:
        args.record.write_text(json.dumps(run, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{len(run['laws']):,} laws of study {run['study']} on build {run['build_number']}: {args.record}")
        return 0
    if not args.against:
        parser.error("give --record to write a record, or --against to read a difference")
    found = difference(load(args.against), run, declared=[part.strip() for part in args.declared.split(",")])
    text = markdown(found)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(text)
    return 0 if all(found["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
