#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-holders-lowest-energy-2"
HOLDING = ("holds", "selects", "grows", "converts")
HELD = ("holds", "unmoved")
ALONE = "a held lattice, alone"
NOT_APART = "a held lattice, not apart"
AMONG = "a held lattice among others"
ELSEWHERE = "another start"
ELSEWHERE_NOT_APART = "another start, not apart"
UNREAD = "no energy read"
WORDS = (ALONE, NOT_APART, AMONG, ELSEWHERE, ELSEWHERE_NOT_APART, UNREAD)


def where_lowest(starts_reading: dict) -> tuple[str, list[str], list[str]]:
    low = (starts_reading or {}).get("lowest") or {}
    held = sorted(name for name, pair in ((starts_reading or {}).get("fates") or {}).items()
                  if (pair or [None])[0] in HELD)
    group = sorted(low.get("group") or [])
    if not group:
        return UNREAD, group, held
    if set(group) <= set(held):
        return (ALONE if low.get("apart") else NOT_APART), group, held
    if set(group) & set(held):
        return AMONG, group, held
    return (ELSEWHERE if low.get("apart") else ELSEWHERE_NOT_APART), group, held


def read(root: Path, holders: dict) -> dict:
    rows = []
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports*" / "28-decision-engine.json"))):
        number = int(Path(path).parent.name.split("_")[1])
        if number > 5:
            continue
        body = json.loads(Path(path).read_text(encoding="utf-8"))["body"]
        for law, entry in ((body.get("every_chain") or {}).get("laws") or {}).items():
            if law in holders:
                word, group, held = where_lowest(entry.get("starts_reading") or {})
                rows.append({"law": law, "campaign": number, "class": holders[law]["class"], "where": word,
                             "lowest": group, "held": held,
                             "at_n": (entry.get("starts_reading") or {}).get("at_n")})
        del body
    found = {row["law"] for row in rows}
    return {"contract": CONTRACT, "holders": len(holders), "read": len(rows),
            "not_in_report_28": sorted(law[:12] for law in holders if law not in found),
            "where": {word: sum(1 for row in rows if row["where"] == word) for word in WORDS},
            "elsewhere_by_group": dict(Counter(",".join(row["lowest"]) for row in rows
                                               if row["where"] == ELSEWHERE).most_common()),
            "elsewhere_not_apart_by_group": dict(Counter(",".join(row["lowest"]) for row in rows
                                                         if row["where"] == ELSEWHERE_NOT_APART).most_common()),
            "by_class": {cls: dict(Counter(row["where"] for row in rows if row["class"] == cls)) for cls in HOLDING},
            "laws": sorted(rows, key=lambda row: row["law"])}


def _groups(counts: dict) -> str:
    return "; ".join(f"{group} {count}" for group, count in counts.items()) or "none"


def markdown(result: dict, bundle: str) -> str:
    lines = [f"# Where the holders end lowest, from {bundle}", "",
             f"`tools/holders_lowest_energy.py` ({CONTRACT}): each law the starts read as `holds`, `selects`, "
             "`grows` or `converts`, and the start whose chain ends lowest in energy a node at the law's size (report "
             "28's starts' reading `lowest`, `observability/starts_reading._lowest`: with the starts that end alike, and apart "
             "when the next is higher by more than 2% or two standard errors). Whether the lowest is a held lattice or "
             "another start, it is said apart only past that margin; within it, `not apart`. Read from a bundle made "
             "on 742 or later, where every chain's energy reaches the report. Recorded, never judged.", "",
             f"{result['read']} of {result['holders']} holders read.", "",
             "| where the lowest end is | laws |", "|---|---:|"]
    lines += [f"| {word} | {count} |" for word, count in result["where"].items()]
    lines += ["", "Where it is another start's, apart: " + _groups(result["elsewhere_by_group"]) + ". Not apart: "
              + _groups(result["elsewhere_not_apart_by_group"]) + ".", "",
              "| class | " + " | ".join(WORDS) + " |", "|---|" + "---:|" * len(WORDS)]
    for cls, counts in result["by_class"].items():
        lines.append(f"| {cls} | " + " | ".join(str(counts.get(word, 0)) for word in WORDS) + " |")
    lines += ["", "## Every holder", "", "| law | campaign | class | at | held | lowest | where |", "|---|---:|---|---:|---|---|---|"]
    for row in result["laws"]:
        lines.append(f"| `{row['law'][:12]}` | {row['campaign']} | {row['class']} | {row['at_n']} | "
                     f"{', '.join(row['held']) or 'none'} | {', '.join(row['lowest']) or 'none'} | {row['where']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/holders_lowest_energy.py")
    parser.add_argument("bundle")
    parser.add_argument("--laws", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    holders = {law: entry for law, entry in json.loads(args.laws.read_text(encoding="utf-8"))["laws"].items()
               if entry.get("class") in HOLDING}
    from tools.read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-lowest-") as scratch:
        root = unpacked(Path(args.bundle), Path(scratch))
        result = dict(read(root, holders), bundle=root.name, laws_from=str(args.laws))
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    page = markdown(result, result["bundle"])
    if args.md:
        args.md.write_text(page, encoding="utf-8")
    if not args.json and not args.md:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
