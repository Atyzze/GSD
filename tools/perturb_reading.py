#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402

CONTRACT = "gsd-perturb-reading-1"
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
COLUMNS = ("n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction")


def criterion(study: str = "175") -> dict:
    return json.loads((READINGS / f"study_{study}_criterion.json").read_text(encoding="utf-8"))


def holders(study: str = "175") -> dict:
    return json.loads((READINGS / f"study_{study}_holders.json").read_text(encoding="utf-8"))


def planned(study: str = "175") -> list[dict]:
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    design = SD.design_for(ROOT, study)
    entry = design["campaigns"][0]
    survey = SD.campaign_spec(design, SD.without_terms(design, shipped_spec(), log=lambda line: None), entry, 0)
    return SD.perturb_laws(design, survey, ROOT)


def values_of(root: Path) -> dict[str, dict]:
    out = {}
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        body = json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}
        columns = list((body.get("every_chain") or {}).get("value_columns") or COLUMNS)
        decided = {str(r.get("candidate_id")): r for r in body.get("laws") or [] if isinstance(r, dict)}
        for law, entry in ((body.get("every_chain") or {}).get("laws") or {}).items():
            chains = {name: {int(row[0]): dict(zip(columns, row, strict=False)) for row in rows}
                      for name, rows in (entry.get("values") or {}).items()}
            own = decided.get(str(law)) or {}
            out[str(law)] = {"chains": chains, "top_n": entry.get("top_n"),
                             "decision": [own.get("action"), own.get("rule"), own.get("at_n")]}
    return out


def behaviour(law: dict | None, chain: str, n: int) -> dict | None:
    row = ((law or {}).get("chains") or {}).get(chain, {}).get(int(n))
    if not row:
        return None
    read = [row.get(p) for p in L.PROBES if row.get(p) is not None]
    if not read:
        return None
    return {"d": round(statistics.median(read), 4), "mean_degree": row.get("mean_degree")}


def alike(seen: dict | None, held: dict | None, tolerance: float) -> bool:
    if not seen or not held or held.get("d") in (None, 0):
        return False
    if abs(seen["d"] - held["d"]) > tolerance * abs(held["d"]):
        return False
    a, b = seen.get("mean_degree"), held.get("mean_degree")
    return a is None or b in (None, 0) or abs(a - b) <= tolerance * abs(b)


def verdict(counts: dict[float, int], rule: dict) -> tuple[str, float | None]:
    need = int(rule["alike_at_least"])
    radii = sorted(counts)
    stream = radii[0]
    if counts[stream] < need:
        return "stream", None
    region = None
    for radius in radii[1:]:
        if counts[radius] < need:
            break
        region = radius
    return ("point", None) if region is None else ("region", region)


def read(root: Path, study: str = "175") -> dict:
    rule = criterion(study)["verdict"]
    source = holders(study)
    laws = planned(study)
    found = values_of(root)
    by_holder: dict[str, list[dict]] = {}
    for law in laws:
        by_holder.setdefault(law["of"], []).append(law)
    rows = []
    for holder in source["holders"]:
        own = holder["read_in_174"]
        chain, n = own["chain"], int(own["to_n"])
        rerun = found.get(holder["candidate_id"])
        own_laws = by_holder.get(holder["candidate_id"], [])
        if rerun is None and not any(law["candidate_id"] in found for law in own_laws):
            continue
        held = behaviour(rerun, chain, n) or {"d": own["d"], "mean_degree": own["mean_degree"]}
        replayed = None
        if rerun is not None:
            columns = own.get("value_columns") or COLUMNS
            replayed = all(rerun["chains"].get(chain, {}).get(int(row[0])) == dict(zip(columns, row, strict=False))
                           for row in own["values"])
        counts, seen = {}, {}
        for law in own_laws:
            if not law["radius"]:
                continue
            radius = float(law["radius"])
            reading = behaviour(found.get(law["candidate_id"]), chain, n)
            counts[radius] = counts.get(radius, 0) + int(alike(reading, held, float(rule["tolerance"])))
            seen.setdefault(radius, []).append(None if reading is None else reading["d"])
        kind, wide = verdict(counts, rule)
        rows.append({"holder": holder["label"], "law": holder["candidate_id"], "chain": chain, "n": n,
                     "d": held["d"], "mean_degree": held.get("mean_degree"), "replayed": replayed,
                     "alike": {f"{r:g}": counts[r] for r in sorted(counts)},
                     "d_read": {f"{r:g}": seen[r] for r in sorted(seen)},
                     "verdict": kind, "region_to": wide, "terms": [t[0] for t in holder["compact"]["terms"]]})
    tally: dict[str, int] = {}
    for row in rows:
        key = row["verdict"] if row["verdict"] != "region" else f"region to {row['region_to']:g}"
        tally[key] = tally.get(key, 0) + 1
    return {"contract": CONTRACT, "study": study, "bundle": Path(root).name, "holders": len(rows),
            "rule": rule, "tally": tally, "rows": rows,
            "replayed": sum(1 for r in rows if r["replayed"]), "rerun_read": sum(1 for r in rows if r["replayed"] is not None)}


def render(found: dict) -> str:
    rule = found["rule"]
    lines = [f"# Study {found['study']}: region or point, on {found['bundle']}", "",
             f"{found['holders']} holders read. A law is alike its holder when it reads at the holder's size on the "
             f"holder's chain a d within {rule['tolerance']:g} of the holder's, relative, and a mean degree as close. "
             f"A radius holds when at least {rule['alike_at_least']} of its variants are alike. {rule['words']}", "",
             f"Run again: {found['replayed']} of {found['rerun_read']} holders read in this bundle read exactly what "
             "they read in study 174.", "",
             "Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(found["tally"].items())) + ".", "",
             "| holder | law | chain | at N | d | alike by radius | verdict | terms |", "|---|---|---|---|---|---|---|---|"]
    for row in found["rows"]:
        verdict_text = row["verdict"] if row["verdict"] != "region" else f"region to {row['region_to']:g}"
        lines.append(f"| {row['holder']} | `{row['law'][:12]}` | {row['chain']} | {row['n']:,} | {row['d']:g} | "
                     + ", ".join(f"{r} {k}" for r, k in row["alike"].items())
                     + f" | {verdict_text} | {' + '.join(row['terms'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the perturbation side study's verdicts, read on its bundle")
    parser.add_argument("bundle", help="the side study's bundle (.tar.zst) or its folder")
    parser.add_argument("--study", default="175")
    parser.add_argument("--json")
    parser.add_argument("--md")
    args = parser.parse_args(argv)
    source = Path(args.bundle)
    if source.is_file():
        from read_bundle import scratch_dir, unpacked
        source = unpacked(source, scratch_dir("gsd-perturb-reading-"))
    found = read(source, args.study)
    if args.json:
        Path(args.json).write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(found), encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
