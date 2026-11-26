#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "gsd-engine-diet-1"
DESIGN = "graph_scale_dynamics/resources/readings/study_176_design.json"
LAWS = {
    "anchor": "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json",
    "overlaps": {"dsl_version": 1, "init": "empty",
                 "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "log_N"}},
                           {"op": "square_edge_overlap", "params": {}, "coeff": {"c0": 0.02, "scale": "one"}},
                           {"op": "triangle_edge_overlap", "params": {}, "coeff": {"c0": 0.02, "scale": "one"}},
                           {"op": "degree_anchor", "params": {"k": 6}, "coeff": {"c0": 0.5, "scale": "one"}}],
                 "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": 0.5, "delete": 0.5},
                              "sweeps": 4}},
    "curvature": {"dsl_version": 1, "init": "empty",
                  "terms": [{"op": "degree_anchor", "params": {"k": 6}, "coeff": {"c0": 0.5, "scale": "one"}},
                            {"op": "ollivier_curvature", "params": {}, "coeff": {"c0": -0.05, "scale": "one"}},
                            {"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "log_N"}}],
                  "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": 0.5, "delete": 0.5},
                               "sweeps": 2}},
}


def law_of(name: str) -> dict:
    found = LAWS[name]
    return json.loads((ROOT / found).read_text(encoding="utf-8")) if isinstance(found, str) else dict(found)


def policy_of(law: dict, n: int) -> dict:
    from graph_scale_dynamics.dsl.dsl import fingerprint
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    raw = (ROOT / DESIGN).read_bytes()
    made = dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=DESIGN)
    made.pop("starts_reading", None)
    spec = SD.campaign_spec(made, control.shipped_spec(), made["campaigns"][0], 0)
    return dict(one_shot_policy(spec, n, fingerprint(law), law), max_sweeps_multiplier=1,
                required_consecutive_passes=1)


def digest(envelope: dict) -> str:
    chains = (envelope.get("sampling_checkpoint") or {}).get("chains") or []
    kept = [{"start": c.get("start"), "edges": [list(e) for e in c.get("edge_list") or []],
             "energy": c.get("energy"), "trajectory": c.get("trajectory"), "accounting": c.get("accounting"),
             "final": c.get("final"), "late_change": c.get("late_change")} for c in chains]
    return hashlib.sha256(json.dumps(kept, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def one(name: str, n: int, seed: int) -> dict:
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    from graph_scale_dynamics.services.worker.engine_registry import rust_source_version, simulate_of
    law = law_of(name)
    policy = policy_of(law, n)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    wall, cpu = time.monotonic(), time.process_time()
    envelope = run_one_shot(law, n, seed, one_shot=policy, record_points=40, simulate=simulate_of("rust"))
    wall, cpu = time.monotonic() - wall, time.process_time() - cpu
    chains = (envelope.get("sampling_checkpoint") or {}).get("chains") or []
    edges = sum(len(c.get("edge_list") or []) for c in chains)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    moves = sum(sum((c.get("attempted") or {}).values()) for c in chains)
    import gsd_engine_rs
    return {"law": name, "n": n, "seed": seed, "engine": rust_source_version(),
            "engine_installed": str(gsd_engine_rs.FINGERPRINT), "chains": len(chains),
            "edges_at_the_end": edges, "peak_bytes": peak, "peak_before_bytes": before * 1024,
            "bytes_an_edge": round((peak - before * 1024) / max(1, edges), 1), "wall_seconds": round(wall, 2),
            "cpu_seconds": round(cpu, 2), "moves": moves,
            "moves_per_cpu_second": round(moves / cpu) if cpu else None, "sha256": digest(envelope)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="one seed's peak memory, its time and its chains' digest, each "
                                                 "in a process of its own")
    parser.add_argument("--law", choices=sorted(LAWS), action="append")
    parser.add_argument("--n", type=int, action="append")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.one:
        print(json.dumps(one(args.law[0], args.n[0], args.seed)))
        return 0
    rows = []
    for name in args.law or ["anchor"]:
        for n in args.n or [16384]:
            done = subprocess.run([sys.executable, __file__, "--one", "--law", name, "--n", str(n), "--seed",
                                   str(args.seed)], capture_output=True, text=True, check=True)
            rows.append(json.loads(done.stdout.strip().splitlines()[-1]))
            print(json.dumps(rows[-1]), flush=True)
    if args.json:
        args.json.write_text(json.dumps({"contract": CONTRACT, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
