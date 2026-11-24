from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

BASE = (64, 256, 1024, 4096)
RELIED_ON = (1024, 4096)
DEEP_FROM = 16384
PROBES = ("d_s", "d_V", "d_B", "d_w")
SECONDS = ("d_s_seconds", "d_V_seconds", "d_B_seconds", "d_w_seconds", "kappa_seconds")
GATE = "nothing_read"


def _reads(values: dict, sizes) -> dict:
    return {chain: sorted({(int(row[0]), probe) for row in rows if int(row[0]) in sizes
                           for probe, value in zip(PROBES, row[1:5], strict=True) if value is not None})
            for chain, rows in (values or {}).items()}


def _deep(values: dict) -> dict:
    return {chain: sorted({(int(row[0]), probe) for row in rows if int(row[0]) >= DEEP_FROM
                           for probe, value in zip(PROBES, row[1:5], strict=True) if value is not None})
            for chain, rows in (values or {}).items()}


def _seconds_by_law(seeds: dict) -> Counter:
    index = {column: i for i, column in enumerate(seeds.get("columns") or [])}
    laws = seeds.get("laws") or []
    out: Counter = Counter()
    for row in seeds.get("rows") or []:
        law = row[index["law"]]
        law = laws[law] if isinstance(law, int) else law
        if int(row[index["n"]]) < DEEP_FROM:
            continue
        out[str(law)] += float(row[index["simulation_seconds"]] or 0.0) + sum(
            float(row[index[key]] or 0.0) for key in SECONDS if key in index)
    return out


def read_campaign(body: dict) -> dict:
    laws = (body.get("every_chain") or {}).get("laws") or {}
    decided = {str(row.get("candidate_id")): row for row in body.get("laws") or [] if isinstance(row, dict)}
    seconds = _seconds_by_law(body.get("seeds") or {})
    gate = next((g for g in (body.get("gate_tree") or {}).get("gates") or [] if g.get("gate") == GATE), None)
    parked = sorted(str(row.get("candidate_id")) for row in body.get("laws") or []
                    if isinstance(row, dict) and row.get("rule") == GATE)
    at_budget = sorted(str(row.get("candidate_id")) for row in body.get("laws") or []
                       if isinstance(row, dict) and row.get("budget_ended_at"))
    out = {"the_gate": {"parked": len(parked), "parked_laws": parked,
                        "tree": {key: gate.get(key) for key in ("withheld", "salted_past", "salt_spent", "salt_ledger")
                                 if key in gate} if gate else None},
           "laws_ended_at_a_budget": len(at_budget),
           "laws_read_from_1024": 0, "laws_with_4096": 0, "nothing_on_the_base_block": 0,
           "nothing_at_1024_and_4096": 0, "only_at_64_or_256": 0, "reached_16384": 0,
           "deep_seconds": round(sum(seconds.values()), 1), "cases": []}
    for law, entry in laws.items():
        values = entry.get("values") or {}
        sizes = {int(row[0]) for rows in values.values() for row in rows}
        out["laws_read_from_1024"] += 1
        if not sizes or max(sizes) < 4096:
            continue
        out["laws_with_4096"] += 1
        base, relied = _reads(values, BASE), _reads(values, RELIED_ON)
        none_base, none_relied = not any(base.values()), not any(relied.values())
        out["nothing_on_the_base_block"] += none_base
        out["nothing_at_1024_and_4096"] += none_relied
        out["only_at_64_or_256"] += (not none_base) and none_relied
        deep = max(sizes) >= DEEP_FROM
        out["reached_16384"] += deep
        if deep and none_relied:
            latest = decided.get(str(law)) or {}
            out["cases"].append({"law": str(law), "top_n": max(sizes), "nothing_on_the_base_block": none_base,
                                 "deep_reads": {c: r for c, r in _deep(values).items() if r},
                                 "class": (entry.get("starts_reading") or {}).get("class"),
                                 "rule": latest.get("rule"), "action": latest.get("action"),
                                 "at_n": latest.get("at_n"), "deep_seconds": round(seconds.get(str(law), 0.0), 1)})
    return out


def controls_of(root: Path) -> set[str]:
    study = Path(root) / "study.json"
    if not study.is_file():
        return set()
    found = json.loads(study.read_text(encoding="utf-8"))
    return {str(row.get("bundle")) for row in found.get("campaigns") or [] if row.get("controls") is not None}


def read_bundle(root: Path) -> dict:
    campaigns, controls = {}, controls_of(root)
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        if Path(path).parent.name in controls:
            continue
        body = json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}
        if not (body.get("every_chain") or {}).get("laws"):
            continue
        campaigns[Path(path).parent.name.split("_reports_")[0]] = read_campaign(body)
    total = Counter()
    for found in campaigns.values():
        total.update({k: v for k, v in found.items() if isinstance(v, (int, float))})
        total.update({"parked_by_the_gate": int((found.get("the_gate") or {}).get("parked") or 0)})
    cases = [case for found in campaigns.values() for case in found["cases"]]
    return {"contract": "gsd-base-block-reading-1", "campaigns": campaigns, "total": dict(total),
            "cases": cases, "deep_reads_after_nothing": sum(1 for case in cases if case["deep_reads"]),
            "case_deep_seconds": round(sum(case["deep_seconds"] for case in cases), 1)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the laws whose chains read nothing on the base block: docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="an unpacked study bundle")
    parser.add_argument("--json", type=Path, help="where to write the reading")
    args = parser.parse_args(argv)
    found = read_bundle(args.bundle)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    total = found["total"]
    print(f"{total.get('laws_with_4096', 0)} laws ran 4,096; {total.get('nothing_on_the_base_block', 0)} read nothing "
          f"on any chain at 64 to 4,096 and {total.get('nothing_at_1024_and_4096', 0)} nothing at 1,024 and 4,096 "
          f"({total.get('only_at_64_or_256', 0)} read only at 64 or 256)")
    print(f"the first gate on the base block (782): {total.get('parked_by_the_gate', 0)} laws parked by it; "
          f"{total.get('laws_ended_at_a_budget', 0)} laws a seed ended at its budget somewhere")
    print(f"{len(found['cases'])} of {total.get('reached_16384', 0)} laws measured at 16,384 read nothing at 1,024 "
          f"and 4,096; {found['deep_reads_after_nothing']} of them read something from 16,384 up; they spent "
          f"{found['case_deep_seconds']:,} s of {total.get('deep_seconds', 0):,} s from 16,384 up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
