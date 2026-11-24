#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "d_s_error_criterion.json"
CONTRACT = "gsd-d-s-error-judged-1"


def family_graph(name: str, parameter: int):
    from graph_scale_dynamics.measurements import calibration as C
    family = next(f for f in C.CALIBRATION_FAMILIES if f["name"] == name)
    return family["build"](parameter)


def read_case(name: str, parameter: int, seeds: int) -> dict:
    from graph_scale_dynamics.measurements import estimators as E
    n, edges = family_graph(name, parameter)
    adj = E.build_adjacency(n, edges)
    component = E.largest_component(n, adj)
    readings = []
    for seed in range(seeds):
        ret = E.return_probability(adj, component, np.random.default_rng(seed), keep_probes=True)
        readings.append(E.fit_ds(ret, len(component)))
    read = [r for r in readings if r.get("valid")]
    values = [float(r["d_s"]) for r in read]
    spread = statistics.stdev(values) if len(values) > 1 else None
    se = statistics.median(float(r["se"]) for r in read) if read else None
    analytic = statistics.median(float(r["analytic_se"]) for r in read) if read else None
    return {"case": name, "parameter": parameter, "n": n, "read": len(read), "seeds": seeds,
            "d_s_mean": round(statistics.fmean(values), 4) if values else None,
            "spread": None if spread is None else round(spread, 4), "se_median": None if se is None else round(se, 4),
            "analytic_se_median": None if analytic is None else round(analytic, 4),
            "ratio": None if not spread or se is None else round(se / spread, 3),
            "refusals": sorted({str(r.get("refusal")) for r in readings if not r.get("valid")})}


def judge(criterion: dict, rows: list[dict]) -> dict:
    judged = [row for row in rows if row["read"] >= 6]
    for row in rows:
        row["judged"] = row["read"] >= 6
        row["passes"] = (row["judged"] and row["ratio"] is not None and 0.5 <= row["ratio"] <= 2.0) if row["judged"] else None
    passes = len(judged) >= 5 and all(row["passes"] for row in judged)
    return {"contract": CONTRACT, "criterion": criterion["contract"], "committed_utc": criterion["committed_utc"],
            "cases": rows, "judged": len(judged), "passes": passes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="judge d_s's reported error against its seeds' spread")
    parser.add_argument("--json", type=Path, help="where to write the judged reading")
    args = parser.parse_args(argv)
    criterion = json.loads(CRITERION.read_text(encoding="utf-8"))
    rows = [read_case(c["case"], int(c["parameter"]), int(criterion["seeds"])) for c in criterion["held_out"]]
    found = judge(criterion, rows)
    for row in found["cases"]:
        print(f"{row['case']} n={row['n']}: {row['read']}/{row['seeds']} read, d_s {row['d_s_mean']}, spread "
              f"{row['spread']}, se {row['se_median']} (analytic {row['analytic_se_median']}), ratio {row['ratio']}, "
              f"{'passes' if row['passes'] else 'not judged' if not row['judged'] else 'fails'}")
    print(f"{found['judged']} judged: {'passes' if found['passes'] else 'fails'}")
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    return 0 if found["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
