#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

CONTRACT = "gsd-held-by-a-gate-1"
PROBES = ("d_s", "d_V", "d_B", "d_w")
START_ORDER = ("empty", "random", "square", "triangular", "cubic", "bcc", "fcc", "tesseract")
LINE, MIDDLE, ABOVE, NOTHING = "a line or a ring", "d 1.3 to 2.5", "above 2.5", "nothing read"
LINE_BELOW, MIDDLE_TO = 1.3, 2.5
RULE = ("a law is held when its latest decision stops it at the gate and the size named; it is classed by the best "
        "reading of any of its starts at that size in report 28's every_chain values: a chain reads where any of its "
        "four probes has a mean there, its d the median of those it reads; the best chain is the one that reads the "
        "most probes, the chain from empty first among equals, then the random start's, then the lattices in their "
        "order; d under 1.3 is a line or a ring, 1.3 to 2.5 the middle, above 2.5 the rest, and no chain reading is "
        "nothing read. The run-on list is every held law that reads something.")


def unpacked(path: Path) -> Path:
    if path.is_file():
        from read_bundle import scratch_dir
        from read_bundle import unpacked as unpack
        return unpack(path, scratch_dir("gsd-held-by-a-gate-"))
    return path


def bundle_root(path: Path) -> Path:
    if (path / "study.json").is_file():
        return path
    found = sorted(p.parent for p in path.glob("*/study.json"))
    if len(found) != 1:
        raise SystemExit(f"{path} holds {len(found)} study bundles: name one")
    return found[0]


def held(root: Path, gate: str, at_n: int) -> list[dict]:
    out = []
    with gzip.open(root / "tables" / "laws.ndjson.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            decision = row.get("decision") or {}
            if isinstance(decision, str):
                decision = json.loads(decision)
            if (decision.get("action") == "stop" and str(decision.get("rule")) == gate
                    and decision.get("at_n") is not None and int(decision["at_n"]) == at_n):
                out.append({"campaign": str(row["campaign_id"]), "law": str(row["candidate_id"]),
                            "number": row.get("candidate_number"), "state": row.get("state")})
    return sorted(out, key=lambda r: (int(r["campaign"]) if r["campaign"].isdigit() else 0, r["number"] or 0, r["law"]))


def chain_values(root: Path, campaigns: set[str]) -> dict[tuple[str, str], dict]:
    out = {}
    for path in sorted(root.glob("campaign_*_reports_*/28-decision-engine.json")):
        campaign = path.parent.name.split("_")[1]
        if campaign not in campaigns:
            continue
        every = (json.loads(path.read_text(encoding="utf-8")).get("body") or {}).get("every_chain") or {}
        columns = list(every.get("value_columns") or [])
        for law, entry in (every.get("laws") or {}).items():
            out[(campaign, str(law))] = {"columns": columns, "values": entry.get("values") or {}}
    return out


def reading_at(found: dict | None, n: int) -> dict:
    if not found:
        return {"class": NOTHING, "chain": None, "d": None, "probes": {}, "why": "no every_chain values"}
    columns = found["columns"]
    if "n" not in columns:
        return {"class": NOTHING, "chain": None, "d": None, "probes": {}, "why": "no size column"}
    reads = []
    for chain, rows in found["values"].items():
        if chain == "given":
            continue
        row = next((r for r in rows or [] if r and r[columns.index("n")] == n), None)
        if row is None:
            continue
        probes = {p: float(row[columns.index(p)]) for p in PROBES
                  if p in columns and row[columns.index(p)] is not None}
        if probes:
            place = START_ORDER.index(chain) if chain in START_ORDER else len(START_ORDER)
            reads.append((-len(probes), place, chain, probes))
    if not reads:
        return {"class": NOTHING, "chain": None, "d": None, "probes": {}}
    _many, _place, chain, probes = sorted(reads)[0]
    d = statistics.median(probes.values())
    label = LINE if d < LINE_BELOW else MIDDLE if d <= MIDDLE_TO else ABOVE
    return {"class": label, "chain": chain, "d": round(d, 3), "probes": {k: round(v, 3) for k, v in probes.items()},
            "chains_reading": len(reads)}


def listing(root: Path, gate: str, at_n: int, study: str | None) -> dict:
    meta = json.loads((root / "study.json").read_text(encoding="utf-8"))
    laws = held(root, gate, at_n)
    values = chain_values(root, {row["campaign"] for row in laws})
    classes = {LINE: 0, MIDDLE: 0, ABOVE: 0, NOTHING: 0}
    for row in laws:
        row.update(reading_at(values.get((row["campaign"], row["law"])), at_n))
        classes[row["class"]] += 1
    run_on = [row for row in laws if row["class"] != NOTHING]
    laws_sha = hashlib.sha256("\n".join(f"{r['campaign']}:{r['law']}" for r in run_on).encode("utf-8")).hexdigest()
    return {"contract": CONTRACT, "study": str(study or meta.get("study") or meta.get("study_id") or ""),
            "bundle": {"name": root.name, "built_utc": meta.get("built_utc") or meta.get("generated_utc"),
                       "build": meta.get("build_number") or meta.get("build")},
            "gate": gate, "at_n": at_n, "rule": RULE, "held": len(laws), "classes": classes,
            "run_on": {"laws": len(run_on), "sha256": laws_sha,
                       "by_class": {k: v for k, v in classes.items() if k != NOTHING}},
            "laws": laws}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="the laws a gate holds at one size, classed by what their starts "
                                                 "read there, and the list of those that read something")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--gate", default="starts_alike")
    parser.add_argument("--at", type=int, default=16384)
    parser.add_argument("--study")
    parser.add_argument("--write", type=Path)
    args = parser.parse_args(argv)
    root = bundle_root(unpacked(args.bundle))
    found = listing(root, args.gate, int(args.at), args.study)
    print(f"study {found['study']}, bundle {found['bundle']['name']}: {found['held']} laws held by {args.gate} at "
          f"N={args.at:,}; " + ", ".join(f"{k} {v}" for k, v in found["classes"].items())
          + f"; {found['run_on']['laws']} to run on")
    if args.write:
        args.write.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
