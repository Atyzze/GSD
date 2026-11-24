#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-cap-reading-1"
CAPS = (12.0, 16.0, 20.0, 24.0)
DEEPER = (262144, 1048576)
AT_THE_CAP = 0.5
GOING = ("run_next", "hold")
PEAKS, FINALS = "every seed's peak degree (the bundle's chains table)", (
    "each chain's final degree, the mean over its seeds (report 28's every chain; the bundle has no chains table, so "
    "a chain that passed a cap and came back down within its run is not seen, nor one seed of three that reached it: "
    "what a cap would touch is at least this)")


def _rows(root: Path, name: str):
    path = Path(root) / "tables" / name
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _json(value):
    if isinstance(value, str) and value[:1] in "{[":
        return json.loads(value)
    return value if isinstance(value, (dict, list)) else {}


def design_of(root: Path) -> dict:
    study = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    for campaign in study.get("campaigns") or []:
        path = (campaign.get("study_design") or {}).get("design")
        if path and (ROOT / path).is_file():
            return json.loads((ROOT / path).read_text(encoding="utf-8"))
    return {}


def chain_degrees(root: Path) -> tuple[dict, dict, str]:
    degrees: dict = defaultdict(lambda: defaultdict(list))
    memory: dict = defaultdict(dict)
    best: dict = {}
    seen = False
    for row in _rows(root, "chains.ndjson.gz") or ():
        seen = True
        if row.get("audit") or row.get("chain") is None:
            continue
        key = (str(row["candidate_id"]), int(row["n"]), row.get("seed"))
        multiplier = int(row.get("sweeps_multiplier") or 1)
        if key in best and best[key][0] > multiplier:
            continue
        if key not in best or best[key][0] < multiplier:
            best[key] = (multiplier, {})
        best[key][1][str(row["chain"])] = row
    if seen:
        for (law, n, seed), (_, chains) in best.items():
            for name, row in chains.items():
                if row.get("ran") and row.get("peak_mean_degree") is not None:
                    degrees[(law, n)][name].append(float(row["peak_mean_degree"]))
            memories = [row.get("seed_peak_memory_bytes") for row in chains.values() if row.get("seed_peak_memory_bytes")]
            if memories:
                memory[(law, n)][seed] = int(memories[0])
        return degrees, memory, PEAKS
    for report in sorted(Path(root).glob("campaign_*_reports_*/28-decision-engine.json")):
        body = json.loads(report.read_text(encoding="utf-8")).get("body") or {}
        every = body.get("every_chain") or {}
        at = list(every.get("value_columns") or []).index("mean_degree")
        for law, entry in (every.get("laws") or {}).items():
            for name, values in (entry.get("values") or {}).items():
                for value in values:
                    if value[at] is not None:
                        degrees[(str(law), int(value[0]))][name] = [float(value[at])]
        seeds = body.get("seeds") or {}
        columns, laws = list(seeds.get("columns") or []), list(seeds.get("laws") or [])
        for row in seeds.get("rows") or []:
            cells = dict(zip(columns, row, strict=False))
            if cells.get("peak_memory_bytes"):
                memory[(str(laws[cells["law"]]), int(cells["n"]))][cells["seed"]] = int(cells["peak_memory_bytes"])
    finds = Path(root) / "finds.json"
    if finds.is_file():
        document = json.loads(finds.read_text(encoding="utf-8"))
        at = list(document.get("columns") or []).index("mean_degree")
        for find in document.get("finds") or []:
            for name, values in (find.get("values") or {}).items():
                for value in values:
                    if value[at] is not None:
                        degrees.setdefault((str(find["law"]), int(value[0])), defaultdict(list))
                        degrees[(str(find["law"]), int(value[0]))].setdefault(name, [float(value[at])])
    return degrees, memory, FINALS


def going_chains(root: Path) -> tuple[dict, int]:
    going: dict = {}
    in_a_row = 1
    for row in _rows(root, "decisions.ndjson.gz") or ():
        facts, inputs = _json(row.get("facts_json")), _json(row.get("inputs_json"))
        policy = (inputs or {}).get("policy") if isinstance(inputs, dict) else None
        if isinstance(policy, dict) and policy.get("fact_sizes_in_a_row"):
            in_a_row = max(in_a_row, int(policy["fact_sizes_in_a_row"]))
        chains = (facts or {}).get("chains") if isinstance(facts, dict) else None
        if row.get("at_n") is None or not isinstance(chains, dict):
            continue
        key = (str(row["candidate_id"]), int(row["at_n"]))
        if key not in going or str(row.get("decision_id")) >= going[key][0]:
            going[key] = (str(row.get("decision_id")), row.get("action"),
                          [name for name, chain in chains.items() if (chain or {}).get("action") in GOING])
    return going, in_a_row


def scoring_chains(root: Path) -> dict:
    path = Path(root) / "finds.json"
    if not path.is_file():
        return {}
    found = {}
    for find in json.loads(path.read_text(encoding="utf-8")).get("finds") or []:
        if find.get("control"):
            continue
        score = find.get("score") or {}
        chains = sorted({"given" if part.get("chain") == "random" else str(part.get("chain"))
                         for part in (score.get("parts") or {}).values() if part.get("value")})
        found[str(find["law"])] = {"score": score.get("score"), "chains": chains, "d": score.get("d")}
    return found


def _reaches(values: list, cap: float) -> bool:
    return bool(values) and max(values) >= cap


def _at(values: list, cap: float) -> bool:
    return bool(values) and min(values) >= cap


def _bands(cap: float) -> tuple:
    return ("8 or below", f"8 to {cap:g}", f"{cap:g} to its cap", "at its cap")


def _band(degree: float, cap: float, own_cap: float) -> str:
    names = _bands(cap)
    if degree >= own_cap - AT_THE_CAP:
        return names[3]
    if degree >= cap:
        return names[2]
    return names[1] if degree > 8 else names[0]


def _quantile(values: list, q: float):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else None


def read(root: Path, caps=CAPS, own_cap: float | None = None) -> dict:
    design = design_of(root)
    own_cap = float(own_cap if own_cap is not None else (design.get("axes") or {}).get("dense_cap") or 32.0)
    degrees, memory, source = chain_degrees(root)
    ladder = sorted(int(n) for n in (design.get("ladder") or {}).get("base", []) + (design.get("ladder") or {})
                    .get("deep", [])) or sorted({n for _, n in degrees})
    going, in_a_row = going_chains(root)
    scoring = scoring_chains(root)
    sizes = sorted({n for _, n in degrees})
    laws_at = defaultdict(set)
    for law, n in degrees:
        laws_at[n].add(law)
    out = {"contract": CONTRACT, "bundle": Path(root).name, "own_cap": own_cap, "source": source,
           "sizes_in_a_row": in_a_row, "ladder": ladder, "laws_by_size": {str(n): len(laws_at[n]) for n in sizes},
           "caps": {}}
    for cap in caps:
        touched_chains, chains_at, touched_laws = {}, {}, {}
        for n in sizes:
            chains = [(law, name, values) for (law, m), named in degrees.items() if m == n
                      for name, values in named.items()]
            touched_chains[str(n)] = [sum(1 for *_, v in chains if _reaches(v, cap)), len(chains)]
            chains_at[str(n)] = sum(1 for *_, v in chains if _at(v, cap))
            touched_laws[str(n)] = sum(1 for law in laws_at[n]
                                       if any(_reaches(v, cap) for v in degrees[(law, n)].values()))
        held, held_laws = defaultdict(int), {}
        for (law, n), (_, action, still) in going.items():
            if action not in GOING or not still or n not in ladder:
                continue
            place = ladder.index(n)
            run = ladder[max(0, place - in_a_row + 1):place + 1]
            if len(run) < in_a_row:
                continue
            if all(all(_at((degrees.get((law, m)) or {}).get(name, []), cap) for m in run) for name in still):
                held[str(n)] += 1
                held_laws.setdefault(law, n)
        laws_scoring = []
        for law, entry in sorted(scoring.items(), key=lambda kv: -(kv[1]["score"] or 0)):
            reached = sorted({n for (l, n), named in degrees.items() if l == law
                              for name in entry["chains"] if _reaches(named.get(name, []), cap)})
            laws_scoring.append({"law": law, "score": entry["score"], "d": entry["d"], "chains": entry["chains"],
                                 "scoring_chain_reaches_at": reached, "held_back_at": held_laws.get(law)})
        bands = {}
        for n in sizes:
            by = defaultdict(list)
            for (law, m), seeds in memory.items():
                if m != n or not degrees.get((law, m)):
                    continue
                densest = max(max(v) for v in degrees[(law, m)].values() if v)
                by[_band(densest, cap, own_cap)] += list(seeds.values())
            bands[str(n)] = {band: {"seeds": len(by[band]), "median_bytes": int(statistics.median(by[band])),
                                    "max_bytes": max(by[band])} for band in _bands(cap) if by.get(band)}
        out["caps"][f"{cap:g}"] = {
            "chains_reaching_it": touched_chains, "chains_at_it_on_every_seed": chains_at,
            "laws_with_a_chain_reaching_it": touched_laws, "laws_held_back_as_too_dense": dict(held),
            "scoring_laws": laws_scoring,
            "scoring_laws_held_back": sum(1 for entry in laws_scoring if entry["held_back_at"]),
            "memory_by_densest_chain": bands}
    top = max((n for (_, n) in memory), default=None)
    if top is not None:
        seeds = [value for (_, n), by in memory.items() if n == top for value in by.values()]
        out["deeper"] = {"from_n": top, "reading": "memory a seed, scaled by the sizes' ratio (memory grows about as N)",
                         **{str(n): {"median_bytes": int(statistics.median(seeds) * n / top),
                                     "p90_bytes": int(_quantile(seeds, 0.9) * n / top),
                                     "max_bytes": int(max(seeds) * n / top)} for n in DEEPER if n > top}}
    return out


def _gb(value) -> str:
    return f"{value / 1e9:.2f} GB" if value is not None else "-"


def render(found: dict) -> str:
    lines = [f"the mean degree cap read on a bundle ({found['contract']}), {found['bundle']}: its cap "
             f"{found['own_cap']:g}, read from {found['source']}; a law is held back as too dense when every chain "
             f"still going is at a cap on every seed at {found['sizes_in_a_row']} sizes in a row, before the "
             "let-through; a chain that reaches a lower cap would have ended there, so its readings at that size "
             "would differ too (not counted)",
             "laws by size: " + ", ".join(f"N={int(n):,} {k}" for n, k in found["laws_by_size"].items())]
    for cap, entry in found["caps"].items():
        lines.append(f"at a cap of {cap}:")
        lines.append("  chains reaching it: " + ", ".join(
            f"N={int(n):,} {a} of {b}" for n, (a, b) in entry["chains_reaching_it"].items()))
        lines.append("  laws with a chain reaching it: " + ", ".join(
            f"N={int(n):,} {k}" for n, k in entry["laws_with_a_chain_reaching_it"].items()))
        lines.append("  laws held back as too dense: " + (", ".join(
            f"N={int(n):,} {k}" for n, k in sorted(entry["laws_held_back_as_too_dense"].items(),
                                                   key=lambda kv: int(kv[0]))) or "none"))
        lines.append(f"  scoring laws held back: {entry['scoring_laws_held_back']} of {len(entry['scoring_laws'])}")
        for law in entry["scoring_laws"]:
            if law["scoring_chain_reaches_at"] or law["held_back_at"]:
                lines.append(f"    {law['law'][:12]} score {law['score']} d {law['d']} ({', '.join(law['chains'])}): "
                             f"reaches it at {', '.join(f'{n:,}' for n in law['scoring_chain_reaches_at']) or '-'}"
                             + (f"; held back at {law['held_back_at']:,}" if law["held_back_at"] else ""))
        for n, bands in entry["memory_by_densest_chain"].items():
            if bands:
                lines.append(f"  memory a seed at N={int(n):,}: " + "; ".join(
                    f"{band} {b['seeds']} seeds, median {_gb(b['median_bytes'])}, max {_gb(b['max_bytes'])}"
                    for band, b in bands.items()))
    deeper = found.get("deeper")
    if deeper:
        lines.append(f"deeper, from N={deeper['from_n']:,} ({deeper['reading']}): " + "; ".join(
            f"N={int(n):,} median {_gb(v['median_bytes'])}, p90 {_gb(v['p90_bytes'])}, max {_gb(v['max_bytes'])}"
            for n, v in deeper.items() if n.isdigit()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/cap_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="a study bundle, unpacked or its .tar.zst")
    parser.add_argument("--caps", type=float, nargs="+", default=list(CAPS))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    from tools.replay_bundle import study_root
    root = args.bundle if args.bundle.is_dir() else study_root(args.bundle)
    found = read(root, caps=tuple(args.caps))
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
