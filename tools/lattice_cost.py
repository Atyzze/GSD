#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

CONTRACT = "gsd-lattice-cost-1"
TWINS = ("empty", "given")
FROM_N = 4096
LISTED = 40


def _rows(root: Path, name: str):
    path = Path(root) / "tables" / name
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def study_campaigns(root: Path) -> set[str]:
    study = json.loads((Path(root) / "study.json").read_text(encoding="utf-8"))
    return {str(c["campaign_id"]) for c in study.get("campaigns") or [] if c.get("study_design")}


def group_of(chain: str) -> str:
    return "twins" if chain in TWINS else "lattices"


def _cell() -> dict:
    return {"chains": 0, "work_units": 0, "seconds": 0.0, "moves": 0, "accepted_moves": 0, "unmoved": 0}


def chain_work(root: Path, campaigns: set[str]) -> dict:
    by_size = defaultdict(lambda: defaultdict(_cell))
    by_law = defaultdict(lambda: defaultdict(_cell))
    seeds_of = defaultdict(lambda: [0, 0])
    with_work = rows = 0
    for row in _rows(root, "chains.ndjson.gz"):
        if str(row.get("campaign_id")) not in campaigns or row.get("evidence") != "compact" or not row.get("ran"):
            continue
        rows += 1
        if row.get("work_units") is None:
            continue
        with_work += 1
        n, chain, law = int(row["n"]), str(row["chain"]), str(row["candidate_id"])
        moved = int(row.get("accepted_moves") or 0)
        for cell in (by_size[n][chain], by_law[(law, n)][group_of(chain)]):
            cell["chains"] += 1
            cell["work_units"] += int(row["work_units"])
            cell["seconds"] += float(row.get("seconds") or 0.0)
            cell["moves"] += int(row.get("moves") or 0)
            cell["accepted_moves"] += moved
            cell["unmoved"] += int(moved == 0 and int(row.get("moves") or 0) > 0)
        if group_of(chain) == "lattices":
            entry = seeds_of[(law, n, chain)]
            entry[0] += 1
            entry[1] += int(moved == 0)
    frozen = defaultdict(lambda: defaultdict(int))
    for (law, n, chain), (seeds, still) in seeds_of.items():
        if seeds and still == seeds:
            frozen[n][chain] += 1
    return {"rows": rows, "with_work": with_work, "by_size": by_size, "by_law": by_law, "frozen": frozen}


def scoring(root: Path) -> list[dict]:
    from graph_scale_dynamics.observability import law_score as L
    import score_list
    found = []
    controls = score_list.control_bundles(Path(root))
    for path in sorted(glob.glob(str(Path(root) / "campaign_*_reports_*" / "28-decision-engine.json"))):
        if Path(path).parent.name in controls:
            continue
        body = json.loads(Path(path).read_text(encoding="utf-8")).get("body") or {}
        for law, entry in sorted(((body.get("every_chain") or {}).get("laws") or {}).items()):
            chains, reading = score_list.chains_of_report(entry)
            result = L.score(chains, reading, references={})
            if result["score"] <= 0:
                continue
            parts = result.get("parts") or {}
            twins = max(float((parts.get(kind) or {}).get("points") or 0.0) for kind in ("empty", "random"))
            found.append({"law": str(law), "score": result["score"], "by": result["by"], "chain": result["chain"],
                          "to_n": result["to_n"], "twins_points": twins})
    return sorted(found, key=lambda row: (-row["score"], row["law"]))


def _share(part: float, whole: float):
    return round(part / whole, 4) if whole else None


def read(root: Path) -> dict:
    campaigns = study_campaigns(root)
    work = chain_work(root, campaigns)
    sizes = {}
    above = {"twins": _cell(), "lattices": _cell()}
    for n in sorted(work["by_size"]):
        chains = work["by_size"][n]
        groups = {"twins": _cell(), "lattices": _cell()}
        for chain, cell in chains.items():
            for key, value in cell.items():
                groups[group_of(chain)][key] += value
                if n >= FROM_N:
                    above[group_of(chain)][key] += value
        every = groups["twins"]["work_units"] + groups["lattices"]["work_units"]
        sizes[str(n)] = {"groups": groups, "lattice_share_of_work": _share(groups["lattices"]["work_units"], every),
                         "by_start": {chain: dict(cell, share_of_work=_share(cell["work_units"], every))
                                      for chain, cell in sorted(chains.items())},
                         "lattice_chains_frozen": dict(sorted(work["frozen"].get(n, {}).items()))}
    total = above["twins"]["work_units"] + above["lattices"]["work_units"]
    seconds = above["twins"]["seconds"] + above["lattices"]["seconds"]
    listed = []
    for row in scoring(root):
        own = {n: work["by_law"].get((row["law"], n)) for n in sorted({n for (law, n) in work["by_law"]
                                                                       if law == row["law"] and n >= FROM_N})}
        twins = sum((cell or {}).get("twins", {}).get("work_units", 0) for cell in own.values())
        lattices = sum((cell or {}).get("lattices", {}).get("work_units", 0) for cell in own.values())
        listed.append(dict(row, lattice_share_of_its_work=_share(lattices, twins + lattices),
                           only_a_lattice_reads=row["twins_points"] == 0))
    return {"contract": CONTRACT, "bundle": Path(root).name, "campaigns": sorted(campaigns),
            "chains_read": work["rows"], "chains_with_work": work["with_work"], "from_n": FROM_N,
            "above": {"groups": above, "lattice_share_of_work": _share(above["lattices"]["work_units"], total),
                      "lattice_share_of_seconds": _share(above["lattices"]["seconds"], seconds)},
            "sizes": sizes, "scoring": listed,
            "reading": ("Every chain of every finished seed of the study's campaigns, from the bundle's chains table "
                        "(841 on: each chain's moves, accepted moves, work in the campaign's unit and seconds). twins "
                        "are the chains from empty and from random, lattices the six lattice starts. A lattice chain "
                        "frozen at a size accepted no move on any of its law's seeds there: no edge changed. For each "
                        "scoring law, the share of its work above 4,096 that its lattice chains took, and whether a "
                        "twin chain earned any of the score's points (only_a_lattice_reads when none did).")}


def _units(value) -> str:
    for scale, unit in ((1e12, "T"), (1e9, "G"), (1e6, "M")):
        if value >= scale:
            return f"{value / scale:,.1f} {unit}"
    return f"{value:,.0f}"


def render(found: dict) -> str:
    lines = [f"the lattice starts' cost ({found['contract']}) on {found['bundle']}: {found['chains_read']:,} chains read, "
             f"{found['chains_with_work']:,} with their work"]
    if not found["chains_with_work"]:
        lines.append("this bundle's chains table carries no chain's work (it was made before 841): nothing to read")
        return "\n".join(lines)
    above = found["above"]
    lines.append(f"from N={found['from_n']:,}: the six lattice starts took {above['lattice_share_of_work']:.0%} of the "
                 f"work and {above['lattice_share_of_seconds']:.0%} of the engine's seconds")
    lines += ["", "| size | twins' work | lattices' work | lattices' share | lattice chains frozen |",
              "|---:|---:|---:|---:|---|"]
    for n, size in found["sizes"].items():
        frozen = ", ".join(f"{chain} {count}" for chain, count in size["lattice_chains_frozen"].items()) or "none"
        lines.append(f"| {int(n):,} | {_units(size['groups']['twins']['work_units'])} | "
                     f"{_units(size['groups']['lattices']['work_units'])} | "
                     f"{size['lattice_share_of_work']:.0%} | {frozen} |")
    if found["scoring"]:
        lines += ["", "| scoring law | score | by | chain | lattices' share of its work | a twin earns points |",
                  "|---|---:|---|---|---:|---|"]
        for row in found["scoring"][:LISTED]:
            share = row["lattice_share_of_its_work"]
            lines.append(f"| {row['law'][:12]} | {row['score']} | {row['by']} | {row['chain']} | "
                         f"{'' if share is None else f'{share:.0%}'} | {'no' if row['only_a_lattice_reads'] else 'yes'} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from read_bundle import scratch_dir, unpacked
    parser = argparse.ArgumentParser(description="tools/lattice_cost.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path, help="a study bundle, unpacked or its .tar.zst")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = unpacked(args.bundle, scratch_dir("gsd_lattice_"))
    found = read(root)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
