#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

CONTRACT = "gsd-study-baseline-1"
CURVATURE = "ollivier_curvature"


def _laws(root: Path):
    from graph_scale_dynamics.observability import law_score as L
    import score_list as SL
    for path in sorted(glob.glob(str(root / "campaign_*_reports_*" / "28-decision-engine.json"))):
        body = json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}
        campaign = Path(path).parent.name.split("_")[1]
        latest = {str(row["candidate_id"]): row for row in body.get("laws") or [] if isinstance(row, dict)}
        every = (body.get("every_chain") or {}).get("laws") or {}
        seeds = body.get("seeds") or {}
        columns, ids = seeds.get("columns") or [], seeds.get("laws") or []
        hours: dict = defaultdict(lambda: defaultdict(float))
        for row in seeds.get("rows") or []:
            record = dict(zip(columns, row, strict=False))
            law = str(ids[record["law"]])
            seconds = record.get("cpu_seconds") or record.get("simulation_seconds") or 0.0
            hours[law][int(record["n"])] += float(seconds) / 3600.0
        for row in (body.get("law_ledger") or {}).get("rows") or []:
            law = str(row["candidate_id"])
            entry = every.get(law) or {}
            decided = latest.get(law) or {}
            terms = [str(term[0]) for term in ((row.get("spec") or {}).get("terms") or []) if term]
            found = None
            if entry:
                chains, five = SL.chains_of_report(entry)
                found = L.compact(L.score(chains, five, references={}))
            fates = {name: fate for name, (fate, _kept) in ((entry.get("starts_reading") or {}).get("fates") or {}).items()}
            sizes = sorted(int(n) for n in hours.get(law, {}))
            yield {"law": law, "campaign": campaign, "kind": row.get("kind"), "terms": sorted(set(terms)),
                   "curvature": CURVATURE in terms,
                   "end": [decided.get("action"), decided.get("rule"), decided.get("at_n")],
                   "top_n": max(sizes) if sizes else None,
                   "core_hours": {str(n): round(hours[law][n], 4) for n in sizes},
                   "fates": fates, "score": found}


def _final_ends(root: Path) -> dict:
    import gzip
    path = Path(root) / "tables" / "laws.ndjson.gz"
    if not path.exists():
        return {}
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as rows:
        for line in rows:
            row = json.loads(line)
            decided = row.get("decision") or {}
            if row.get("candidate_id") and decided:
                out[str(row["candidate_id"])] = [decided.get("action"), decided.get("rule"), decided.get("at_n")]
    return out


def _study_of(root: Path) -> str:
    try:
        return str(json.loads((Path(root) / "study.json").read_text(encoding="utf-8")).get("study_id") or "")
    except (OSError, ValueError):
        return ""


def gates_scored(root: Path, laws: list[dict]) -> list[dict]:
    try:
        ledger = json.loads((Path(root) / "gates_ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    score = {f"{law['campaign']}:{law['law']}": float((law["score"] or {}).get("score") or 0) for law in laws}
    rows = []
    for gate, by_size in sorted((ledger.get("gates") or {}).items()):
        for n, entry in sorted(by_size.items(), key=lambda kv: int(kv[0])):
            if "laws" not in entry:
                continue
            found = sorted(((score.get(key, 0.0), key) for key in entry["laws"] if score.get(key, 0.0) > 0), reverse=True)
            rows.append({"gate": gate, "n": int(n), "label": entry.get("label"), "held": entry.get("held"),
                         "let_through": entry.get("let_through"), "scored": len(found),
                         "best": [{"law": key, "score": value} for value, key in found[:5]]})
    return rows


def read(root: Path) -> dict:
    laws = list(_laws(Path(root)))
    final = _final_ends(Path(root))
    for law in laws:
        law["end"] = final.get(law["law"], law["end"])
    study = _study_of(Path(root)) or "this"
    build = (ROOT / "BUILD_NUMBER").read_text(encoding="utf-8").strip()
    by_size_hours: Counter = Counter()
    by_size_laws: Counter = Counter()
    for law in laws:
        for n, value in law["core_hours"].items():
            by_size_hours[int(n)] += value
            by_size_laws[int(n)] += 1
    ends = Counter(str(law["end"][1]) for law in laws)
    without = [law for law in laws if not law["curvature"]]
    return {"contract": CONTRACT, "bundle": Path(root).name, "study": study, "laws": len(laws),
            "with_the_curvature_term": len(laws) - len(without),
            "core_hours": round(sum(by_size_hours.values()), 2),
            "core_hours_without_the_curvature_term": round(sum(sum(l["core_hours"].values()) for l in without), 2),
            "by_size": [{"n": n, "laws": by_size_laws[n], "core_hours": round(by_size_hours[n], 2)}
                        for n in sorted(by_size_laws)],
            "ends": dict(sorted(ends.items(), key=lambda kv: -kv[1])),
            "scored": sum(1 for law in laws if (law["score"] or {}).get("score")),
            "gates_scored": gates_scored(Path(root), laws),
            "reading": (f"Study {study}'s bundle read law by law on build {build}: each law's end as the folder held it "
                        "when the bundle was made, its sizes and core-hours, its lattice fates and its score on this "
                        "build's rule (readings from 4,096 on pieces of 4,096 nodes or more). The baseline the next "
                        "study is read against, law by law. A pilot's numbers, not findings."),
            "per_law": sorted(laws, key=lambda law: (law["campaign"], law["law"]))}


def render(found: dict) -> str:
    lines = [f"# Study {found.get('study') or 'this'}, the baseline ({found['bundle']})", "", found["reading"], "",
             f"{found['laws']:,} laws, {found['with_the_curvature_term']:,} with the curvature term; "
             f"{found['core_hours']:,} core-hours, {found['core_hours_without_the_curvature_term']:,} without the "
             f"term's laws; {found['scored']:,} laws score above zero on 784's rule.", "",
             "| N | laws | core-hours |", "|---:|---:|---:|"]
    lines += [f"| {row['n']:,} | {row['laws']:,} | {row['core_hours']:,} |" for row in found["by_size"]]
    lines += ["", "| ended by | laws |", "|---|---:|"]
    lines += [f"| `{rule}` | {count:,} |" for rule, count in found["ends"].items()]
    if found.get("gates_scored"):
        lines += ["", "What each gate let through, and how much of that scored:", "",
                  "| gate | N | share | held back | let through | scored | best |", "|---|---:|---|---:|---:|---:|---|"]
        for row in found["gates_scored"]:
            best = ", ".join("%s %g" % (b["law"].split(":")[-1][:8], b["score"]) for b in row["best"][:2])
            lines.append(f"| `{row['gate']}` | {row['n']:,} | {row['label']} | {row['held'] or 0:,} | "
                         f"{row['let_through']:,} | {row['scored']:,} | {best} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="a study's bundle read law by law into one baseline")
    parser.add_argument("bundle", help="the study bundle's unpacked folder")
    parser.add_argument("--out", required=True, help="the path to write, without its .json and .md")
    args = parser.parse_args(argv)
    found = read(Path(args.bundle))
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(render(found), encoding="utf-8")
    print(f"wrote {out.with_suffix('.json')} and {out.with_suffix('.md')}: {found['laws']:,} laws")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
