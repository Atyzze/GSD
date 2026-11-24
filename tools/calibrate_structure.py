#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.measurements import calibration as cal  # noqa: E402
from graph_scale_dynamics.measurements.structure_census import (  # noqa: E402
    CENSUS_CONTRACT, GAP_MAX_N, census,
)

TABLE = ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "structure_thresholds.json"
CONTRACT = "structure-thresholds-1"
GAP_WINDOW = (4096, GAP_MAX_N)
DIAMETER_WINDOW = (4096, 262144)
SEEDS = (0, 1, 2)
FINITE = {
    "periodic_ring": 1.0, "periodic_square_lattice": 2.0, "periodic_triangular_lattice": 2.0,
    "periodic_honeycomb_lattice": 2.0, "periodic_cubic_lattice": 3.0,
    "periodic_hypercubic_lattice_4d": 4.0, "sierpinski_gasket": cal.SIERPINSKI_DS,
    "sierpinski_carpet": None, "uniform_random_tree": cal.CRT_DS,
}
NOT_FINITE = ("random_4_regular", "random_3_regular", "balanced_binary_tree",
              "erdos_renyi_sparse", "erdos_renyi_mid", "erdos_renyi_dense")
READ_NOT_FINITE = ("erdos_renyi_degree_2", "erdos_renyi_degree_6")


def _family(name: str) -> dict:
    return next(f for f in cal.CALIBRATION_FAMILIES if f["name"] == name)


def _one(task):
    name, parameter, seed = task
    family = _family(name)
    builder = family.get("build_seeded")
    n, edges = builder(parameter, seed) if builder else family["build"](parameter)
    record = census(n, edges)
    giant = record["largest_component"]
    return {"family": name, "parameter": parameter, "seed": seed, "n": int(n),
            "giant": int(giant["size"]), "diameter": int(giant["diameter"]["lower_bound"]),
            "gap": (giant["spectral_gap"] or {}).get("value"),
            "gap_method": (giant["spectral_gap"] or {}).get("method")}


def tasks(names=None) -> list:
    out = []
    for name in (list(FINITE) + list(NOT_FINITE) if names is None else list(names)):
        family = _family(name)
        seeds = SEEDS if family.get("graph_varies_per_seed") else (0,)
        for parameter in family["ladder"]:
            n = cal.family_rung_size(family, parameter)
            if GAP_WINDOW[0] <= n <= DIAMETER_WINDOW[1]:
                out.extend((name, parameter, seed) for seed in seeds)
    return out


def _slope(points: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    points = [(x, y) for x, y in points if x and y and x > 0 and y > 0]
    if len({x for x, _ in points}) < 2:
        return None, None
    lx = np.log([p[0] for p in points])
    ly = np.log([p[1] for p in points])
    slope, intercept = np.polyfit(lx, ly, 1)
    if len(points) < 3:
        return float(slope), None
    resid = ly - (slope * lx + intercept)
    se = math.sqrt(float(resid @ resid) / (len(points) - 2) / float(((lx - lx.mean()) ** 2).sum()))
    return float(slope), se


def exponents(rows: list[dict], names=None) -> dict:
    fams = {}
    for name in (list(FINITE) + list(NOT_FINITE) if names is None else list(names)):
        mine = [r for r in rows if r["family"] == name]
        gap_pts = [(r["n"], r["gap"]) for r in mine if GAP_WINDOW[0] <= r["n"] <= GAP_WINDOW[1]]
        diam_pts = [(r["n"], r["diameter"]) for r in mine if DIAMETER_WINDOW[0] <= r["n"] <= DIAMETER_WINDOW[1]]
        a_gap, se_gap = _slope(gap_pts)
        a_diam, se_diam = _slope(diam_pts)
        d_s = FINITE.get(name)
        fams[name] = {"finite_dimension": name in FINITE,
                      "expected_gap_exponent": (round(-2.0 / d_s, 4) if d_s else None),
                      "gap_exponent": a_gap, "gap_exponent_se": se_gap, "gap_points": len(gap_pts),
                      "diameter_exponent": a_diam, "diameter_exponent_se": se_diam,
                      "diameter_points": len(diam_pts),
                      "sizes": sorted({r["n"] for r in mine})}
    return fams


def thresholds(fams: dict) -> dict:
    finite = {k: v for k, v in fams.items() if v["finite_dimension"]}
    other = {k: v for k, v in fams.items() if not v["finite_dimension"]}
    open_families = {k: v for k, v in other.items() if k != "balanced_binary_tree"}
    slowest = max(finite.items(), key=lambda kv: kv[1]["gap_exponent"])
    fastest = min(open_families.items(), key=lambda kv: kv[1]["gap_exponent"])
    gap = 0.5 * (slowest[1]["gap_exponent"] + fastest[1]["gap_exponent"])
    narrowest = min(finite.items(), key=lambda kv: kv[1]["diameter_exponent"])
    widest = max(other.items(), key=lambda kv: kv[1]["diameter_exponent"])
    diam = 0.5 * (narrowest[1]["diameter_exponent"] + widest[1]["diameter_exponent"])

    def margin(value, family):
        se = family[1]["gap_exponent_se"] if value is gap else family[1]["diameter_exponent_se"]
        edge = family[1]["gap_exponent"] if value is gap else family[1]["diameter_exponent"]
        return {"family": family[0], "exponent": round(edge, 4), "distance": round(abs(edge - value), 4),
                "in_standard_errors": (round(abs(edge - value) / se, 1) if se and se > 1e-6 else None),
                "exact": bool(se is not None and se <= 1e-6)}

    classified = {name: {"finite_dimension": v["finite_dimension"],
                         "gate_says_finite": bool(v["gap_exponent"] <= gap and v["diameter_exponent"] >= diam)}
                  for name, v in fams.items()}
    return {
        "gap_exponent_at_most": round(gap, 4),
        "diameter_exponent_at_least": round(diam, 4),
        "gap_margins": [margin(gap, slowest), margin(gap, fastest)],
        "diameter_margins": [margin(diam, narrowest), margin(diam, widest)],
        "classified": classified,
        "all_classified_right": all(c["finite_dimension"] == c["gate_says_finite"] for c in classified.values()),
        "rule": ("a law has a finite dimension when its gap exponent over N = 4,096 to 65,536 is at most "
                 "gap_exponent_at_most AND its diameter exponent over N = 4,096 to 262,144 is at least "
                 "diameter_exponent_at_least; each is the midpoint between the nearest families of the two "
                 "classes"),
    }


def _chained_task(task):
    from graph_scale_dynamics.research import chained_family as C
    ell, seed, n_target = task
    n, edges = C.chained_cubic(n_target, ell, seed)
    return {"ell": ell, "seed": seed, **C.read_graph(n, edges, rung=n_target, seed=seed)}


def _finite_task(task):
    from graph_scale_dynamics.research import chained_family as C
    name, parameter, seed = task
    family = _family(name)
    builder = family.get("build_seeded")
    n, edges = builder(parameter, seed) if builder else family["build"](parameter)
    return {"family": name, "parameter": parameter, "seed": seed, **C.read_graph(n, edges, seed=seed)}


def read_chained(workers: int, started: float, criterion_path: Path, out_path: Path) -> int:
    from graph_scale_dynamics.research import chained_family as C
    criterion = json.loads(Path(criterion_path).read_text(encoding="utf-8"))
    largest = int(criterion["largest"])
    chained_work = [(ell, seed, n) for ell in criterion["chains"] for seed in criterion["seeds"]
                    for n in criterion["sizes"]]
    finite_work = [task for task in tasks(list(FINITE)) if task[2] == 0
                   and cal.family_rung_size(_family(task[0]), task[1]) <= largest]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        chained_rows = list(pool.map(_chained_task, chained_work))
        finite_rows = list(pool.map(_finite_task, finite_work))
    chained = {}
    for ell in criterion["chains"]:
        for seed in criterion["seeds"]:
            rows = [r for r in chained_rows if r["ell"] == ell and r["seed"] == seed]
            chained[f"ell={ell}, seed {seed}"] = {"ell": ell, "seed": seed, "rows": rows, **C.judge(rows)}
    finite = {}
    for name in FINITE:
        rows = [r for r in finite_rows if r["family"] == name]
        if rows:
            finite[name] = {"rows": rows, "dimension": FINITE[name], **C.judge(rows)}
    out = {"contract": C.CHAINED_CONTRACT, "criterion": criterion["contract"],
           "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "seconds": round(time.time() - started, 1), "chains": list(criterion["chains"]),
           "sizes": list(criterion["sizes"]),
           "chained": chained, "finite_families": finite,
           "summary": {"chained_seeds": len(chained),
                       "the_rule_reads_finite": sum(1 for v in chained.values() if v["rule_finite"] is True),
                       "three_readings_agree": sum(1 for v in chained.values()
                                                   if v["three_readings"]["agree"] is True),
                       "finite_families": len(finite),
                       "finite_families_the_three_readings_accept": sum(
                           1 for v in finite.values() if v["three_readings"]["agree"] is True)}}
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    for key, value in chained.items():
        t = value["three_readings"]
        print(f"{key}: the rule reads it {'FINITE' if value['rule_finite'] else 'not finite'} "
              f"({value['rule_why']}); local d_s {t['local_d_s']}, gap-implied {t['gap_implied_d_s']}, bulk "
              f"exponent {t['bulk_exponent']}: the three readings {'AGREE' if t['agree'] else 'refuse'}")
    for key, value in finite.items():
        t = value["three_readings"]
        print(f"{key} (d = {value['dimension']}): rule finite {value['rule_finite']}; local d_s {t['local_d_s']}, "
              f"gap-implied {t['gap_implied_d_s']}, bulk exponent {t['bulk_exponent']}: agree {t['agree']}")
    print(json.dumps(out["summary"]))
    print(path)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/calibrate_structure.py: see docs/TOOLS.md")
    parser.add_argument("--check", action="store_true", help="recompute and compare with the committed table")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--read", action="store_true",
                        help="read the families added since the fit against the committed rule; writes nothing (529)")
    parser.add_argument("--read-chained", action="store_true",
                        help=("the chained cubic family and the finite families through the rule and the three "
                              "readings, at the criterion's sizes"))
    parser.add_argument("--criterion", type=Path, default=ROOT / "graph_scale_dynamics" / "resources" / "readings"
                        / "chained_cubic_criterion.json")
    parser.add_argument("--out", type=Path, default=ROOT / "graph_scale_dynamics" / "resources" / "readings"
                        / "chained_cubic_judged.json")
    args = parser.parse_args(argv)
    started = time.time()
    if args.read_chained:
        return read_chained(max(1, args.workers), started, args.criterion, args.out)
    if args.read:
        stored = json.loads(TABLE.read_text(encoding="utf-8"))["thresholds"]
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            rows = sorted(pool.map(_one, tasks(READ_NOT_FINITE)), key=lambda r: (r["family"], r["n"], r["seed"]))
        for name, v in exponents(rows, READ_NOT_FINITE).items():
            finite = bool(v["gap_exponent"] <= stored["gap_exponent_at_most"]
                          and v["diameter_exponent"] >= stored["diameter_exponent_at_least"])
            print(f"{name}: gap exponent {v['gap_exponent']:.4f} (finite at most {stored['gap_exponent_at_most']}), "
                  f"diameter exponent {v['diameter_exponent']:.4f} (finite at least "
                  f"{stored['diameter_exponent_at_least']}): the rule reads it "
                  f"{'FINITE' if finite else 'not finite'}, and it is not finite")
        return 0
    work = tasks()
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        rows = sorted(pool.map(_one, work), key=lambda r: (r["family"], r["n"], r["seed"]))
    fams = exponents(rows)
    table = {"contract": CONTRACT, "census_contract": CENSUS_CONTRACT,
             "gap_window": list(GAP_WINDOW), "diameter_window": list(DIAMETER_WINDOW),
             "families": fams, "thresholds": thresholds(fams), "rows": rows,
             "computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "seconds": round(time.time() - started, 1)}
    if args.check:
        stored = json.loads(TABLE.read_text(encoding="utf-8"))
        same = (stored["thresholds"]["gap_exponent_at_most"] == table["thresholds"]["gap_exponent_at_most"]
                and stored["thresholds"]["diameter_exponent_at_least"] == table["thresholds"]["diameter_exponent_at_least"])
        print("the committed thresholds reproduce" if same else "the thresholds moved: rerun without --check")
        return 0 if same else 1
    TABLE.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    t = table["thresholds"]
    print(f"gap exponent at most {t['gap_exponent_at_most']}, diameter exponent at least "
          f"{t['diameter_exponent_at_least']}; every family classified right: {t['all_classified_right']}")
    print(TABLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
