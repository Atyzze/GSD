from __future__ import annotations

import statistics

import numpy as np

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.measurements import known_answers
from graph_scale_dynamics.research import boltzmann_known_answers as B
from graph_scale_dynamics.research.planted_geometries import random_regular

CONTRACT = "gsd-start-admission-1"
DIAMOND = "periodic_diamond_lattice"
DIAMOND_STEPS = ((1, 1, -1), (1, -1, 1), (-1, 1, 1), (-1, -1, -1))
ALONE = {"swap": 0.0, "sweeps": 1, "locality": 0.0}


def diamond_box(n: int) -> tuple[int, int, int] | None:
    box = known_answers._box(8 * int(n))
    return box if box is not None and all(side % 4 == 0 for side in box) else None


def periodic_diamond(n: int) -> list[tuple[int, int]] | None:
    box = diamond_box(n)
    if box is None:
        return None
    a, b, c = box
    x, y, z = (axis.reshape(-1) for axis in np.meshgrid(np.arange(a), np.arange(b), np.arange(c), indexing="ij"))
    same_parity = (x % 2 == y % 2) & (y % 2 == z % 2)
    kept = same_parity & (((x + y + z) % 4) <= 1)
    label = np.full(a * b * c, -1, dtype=np.int64)
    label[kept] = np.arange(int(kept.sum()), dtype=np.int64)
    assert int(kept.sum()) == int(n)
    even = kept & ((x + y + z) % 4 == 0)
    here, ends = [], []
    for dx, dy, dz in DIAMOND_STEPS:
        to = (((x[even] + dx) % a) * b + (y[even] + dy) % b) * c + (z[even] + dz) % c
        assert bool((label[to] >= 0).all())
        here.append(label[even])
        ends.append(label[to])
    return known_answers._unique_pairs(int(n), np.concatenate(here), np.concatenate(ends))


def edges_of(family: str, n: int) -> list[tuple[int, int]] | None:
    return periodic_diamond(n) if family == DIAMOND else known_answers.edges(family, int(n))


def degree_of(n: int, edges) -> int:
    counts = np.bincount(np.asarray(edges, dtype=np.int64).reshape(-1), minlength=int(n))
    if counts.min() != counts.max():
        raise ValueError(f"not a regular graph: degrees {int(counts.min())} to {int(counts.max())}")
    return int(counts[0])


def law_of(op: str, degree: int) -> dict:
    anchored = "k" in dsl.OPERATORS[op]["params"]
    return B.law_of([B._term(op, 1.0, int(degree) if anchored else None)], ALONE)


def measure(criterion: dict, energy, operators=None) -> list[dict]:
    rows = []
    for lattice in criterion["lattices"]:
        for n in criterion["sizes"]:
            edges = edges_of(lattice["family"], int(n))
            if edges is None:
                rows.append({"name": lattice["name"], "n": int(n), "built": False})
                continue
            degree = degree_of(int(n), edges)
            wirings = [random_regular(int(n), degree, int(seed))[1] for seed in criterion["seeds"]]
            for op in operators or sorted(dsl.OPERATORS):
                law = law_of(op, degree)
                on_lattice = float(energy(law, int(n), edges)) / int(n)
                on_random = [float(energy(law, int(n), wiring)) / int(n) for wiring in wirings]
                rows.append({"name": lattice["name"], "n": int(n), "built": True, "degree": degree, "op": op,
                             "lattice": on_lattice, "random": on_random,
                             "random_mean": statistics.fmean(on_random),
                             "random_sd": statistics.stdev(on_random) if len(on_random) > 1 else None,
                             "difference": on_lattice - statistics.fmean(on_random)})
    return rows


def tells(differences: dict, criterion: dict) -> bool:
    sizes = sorted(differences)
    if not sizes or sizes != sorted(int(n) for n in criterion["sizes"]):
        return False
    first, last = abs(differences[sizes[0]]), abs(differences[sizes[-1]])
    return last >= float(criterion["tells_at_least"]) and last >= float(criterion["keeps_at_least"]) * first


def judge(criterion: dict, rows: list[dict]) -> dict:
    lattices = []
    for lattice in criterion["lattices"]:
        own = [row for row in rows if row["name"] == lattice["name"]]
        built = bool(own) and all(row["built"] for row in own)
        degree = next((row["degree"] for row in own if row.get("built")), None)
        by_op: dict[str, dict] = {}
        for row in own:
            if row.get("built"):
                by_op.setdefault(row["op"], {})[int(row["n"])] = row["difference"]
        told_by = sorted(op for op, differences in by_op.items() if tells(differences, criterion))
        under_cap = degree is not None and degree < float(criterion["mean_degree_cap"])
        admitted = bool(built and under_cap and told_by)
        lattices.append({"name": lattice["name"], "family": lattice["family"], "dimension": lattice["dimension"],
                         "degree": degree, "built_at_every_size": built, "under_the_cap": bool(under_cap),
                         "told_by": told_by, "admitted": admitted,
                         "expected_admitted": bool(lattice["admitted"]), "expected_told_by": sorted(lattice["told_by"]),
                         "admitted_as_expected": admitted == bool(lattice["admitted"]),
                         "told_as_expected": told_by == sorted(lattice["told_by"]),
                         "differences": {op: {str(n): d for n, d in sorted(found.items())}
                                         for op, found in sorted(by_op.items())}})
    return {"contract": CONTRACT, "sizes": list(criterion["sizes"]), "seeds": list(criterion["seeds"]),
            "tells_at_least": criterion["tells_at_least"], "keeps_at_least": criterion["keeps_at_least"],
            "lattices": lattices, "rows": rows,
            "admitted": [entry["name"] for entry in lattices if entry["admitted"]],
            "not_admitted": [entry["name"] for entry in lattices if not entry["admitted"]],
            "told_otherwise_than_expected": [entry["name"] for entry in lattices if not entry["told_as_expected"]],
            "passes": all(entry["admitted_as_expected"] for entry in lattices)}


def _number(value: float) -> str:
    return "0" if abs(value) < 5e-7 else f"{value:+.4g}"


def render(judged: dict) -> str:
    sizes = [str(n) for n in judged["sizes"]]
    lines = ["# Which lattices a law of the fourteen terms can tell from a random graph", "",
             f"Judged against `{judged.get('criterion', 'its criterion')}`, committed before this reading. "
             f"{'It passes' if judged['passes'] else 'It does not pass'}: "
             f"{len(judged['admitted'])} of {len(judged['lattices'])} lattices are admitted "
             f"({', '.join(judged['admitted']) or 'none'}), and not {', '.join(judged['not_admitted']) or 'none'}.", "",
             "A term tells a lattice when its energy a node there, taken alone with coupling 1, differs from its mean "
             "on random regular graphs of the same size and degree by at least "
             f"{judged['tells_at_least']} at the largest size and by at least {judged['keeps_at_least']} of its "
             "difference at the smallest: an amount a node that does not shrink with N. Sizes read: "
             f"{', '.join(f'{int(n):,}' for n in sizes)} nodes; {len(judged['seeds'])} random graphs a size.", "",
             "| lattice | dimension | neighbours | admitted | told by | as expected |", "|---|---:|---:|---|---|---|"]
    for entry in judged["lattices"]:
        expected = "yes" if entry["told_as_expected"] else (
            "expected " + (", ".join(f"`{op}`" for op in entry["expected_told_by"]) or "none"))
        lines.append(f"| {entry['name']} | {entry['dimension']} | {entry['degree']} | "
                     f"{'yes' if entry['admitted'] else 'no'} | "
                     f"{', '.join(f'`{op}`' for op in entry['told_by']) or 'no term'} | {expected} |")
    lines += ["", "## Every term on every lattice", "",
              "The lattice's energy a node less the random graphs' mean, at each size; a term that reads the same on "
              "both at every size is left out.", ""]
    for entry in judged["lattices"]:
        lines += [f"### {entry['name']}", "", "| term | " + " | ".join(f"{int(n):,}" for n in sizes) + " | tells |",
                  "|---|" + "---:|" * len(sizes) + "---|"]
        shown = 0
        for op, found in entry["differences"].items():
            if all(abs(found.get(n, 0.0)) < 5e-7 for n in sizes):
                continue
            shown += 1
            lines.append(f"| `{op}` | " + " | ".join(_number(found[n]) if n in found else "not built" for n in sizes)
                         + f" | {'yes' if op in entry['told_by'] else 'no'} |")
        if not shown:
            lines.append("| every term | " + " | ".join("0" for _ in sizes) + " | no |")
        lines.append("")
    return "\n".join(lines)
