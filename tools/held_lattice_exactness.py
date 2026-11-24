#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-held-lattice-exactness-2"
EXACT_AT_N = 4096
KEPT = ("holds", "unmoved")
SHAPES = ("one_space", "grows", "converts", "selects", "holds")
MIN_N = 4096
BANDS = ((0.001, "within 0.1%"), (0.01, "within 1%"), (0.05, "within 5%"))
FURTHER = "further"
UNREAD = "not read at its size"


def _bodies(bundle: Path):
    study = json.loads((bundle / "study.json").read_text(encoding="utf-8"))
    for campaign in study.get("campaigns") or []:
        if not campaign.get("law_budget") or (campaign.get("study_design") or {}).get("arm"):
            continue
        found = sorted((bundle / str(campaign.get("bundle") or "")).glob("28-*.json"))
        if found:
            document = json.loads(found[0].read_text(encoding="utf-8"))
            yield str(campaign["campaign_id"]), document.get("body", document)


@lru_cache(maxsize=None)
def exact() -> dict:
    from graph_scale_dynamics.measurements import starts as the_starts
    from graph_scale_dynamics.measurements.structure_census import census
    out = {}
    for start in the_starts.known_lattices():
        if not start.reaches(EXACT_AT_N):
            continue
        counted = census(EXACT_AT_N, start.edges(EXACT_AT_N))
        out[start.name] = (2.0 * float(counted.get("edges") or 0) / EXACT_AT_N,
                           float(counted.get("squares") or 0) / EXACT_AT_N,
                           float((counted.get("cliques") or {}).get("triangles") or 0) / EXACT_AT_N)
    return out


def band(lattice: str, degree: float, squares: float, triangles: float = 0.0) -> str:
    k, q, t = exact()[lattice]
    off = max(abs(degree - k) / k, abs(squares - q) / max(q, 1.0), abs(triangles - t) / max(t, 1.0))
    for limit, name in BANDS:
        if off < limit:
            return name
    return FURTHER


def _at(values: dict, columns: list[str], chain: str, n: int, *, at_or_below: bool = False) -> tuple | None:
    found = None
    for row in values.get(chain) or []:
        record = dict(zip(columns, row, strict=False))
        size = int(record["n"])
        if (size == int(n) or (at_or_below and size <= int(n))) and None not in (
                record.get("mean_degree"), record.get("squares_per_node"), record.get("triangles_per_node")):
            if found is None or size > found[0]:
                found = (size, float(record["mean_degree"]), float(record["squares_per_node"]),
                         float(record["triangles_per_node"]))
    return found[1:] if found else None


def read(bundle: Path) -> dict:
    held, scored = Counter(), Counter()
    held_by_lattice: dict[str, Counter] = {name: Counter() for name in exact()}
    laws_by_band: dict[str, list[str]] = {}
    unread = 0
    for _campaign, body in _bodies(Path(bundle)):
        every = body.get("every_chain") or {}
        columns = list(every.get("value_columns") or [])
        for law, chain in (every.get("laws") or {}).items():
            five = chain.get("starts_reading") or {}
            values = chain.get("values") or {}
            at_n = int(five.get("at_n") or 0)
            if five.get("class") in SHAPES and at_n >= MIN_N:
                for lattice, fate in (five.get("fates") or {}).items():
                    if lattice in exact() and (fate or [None])[0] in KEPT:
                        found = _at(values, columns, lattice, at_n)
                        if found is None:
                            unread += 1
                            continue
                        name = band(lattice, *found)
                        held[name] += 1
                        held_by_lattice[lattice][name] += 1
                        laws_by_band.setdefault(name, []).append(f"{law[:12]}:{lattice}")
            score = chain.get("score") or {}
            if int(score.get("score") or 0) > 0 and score.get("chain") in exact():
                top = int(score.get("to_n") or chain.get("top_n") or 0)
                found = _at(values, columns, score["chain"], top, at_or_below=True)
                scored[band(score["chain"], *found) if found else UNREAD] += 1
    order = [name for _limit, name in BANDS] + [FURTHER]
    return {"contract": CONTRACT, "bundle": Path(bundle).name, "exact": {k: list(v) for k, v in exact().items()},
            "reading": ("each lattice a survey batch's law read as a shape held or left unmoved at the size its five "
                        f"starts were read (from {MIN_N:,}), and each scored law's scoring lattice at the size it scored "
                        "to (or the largest below it with values): how near its chain's mean degree, squares and "
                        "triangles a node end to the exact lattice's, the narrowest band all three are in"),
            "held": {"lattices": sum(held.values()), "by_band": {k: held.get(k, 0) for k in order},
                     "by_lattice": {lat: {k: c.get(k, 0) for k in order} for lat, c in held_by_lattice.items()},
                     "not_read": unread,
                     "laws_by_band": {k: sorted(v) for k, v in laws_by_band.items() if k != order[0]}},
            "scored": {"laws": sum(scored.values()),
                       "by_band": {k: scored.get(k, 0) for k in order + [UNREAD] if k in order or scored.get(k)}}}


def markdown(found: dict) -> str:
    held, scored = found["held"], found["scored"]
    lines = ["# How near its exact lattice each held lattice ends", "", f"From `{found['bundle']}`: {found['reading']}.",
             "", f"Lattices held or left unmoved by laws read as a shape: {held['lattices']}"
             f" ({held['not_read']} not read at their size).", "", "| lattice | " + " | ".join(held["by_band"]) + " |",
             "|---|" + "---:|" * len(held["by_band"])]
    for lattice, by in held["by_lattice"].items():
        lines.append(f"| {lattice} | " + " | ".join(str(v) for v in by.values()) + " |")
    lines.append("| all | " + " | ".join(str(v) for v in held["by_band"].values()) + " |")
    lines += ["", f"Scored laws, by their scoring lattice: {scored['laws']}: "
              + ", ".join(f"{k} {v}" for k, v in scored["by_band"].items()) + "."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/held_lattice_exactness.py: see docs/TOOLS.md")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    found = read(args.bundle)
    args.json.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = markdown(found)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
