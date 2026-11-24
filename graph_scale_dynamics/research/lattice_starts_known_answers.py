from __future__ import annotations

import statistics
from concurrent.futures import ProcessPoolExecutor

from graph_scale_dynamics.measurements import known_answers

CONTRACT = "gsd-lattice-starts-known-answers-1"


def read_start(family: str, name: str, n: int, seed: int) -> dict:
    from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE, chain_probes
    row = {"lattice": name, "family": family, "n": int(n), "seed": int(seed)}
    if not known_answers.reaches(family, int(n)):
        return {**row, "built": False}
    edges = known_answers.edges(family, int(n))
    found = chain_probes(int(n), edges, seed=int(seed), name=name)
    probes = {}
    for probe in PROBE_VALUE:
        block = found.get(probe) or {}
        probes[probe] = {"value": float(block["value"]) if block.get("valid") else None,
                         "refusal": None if block.get("valid") else block.get("refusal")}
    return {**row, "built": True, "edges": len(edges), "half_volume_radius": found.get("half_volume_radius"),
            "probes": probes}


def _read(task: tuple) -> dict:
    return read_start(*task)


def measure(criterion: dict, workers: int = 1) -> list[dict]:
    tasks = [(lattice["family"], lattice["name"], int(n), int(seed)) for lattice in criterion["lattices"]
             for n in criterion["sizes"] for seed in criterion["seeds"]]
    if int(workers) <= 1:
        return [_read(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=int(workers)) as pool:
        return list(pool.map(_read, tasks))


def band_of(criterion: dict, lattice: dict, probe: str) -> tuple[float, float]:
    low, high = criterion["d_w_band"] if probe == "d_w" else criterion["bands"][str(lattice["dimension"])]
    return float(low), float(high)


def judge(criterion: dict, rows: list[dict]) -> dict:
    predicted = {(entry["lattice"], int(entry["n"]), entry["probe"]) for entry in criterion["predicted_to_refuse"]}
    top = max(int(n) for n in criterion["sizes"])
    cells, misses = [], []
    for lattice in criterion["lattices"]:
        for n in criterion["sizes"]:
            own = [row for row in rows if row["lattice"] == lattice["name"] and int(row["n"]) == int(n)]
            built = bool(own) and all(row.get("built") for row in own)
            for probe in criterion["probes"]:
                values = [row["probes"][probe]["value"] for row in own if row.get("built")]
                refusals = sorted({str(row["probes"][probe]["refusal"]) for row in own
                                   if row.get("built") and row["probes"][probe]["value"] is None})
                reads = built and len(values) == len(criterion["seeds"]) and all(v is not None for v in values)
                low, high = band_of(criterion, lattice, probe)
                median = statistics.median(values) if reads else None
                in_band = None if median is None else bool(low <= median <= high)
                at_the_top = None
                if reads and probe == "d_s" and int(n) == top:
                    at_the_top = bool(abs(median - lattice["dimension"]) <= float(criterion["d_s_within_at_the_top"]))
                expected_to_read = (lattice["name"], int(n), probe) not in predicted
                cell = {"lattice": lattice["name"], "dimension": lattice["dimension"], "n": int(n), "probe": probe,
                        "built": built, "reads": bool(reads), "expected_to_read": expected_to_read,
                        "values": values, "median": median, "band": [low, high], "in_band": in_band,
                        "within_at_the_top": at_the_top, "refusals": refusals}
                cells.append(cell)
                if bool(reads) != expected_to_read:
                    misses.append({**{k: cell[k] for k in ("lattice", "n", "probe")},
                                   "miss": "refused where a reading was predicted" if expected_to_read
                                   else "read where a refusal was predicted", "refusals": refusals})
                elif reads and not in_band:
                    misses.append({**{k: cell[k] for k in ("lattice", "n", "probe")}, "miss": "outside its band",
                                   "median": median, "band": [low, high]})
                elif at_the_top is False:
                    misses.append({**{k: cell[k] for k in ("lattice", "n", "probe")},
                                   "miss": "d_s further from the dimension at the largest size than allowed",
                                   "median": median})
    read = sum(1 for cell in cells if cell["reads"])
    return {"contract": CONTRACT, "sizes": list(criterion["sizes"]), "seeds": list(criterion["seeds"]),
            "probes": list(criterion["probes"]), "lattices": [dict(lattice) for lattice in criterion["lattices"]],
            "cells": cells, "rows": rows, "misses": misses, "read": read, "of": len(cells),
            "refused": [{k: cell[k] for k in ("lattice", "n", "probe", "refusals", "expected_to_read")}
                        for cell in cells if not cell["reads"]],
            "passes": not misses}


def _shown(cell: dict) -> str:
    if not cell["built"]:
        return "not built"
    if not cell["reads"]:
        return "refused (" + ", ".join(cell["refusals"]) + ")"
    mark = "" if cell["in_band"] and cell["within_at_the_top"] is not False else " !"
    return f"{cell['median']:.2f}{mark}"


def render(judged: dict) -> str:
    sizes = judged["sizes"]
    lines = ["# The six lattice starts, read by the instrument", "",
             "Judged against `lattice_starts_known_answers_criterion.json`, committed before this reading. "
             f"{'It passes' if judged['passes'] else 'It does not pass'}: the probes read {judged['read']} of "
             f"{judged['of']} cells (a start, a size and a probe), and {len(judged['misses'])} cells are not as "
             "predicted.", "",
             "Each start is built at each size and read as the fleet reads the graph of a chain from a given start, "
             f"on {len(judged['seeds'])} seeds; the number shown is the median. A mark (!) is a reading outside the "
             "band of the start's dimension, or a d_s at the largest size further from the dimension than allowed.", ""]
    for lattice in judged["lattices"]:
        lines += [f"## {lattice['name']} ({lattice['dimension']} dimensions, {lattice['neighbours']} neighbours)", "",
                  "| nodes | " + " | ".join(judged["probes"]) + " |", "|---:|" + "---:|" * len(judged["probes"])]
        for n in sizes:
            row = [cell for cell in judged["cells"] if cell["lattice"] == lattice["name"] and cell["n"] == int(n)]
            by_probe = {cell["probe"]: cell for cell in row}
            lines.append(f"| {int(n):,} | " + " | ".join(_shown(by_probe[probe]) for probe in judged["probes"]) + " |")
        lines.append("")
    lines += ["## Not as predicted", ""]
    if not judged["misses"]:
        lines.append("Nothing: every probe read or refused as predicted, and every reading is in its band.")
    for miss in judged["misses"]:
        detail = (f", median {miss['median']:.3f}" if isinstance(miss.get("median"), float) else "") + (
            f", refusal {', '.join(miss['refusals'])}" if miss.get("refusals") else "")
        lines.append(f"* {miss['lattice']} at {int(miss['n']):,} nodes, {miss['probe']}: {miss['miss']}{detail}.")
    lines.append("")
    return "\n".join(lines)
