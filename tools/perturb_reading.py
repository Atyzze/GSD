#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402

CONTRACT = "gsd-perturb-reading-2"
ENDED = ("stop", "park", "done")
LONGER = "longer_chain"
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


def standing(statuses: list[str], need: int) -> str:
    alike_now = statuses.count("alike")
    if alike_now >= need:
        return "holds"
    if alike_now + statuses.count("unread") < need:
        return "fails"
    return "open"


def verdict_so_far(by_radius: dict[float, list[str]], rule: dict) -> tuple[str, float | None, bool]:
    need = int(rule["alike_at_least"])
    radii = sorted(by_radius)
    states = {radius: standing(by_radius[radius], need) for radius in radii}
    if states[radii[0]] == "fails":
        return "stream", None, True
    if states[radii[0]] == "open":
        return "open", None, False
    region = None
    for radius in radii[1:]:
        if states[radius] == "holds":
            region = radius
            continue
        if states[radius] == "fails":
            return ("point", None, True) if region is None else ("region", region, True)
        return "open", region, False
    return "region", region, True


def decided_at(law: dict | None, n: int) -> bool:
    _action, rule, at_n = ((law or {}).get("decision") or [None, None, None])
    if at_n is None:
        return False
    return int(at_n) > int(n) or (int(at_n) == int(n) and rule != LONGER)


def status_of(law: dict | None, chain: str, n: int, held: dict, tolerance: float) -> str:
    if law is None:
        return "unread"
    if decided_at(law, n):
        return "alike" if alike(behaviour(law, chain, n), held, tolerance) else "unlike"
    if (law.get("decision") or [None])[0] in ENDED:
        return "ended"
    return "unread"


def moves_of(root: Path, laws: set[str]) -> dict[tuple[str, str, int], float]:
    path = Path(root) / "tables" / "chains.ndjson.gz"
    if not path.is_file():
        return {}
    seen: dict[tuple[str, str, int], list[float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("candidate_id") in laws and row.get("final_edges"):
                key = (row["candidate_id"], row["chain"], int(row["n"]))
                seen.setdefault(key, []).append(row["accepted_moves"] / row["final_edges"])
    return {key: round(statistics.median(shares), 4) for key, shares in seen.items()}


def kept_or_made(rerun: dict | None, chain: str, n: int, tolerance: float, moved: float | None) -> dict | None:
    if not decided_at(rerun, n):
        return None
    own = behaviour(rerun, chain, n)
    if own is None:
        return None
    others = sorted(name for name in (rerun.get("chains") or {})
                    if name != chain and alike(behaviour(rerun, name, n), own, tolerance))
    return {"starts_alike": others, "made": bool(others), "moved_per_edge": moved}


def read(root: Path, study: str = "175") -> dict:
    rule = criterion(study)["verdict"]
    tolerance = float(rule["tolerance"])
    source = holders(study)
    laws = planned(study)
    found = values_of(root)
    moved = moves_of(root, {h["candidate_id"] for h in source["holders"]})
    by_holder: dict[str, list[dict]] = {}
    for law in laws:
        by_holder.setdefault(law["of"], []).append(law)
    rows = []
    for holder in source["holders"]:
        own = holder["read_in_174"]
        chain, n = own["chain"], int(own["to_n"])
        columns = own.get("value_columns") or COLUMNS
        rerun = found.get(holder["candidate_id"])
        own_laws = by_holder.get(holder["candidate_id"], [])
        if rerun is None and not any(law["candidate_id"] in found for law in own_laws):
            continue
        as_read = {"chains": {chain: {int(row[0]): dict(zip(columns, row, strict=False)) for row in own["values"]}}}
        held = behaviour(as_read, chain, n) or {"d": own["d"], "mean_degree": own["mean_degree"]}
        sizes = [int(row[0]) for row in own["values"] if decided_at(rerun, int(row[0]))]
        replayed = None
        if sizes:
            replayed = all(rerun["chains"].get(chain, {}).get(size) == as_read["chains"][chain][size] for size in sizes)
        statuses: dict[float, list[str]] = {}
        seen: dict[float, list[float | None]] = {}
        for law in own_laws:
            if not law["radius"]:
                continue
            radius = float(law["radius"])
            mine = found.get(law["candidate_id"])
            statuses.setdefault(radius, []).append(status_of(mine, chain, n, held, tolerance))
            reading = behaviour(mine, chain, n) if decided_at(mine, n) else None
            seen.setdefault(radius, []).append(None if reading is None else reading["d"])
        kind, wide, settled = verdict_so_far(statuses, rule)
        rows.append({"holder": holder["label"], "law": holder["candidate_id"], "chain": chain, "n": n,
                     "d": held["d"], "mean_degree": held.get("mean_degree"), "replayed": replayed,
                     "replayed_sizes": sizes,
                     "alike": {f"{r:g}": statuses[r].count("alike") for r in sorted(statuses)},
                     "statuses": {f"{r:g}": {s: statuses[r].count(s) for s in ("alike", "unlike", "ended", "unread")
                                             if statuses[r].count(s)} for r in sorted(statuses)},
                     "d_read": {f"{r:g}": seen[r] for r in sorted(seen)},
                     "verdict": kind, "region_to": wide, "settled": settled,
                     "kept_or_made": kept_or_made(rerun, chain, n, tolerance,
                                                  moved.get((holder["candidate_id"], chain, n))),
                     "terms": [t[0] for t in holder["compact"]["terms"]]})
    tally: dict[str, int] = {}
    for row in rows:
        tally[label(row)] = tally.get(label(row), 0) + 1
    shown = [row["kept_or_made"] for row in rows if row["kept_or_made"]]
    return {"contract": CONTRACT, "study": study, "bundle": Path(root).name, "holders": len(rows),
            "rule": rule, "tally": tally, "rows": rows, "settled": sum(1 for r in rows if r["settled"]),
            "made": sum(1 for k in shown if k["made"]), "kept_or_made_read": len(shown),
            "replayed": sum(1 for r in rows if r["replayed"]),
            "rerun_read": sum(1 for r in rows if r["replayed"] is not None)}


def label(row: dict) -> str:
    if row["verdict"] == "region":
        return f"region to {row['region_to']:g}"
    if row["verdict"] == "open":
        return "open" if row["region_to"] is None else f"open, a region to at least {row['region_to']:g}"
    return row["verdict"]


def render(found: dict) -> str:
    rule = found["rule"]
    lines = [f"# Study {found['study']}: region or point, on {found['bundle']}", "",
             f"{found['holders']} holders read, {found['settled']} of them settled. A law is alike its holder when it "
             f"reads at the holder's size on the holder's chain a d within {rule['tolerance']:g} of the holder's, "
             f"relative, and a mean degree as close. A radius holds when at least {rule['alike_at_least']} of its "
             f"variants are alike. {rule['words']}", "",
             "A variant is read when its law has been decided at the holder's size, not by buying it longer chains "
             "there: alike or unlike. One stopped, "
             "parked or done below that size ended there and is not alike, as the criterion has it. One still "
             "running is unread, and a radius stays open while its unread variants could still decide it.", "",
             f"Run again: {found['replayed']} of {found['rerun_read']} holders decided at a size of 174 read there "
             "exactly what they read in study 174.", "",
             "Kept or made, added after the study started and recorded only, no part of a verdict: at the holder's "
             "size, which of the holder's other starts read alike its chain (made when one does, kept when none "
             "does), and its chain's accepted moves per edge. "
             f"{found['made']} of {found['kept_or_made_read']} holders read so far are made.", "",
             "Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(found["tally"].items())) + ".", "",
             "| holder | law | chain | at N | d | variants by radius | verdict | kept or made | terms |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in found["rows"]:
        by_radius = "; ".join(f"{r}: " + ", ".join(f"{count} {status}" for status, count in counts.items())
                              for r, counts in row["statuses"].items())
        kept = row["kept_or_made"]
        kept_text = "not read yet" if kept is None else (
            ("made, with " + ", ".join(kept["starts_alike"]) if kept["made"] else "kept")
            + ("" if kept["moved_per_edge"] is None else f", {kept['moved_per_edge']:g} accepted moves an edge"))
        lines.append(f"| {row['holder']} | `{row['law'][:12]}` | {row['chain']} | {row['n']:,} | {row['d']:g} | "
                     f"{by_radius} | {label(row)} | {kept_text} | {' + '.join(row['terms'])} |")
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
