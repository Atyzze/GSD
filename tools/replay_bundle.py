#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-bundle-replay-1"
TABLE = Path("tables") / "decisions.ndjson.gz"
SHOWN = 50


def study_root(path: Path) -> Path:
    from tools.read_bundle import scratch_dir, unpacked
    return unpacked(Path(path), scratch_dir("gsd_replay_"))


def rows_of(root: Path):
    with gzip.open(Path(root) / TABLE, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def verdict_of(row: dict) -> dict:
    from graph_scale_dynamics.decisions.replay import replay_matches
    try:
        return replay_matches(dict(row, inputs=row.get("inputs_json")))
    except Exception as exc:  # noqa: BLE001
        return {"matches": False, "differences": [f"{type(exc).__name__}: {exc}"], "same_rules": None}


def replay_rows(rows) -> dict:
    counts: dict = defaultdict(Counter)
    rules: dict = defaultdict(Counter)
    same: dict = defaultdict(Counter)
    mismatches, unread = [], []
    for row in rows:
        campaign = str(row.get("campaign_id"))
        verdict = verdict_of(row)
        if verdict["matches"] is None:
            key = "released hold" if row.get("released_hold") else "no inputs"
            if key == "no inputs":
                unread.append({"campaign_id": campaign, "candidate_id": row.get("candidate_id"),
                               "decision_id": row.get("decision_id"), "rule": row.get("rule")})
        else:
            key = "replays" if verdict["matches"] else "differs"
            same[campaign][str(verdict.get("same_rules")).lower()] += 1
        counts[campaign][key] += 1
        rules[campaign][f"{row.get('action')}:{row.get('rule')}"] += 1
        if verdict["matches"] is False:
            mismatches.append({"campaign_id": campaign, "candidate_id": row.get("candidate_id"),
                               "decision_id": row.get("decision_id"), "rule": row.get("rule"),
                               "same_rules": verdict.get("same_rules"), "differences": verdict["differences"]})
    total = Counter()
    for found in counts.values():
        total.update(found)
    return {"contract": CONTRACT, "decisions": sum(total.values()), "counts": dict(total),
            "by_campaign": {c: {"counts": dict(counts[c]), "same_rules": dict(same[c]),
                                "by_rule": dict(sorted(rules[c].items()))} for c in sorted(counts)},
            "mismatches": mismatches, "without_inputs": unread,
            "whole": not mismatches and not unread}


def render(found: dict) -> str:
    counts = found["counts"]
    lines = [f"every decision of the bundle replayed ({found['contract']}): {found['decisions']:,} decisions, "
             f"{counts.get('replays', 0):,} replay, {counts.get('differs', 0):,} differ, "
             f"{counts.get('no inputs', 0):,} without inputs, {counts.get('released hold', 0):,} released holds"]
    for campaign, part in found["by_campaign"].items():
        rules = ", ".join(f"{rule} {count}" for rule, count in part["by_rule"].items())
        lines.append(f"  campaign {campaign}: {part['counts']}, same rules {part['same_rules']}; {rules}")
    for item in found["mismatches"][:SHOWN]:
        lines.append(f"  differs: {item['campaign_id']} {str(item['candidate_id'])[:12]} {item['decision_id']} "
                     f"{item['rule']}: {'; '.join(item['differences'])[:400]}")
    if len(found["mismatches"]) > SHOWN:
        lines.append(f"  and {len(found['mismatches']) - SHOWN} more differ (--json for all)")
    for item in found["without_inputs"][:SHOWN]:
        lines.append(f"  no inputs: {item['campaign_id']} {str(item['candidate_id'])[:12]} {item['decision_id']} "
                     f"{item['rule']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="replay every decision of a study bundle from its own inputs")
    parser.add_argument("bundle", type=Path, help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", type=Path, help="write the whole result, every mismatch included")
    args = parser.parse_args(argv)
    root = study_root(args.bundle)
    if not (root / TABLE).is_file():
        print(f"{args.bundle}: no {TABLE.as_posix()}; this bundle carries no decision's inputs")
        return 2
    found = replay_rows(rows_of(root))
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if found["whole"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
