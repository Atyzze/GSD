#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import coverage_reading as C  # noqa: E402
import law_rows as L  # noqa: E402
from graph_scale_dynamics.observability.starts_reading import DEGREE_WITHIN, STRUCTURE_WITHIN  # noqa: E402

CONTRACT = "gsd-history-reading-1"
APART = ("starts_apart", "starts_apart_twice", "starts_apart_by_history")
REMEMBERS = "remembers"
LATTICES, LATTICE_DEGREE = L.LATTICES, L.LATTICE_DEGREE
CHANGED = "changed"
COLUMNS = ("n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction", "triangles_per_node",
           "squares_per_node", "kappa")
PROBES = ("d_s", "d_V", "d_B", "d_w")
ONE_PIECE = 0.98
PROBES_READ = 2
EMPTY_DEGREE = 0.5
CANDIDATE_FROM_N = 16_384
NAMES = {"empty": "empty", "given": "random"}
LOST = ("dense", "fell_apart", "melted", "not read")
NOT_NEW = ("unmoved", "holds")
KINDS = ("the empty start stays empty", "a lattice does not move", "every lattice is lost",
         "the starts move and still end apart")
STATES = {"PARKED": "parked", "EXTENDING": "still running", "STOPPED": "stopped", "HELD": "held", "DONE": "done"}
SHOWN = 60


def chain_at(values: list, n: int) -> dict | None:
    for row in values or []:
        if int(row[0]) == int(n):
            return dict(zip(COLUMNS, row, strict=False))
    return None


def readable(cell: dict | None) -> bool:
    if not cell:
        return False
    probes = sum(1 for key in PROBES if cell.get(key) is not None)
    return probes >= PROBES_READ and float(cell.get("giant_fraction") or 0.0) >= ONE_PIECE


def pattern(groups: list) -> str:
    return " / ".join("+".join(NAMES.get(chain, chain) for chain in sorted(group)) for group in groups)


def kind_of(entry: dict) -> str:
    fates = entry["fates"]
    if entry["empty_stays_empty"]:
        return KINDS[0]
    if any(fate in NOT_NEW for fate in fates.values()):
        return KINDS[1]
    if all(fate in LOST for fate in fates.values()):
        return KINDS[2]
    return KINDS[3]


def moved_by(cell: dict, lattice: str) -> str:
    degree = cell.get("mean_degree")
    if degree is not None and abs(float(degree) - LATTICE_DEGREE[lattice]) / LATTICE_DEGREE[lattice] > DEGREE_WITHIN:
        return "degree"
    return "structure"


def law_entry(law: str, chained: dict, ended: tuple[str, str], compact: dict) -> dict | None:
    starts = chained.get("starts_reading") or {}
    if not starts or starts.get("class") in (None, "not_read"):
        return None
    at_n = int(starts.get("at_n") or 0)
    values = chained.get("values") or {}
    cells = {name: chain_at(values.get(name), at_n) for name in values}
    fates = {lattice: (fate or [None])[0] or "not read" for lattice, fate in (starts.get("fates") or {}).items()}
    empty = cells.get("empty")
    degree = None if empty is None else empty.get("mean_degree")
    entry = {"law": law, "class": starts.get("class"), "state": ended[0], "ended": ended[1], "at_n": at_n,
             "trend": starts.get("trend"),
             "pattern": pattern(((starts.get("by_n") or {}).get(str(at_n)) or [None, []])[1]), "fates": fates,
             "empty_stays_empty": degree is not None and float(degree) < EMPTY_DEGREE,
             "random_readable": readable(cells.get("given")),
             "lattices_readable": sorted(name for name in LATTICES if readable(cells.get(name))
                                         and fates.get(name) not in NOT_NEW),
             "zero_t": bool(compact.get("zero_temperature")), "stratum": C.stratum(compact)}
    entry["kind"] = kind_of(entry)
    entry["kept_reach"] = {name: {"from_degree": LATTICE_DEGREE[name], "moved": moved_by(cells[name], name),
                                  **{k: cells[name].get(k) for k in ("mean_degree", "reach", *PROBES)}}
                           for name in entry["lattices_readable"] if fates.get(name) == CHANGED}
    return entry


def ending(entry: dict) -> str:
    return f"{STATES.get(entry['state'], entry['state'].lower())}: {entry['ended'] or 'no reason given'}"


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(entries: list[dict]) -> dict:
    remembers = [e for e in entries if e["class"] == REMEMBERS]
    apart = [e for e in entries if e["ended"] in APART]
    by_temperature = {}
    for name, flag in (("zero", True), ("finite", False)):
        group = [e for e in entries if e["zero_t"] is flag]
        hit = sum(1 for e in group if e["class"] == REMEMBERS)
        by_temperature[name] = {"laws": len(group), "remembers": hit, "share": share(hit, len(group))}
    strata = defaultdict(lambda: [0, 0])
    for e in entries:
        strata[e["stratum"]][0] += 1
        strata[e["stratum"]][1] += e["class"] == REMEMBERS
    fates = defaultdict(Counter)
    by_size = defaultdict(Counter)
    kinds = defaultdict(Counter)
    for e in remembers:
        for lattice, fate in e["fates"].items():
            fates[lattice][fate] += 1
        by_size[e["at_n"]][str(e["trend"])] += 1
        kinds[e["kind"]]["laws"] += 1
        kinds[e["kind"]]["zero temperature"] += e["zero_t"]
        kinds[e["kind"]][f"from {CANDIDATE_FROM_N:,}"] += e["at_n"] >= CANDIDATE_FROM_N
        kinds[e["kind"]]["random start read"] += e["random_readable"]
        kinds[e["kind"]]["a moved lattice read"] += bool(e["lattices_readable"])
    kept = [e for e in entries if e["kept_reach"]]
    candidates = sorted((e for e in remembers if e["at_n"] >= CANDIDATE_FROM_N
                         and (e["lattices_readable"] or e["random_readable"])),
                        key=lambda e: (-e["at_n"], -KINDS.index(e["kind"]), e["law"]))
    return {"laws": len(entries), "classes": dict(Counter(e["class"] for e in entries).most_common()),
            "remembers": len(remembers),
            "remembers_ended": dict(Counter(ending(e) for e in remembers).most_common()),
            "apart": len(apart), "apart_by_class": {k: dict(Counter(ending(e) for e in apart if e["class"] == k))
                                                    for k in sorted({e["class"] for e in apart})},
            "kinds": {k: dict(kinds[k]) for k in KINDS if k in kinds},
            "by_temperature": by_temperature,
            "by_stratum": {h: {"laws": n, "remembers": k, "share": share(k, n)}
                           for h, (n, k) in sorted(strata.items())},
            "trend_by_size": {str(n): dict(c.most_common()) for n, c in sorted(by_size.items())},
            "lattice_fates": {lattice: dict(c.most_common()) for lattice, c in sorted(fates.items())},
            "patterns": dict(Counter(e["pattern"] for e in remembers).most_common(12)),
            "candidates": [{k: e[k] for k in ("law", "at_n", "kind", "trend", "pattern", "fates", "lattices_readable",
                                              "random_readable", "state", "ended", "stratum", "zero_t")}
                           for e in candidates],
            "kept_reach": {"laws": len(kept), "by_class": dict(Counter(e["class"] for e in kept).most_common()),
                           "by_lattice": dict(Counter(k for e in kept for k in e["kept_reach"]).most_common()),
                           "by_what_moved": dict(Counter(f"{k}, {c['moved']}" for e in kept
                                                         for k, c in e["kept_reach"].items()).most_common()),
                           "by_size": {str(n): k for n, k in sorted(Counter(e["at_n"] for e in kept).items())},
                           "ended": dict(Counter(ending(e) for e in kept).most_common()),
                           "laws_from": [{k: e[k] for k in ("law", "class", "at_n", "kept_reach", "state", "ended")}
                                         for e in sorted(kept, key=lambda e: (-e["at_n"], e["law"]))
                                         if e["at_n"] >= CANDIDATE_FROM_N]}}


def ended_by(root: Path) -> dict[str, tuple[str, str]]:
    out = {}
    with gzip.open(root / "tables" / "laws.ndjson.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[str(row["candidate_id"])] = (str(row.get("state") or ""),
                                             str(row.get("state_reason") or "").replace("decision engine: ", ""))
    return out


def entries_of(root: Path) -> list[dict]:
    ended = ended_by(root)
    specs = {row["law"]: row["spec"] for row in L.rows(root)}
    out = []
    for part in L.campaigns(root):
        engine = L.body(root / str(part.get("bundle") or ""))
        for law, chained in ((engine.get("every_chain") or {}).get("laws") or {}).items():
            if law in specs:
                entry = law_entry(law, chained, ended.get(law, ("", "")), specs[law])
                if entry is not None:
                    out.append(entry)
    return out


def reading(root: Path) -> dict:
    return {"contract": CONTRACT, "bundle": root.name,
            "rules": {"one_piece": ONE_PIECE, "probes_read": PROBES_READ, "empty_degree": EMPTY_DEGREE,
                      "candidate_from_n": CANDIDATE_FROM_N, "a lattice does not count as read when": list(NOT_NEW)},
            **summarize(entries_of(root))}


def _num(value) -> str:
    return "" if value is None else f"{float(value):.3g}"


def _pct(value: float | None) -> str:
    return "" if value is None else f"{value:.1%}"


def _pairs(counts: dict) -> str:
    return "; ".join(f"{k} {n:,}" for k, n in counts.items())


def render(result: dict) -> str:
    rem = result["remembers"]
    lines = [f"# The laws whose starts end apart, from {result['bundle']}", "",
             f"Of {result['laws']:,} blind laws whose starts were read at a size from 1,024, {rem:,} read "
             "`remembers`: their starts end apart at the largest size read and no lattice holds its shape. "
             f"Recorded, never judged ({result['contract']}).", "",
             "## What keeps them apart", "",
             "Each law is put in the first of these that fits it.", "",
             "| kind | laws | share | at zero temperature | read from 16,384 | random start read "
             "| a moved lattice read |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for kind, c in result["kinds"].items():
        lines.append(f"| {kind} | {c['laws']:,} | {_pct(share(c['laws'], rem))} | {c.get('zero temperature', 0):,} | "
                     f"{c.get('from 16,384', 0):,} | {c.get('random start read', 0):,} | "
                     f"{c.get('a moved lattice read', 0):,} |")
    lines += ["", "`the empty start stays empty`: the start from no edges has fewer than "
              f"{result['rules']['empty_degree']} edges a node at the largest size, so the law cannot grow a graph "
              "from nothing and that start differs from the rest by that alone. `a lattice does not move`: a lattice "
              "ends `unmoved` (the law leaves it as it began). `every lattice is lost`: each lattice melted, fell "
              "apart or went dense, and they still differ from each other or from the random start. The last row is "
              "what is left: every start moved, at least one lattice kept part of its reach, and they still end apart.",
              "", "## How they ended", "", "| state: decision | laws |", "|---|---:|"]
    lines += [f"| {k} | {n:,} |" for k, n in result["remembers_ended"].items()]
    lines += ["", f"{result['apart']:,} laws were decided on their starts disagreeing, by their class:", ""]
    lines += [f"- {k}: {_pairs(v)}" for k, v in result["apart_by_class"].items()]
    lines += ["", "`starts_apart` marks a law apart once and lets it run on; a second time "
              "(`starts_apart_twice`) or apart at every size it was read (`_by_history`) parks it. The laws that "
              "hold or select run on whatever their starts do.",
              "", "## Where", "", "| temperature | laws | remember | share |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {g['laws']:,} | {g['remembers']:,} | {_pct(g['share'])} |"
              for k, g in result["by_temperature"].items()]
    lines += ["", "| stratum | laws | remember | share |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {g['laws']:,} | {g['remembers']:,} | {_pct(g['share'])} |"
              for k, g in result["by_stratum"].items()]
    lines += ["", "## Whether the starts come together as the graph grows", "",
              "Between the first and the largest size read: `merging` some starts come together, `splitting` some "
              "part, `regrouping` both, `steady` neither. A law read at one size has no trend.", "",
              "| largest size read | trends |", "|---:|---|"]
    lines += [f"| {int(n):,} | {_pairs(c)} |" for n, c in result["trend_by_size"].items()]
    lines += ["", "## What the lattice starts did", "", "| lattice | fates |", "|---|---|"]
    lines += [f"| {k} | {_pairs(c)} |" for k, c in result["lattice_fates"].items()]
    lines += ["", "## The most common ways they part", "",
              "Starts in one group are written together; groups are split by `/`.", "",
              "| groups at the largest size | laws |", "|---|---:|"]
    lines += [f"| {k} | {n:,} |" for k, n in result["patterns"].items()]
    cands = result["candidates"]
    lines += ["", f"## Read from {result['rules']['candidate_from_n']:,}, with a start one piece and read", "",
              f"{len(cands):,} laws have a start whose graph is one piece and read by two probes or more, where that "
              "start is the random one or a lattice that moved. These are the laws among those that remember a study "
              "of neighbourhoods would look at first.", "",
              "| law | size | kind | trend | groups | lattice fates | read |", "|---|---:|---|---|---|---|---|"]
    lines += [f"| `{c['law'][:12]}` | {c['at_n']:,} | {c['kind']} | {c['trend']} | {c['pattern']} | "
              + ", ".join(f"{k} {v}" for k, v in sorted(c["fates"].items()))
              + f" | {', '.join(c['lattices_readable'] + (['random'] if c['random_readable'] else []))} |"
              for c in cands[:SHOWN]]
    if len(cands) > SHOWN:
        lines += ["", f"and {len(cands) - SHOWN:,} more in the JSON."]
    kept = result["kept_reach"]
    lines += ["", "## A lattice that keeps its reach and changes up close", "",
              f"In {kept['laws']:,} laws of any class a lattice ends `changed`, its graph one piece and read: it keeps "
              "the reach of its start, so its large-scale geometry survives, while either its edges a node move by "
              f"more than {DEGREE_WITHIN:.0%} (`degree`) or, its degree within that, its triangles, squares or edges "
              f"a node move by more than {STRUCTURE_WITHIN:.0%} of the start's (`structure`). The class `holds` does "
              f"not count either. By class: {_pairs(kept['by_class'])}. By lattice and what moved: "
              f"{_pairs(kept['by_what_moved'])}. By largest size read: "
              + "; ".join(f"{int(n):,} {k:,}" for n, k in kept["by_size"].items()) + ".", "",
              "| state: decision | laws |", "|---|---:|"]
    lines += [f"| {k} | {n:,} |" for k, n in kept["ended"].items()]
    lines += ["", f"Those read from {result['rules']['candidate_from_n']:,}:", "",
              "| law | class | size | lattice | moved | degree | reach | d_s | d_V | d_B | d_w | state: decision |",
              "|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---|"]
    for e in kept["laws_from"][:SHOWN]:
        for name, c in e["kept_reach"].items():
            lines.append(f"| `{e['law'][:12]}` | {e['class']} | {e['at_n']:,} | {name} | {c['moved']} | "
                         f"{c['from_degree']} to {_num(c['mean_degree'])} | {_num(c['reach'])} | "
                         + " | ".join(_num(c[k]) for k in PROBES)
                         + f" | {STATES.get(e['state'], e['state'])}: {e['ended']} |")
    if len(kept["laws_from"]) > SHOWN:
        lines += ["", f"and {len(kept['laws_from']) - SHOWN:,} more in the JSON."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/history_reading.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle (.tar.zst) or its unpacked folder")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    from read_bundle import unpacked
    with tempfile.TemporaryDirectory(prefix="gsd-history-") as scratch:
        result = reading(unpacked(Path(args.bundle), Path(scratch)))
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = render(result)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text[:7000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
