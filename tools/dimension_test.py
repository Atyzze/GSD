from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from graph_scale_dynamics.measurements import estimators
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.research import dimension_test, planted_geometries
from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "dimension_test_criterion_4.json"
MEASURED_CONTRACT = "gsd-dimension-test-measured-1"

HELD_OUT_BUILDERS = {
    "rgg_2d_sparse": lambda n, s: planted_geometries.random_geometric(n, 2, 5.0, s),
    "rgg_3d_dense": lambda n, s: planted_geometries.random_geometric(n, 3, 14.0, s),
    "percolation_2d": planted_geometries.FAMILIES["percolation_2d"]["build"],
    "random_tree": planted_geometries.FAMILIES["random_tree"]["build"],
    "random_regular_3": lambda n, s: planted_geometries.random_regular(n, 3, s),
    "erdos_renyi_8": lambda n, s: planted_geometries.erdos_renyi(n, 8.0, s),
    "ring_with_chords_dense": lambda n, s: planted_geometries.ring_with_chords(n, 0.1, s),
    "subdivided_regular_long": lambda n, s: planted_geometries.subdivided_regular(n, 6, s),
    "preferential_attachment_3": lambda n, s: planted_geometries.preferential_attachment(n, 3, s),
}


def _builder(family: str):
    if family in planted_geometries.FAMILIES:
        return planted_geometries.FAMILIES[family]["build"]
    return HELD_OUT_BUILDERS[family]


def measure_one(task: tuple[str, int, int]) -> dict:
    family, size, seed = task
    return measure_built(family, size, seed, _builder(family))


def measure_built(family: str, size: int, seed: int, builder) -> dict:
    started = time.perf_counter()
    built = builder(size, seed)
    if built is None:
        return {"family": family, "requested_n": size, "seed": seed, "built": False}
    n, edges = built
    result, _ = estimators._measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)
    row = {"family": family, "requested_n": size, "seed": seed, "built": True, "n": n,
           "mean_degree": round(2.0 * len(edges) / n, 4), "giant_fraction": round(result["component"] / n, 4),
           "reach": result.get("half_volume_radius"), "small_world": result.get("small_world"), "refusals": {}}
    for probe, key in PROBE_VALUE.items():
        block = result.get(probe) or {}
        row[probe] = float(block[key]) if block.get("valid") and block.get(key) is not None else None
        if row[probe] is None:
            row["refusals"][probe] = block.get("refusal")
    row["seconds"] = round(time.perf_counter() - started, 2)
    return row


def tasks_for(criterion: dict, part: str, sizes: list[int] | None = None) -> list[tuple[str, int, int]]:
    block = criterion[part]
    return [(case["family"], n, seed) for case in block["cases"] for n in (sizes or block["sizes"])
            for seed in block["seeds"]]


def cmd_measure(args) -> int:
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    tasks = tasks_for(criterion, args.part, args.sizes)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(measure_one, tasks):
            rows.append(row)
            print(" ".join(f"{k}={row.get(k)}" for k in ("family", "n", "seed", "d_s", "d_V", "d_B", "d_w", "reach",
                                                          "seconds")), flush=True)
    out = {"contract": MEASURED_CONTRACT, "part": args.part, "criterion": str(Path(args.criterion).relative_to(ROOT))
           if Path(args.criterion).resolve().is_relative_to(ROOT) else str(args.criterion),
           "analysis_version": ANALYSIS_VERSION,
           "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def cmd_judge(args) -> int:
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    measured = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.measured]
    judged = dimension_test.judge_against(criterion, measured)
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(dimension_test.render(judged), encoding="utf-8")
    print(dimension_test.render(judged))
    return 0 if judged["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the dimension test on its known answers")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--criterion", default=str(CRITERION))
    m.add_argument("--part", choices=("training", "held_out"), required=True)
    m.add_argument("--sizes", type=int, nargs="*")
    m.add_argument("--workers", type=int, default=2)
    m.add_argument("--out", required=True)
    m.set_defaults(run=cmd_measure)
    j = sub.add_parser("judge")
    j.add_argument("--criterion", default=str(CRITERION))
    j.add_argument("--measured", nargs="+", required=True)
    j.add_argument("--json")
    j.add_argument("--md")
    j.set_defaults(run=cmd_judge)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
