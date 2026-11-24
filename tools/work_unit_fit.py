#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

READING = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "work_unit_fit.json"
CONTRACT = "gsd-work-unit-fit-1"
DESIGN = "tests/fixtures/a_design.json"
SEARCH_SEED = 806_000_000_000_806
SIZES = (256, 1024, 4096)
SEEDS = (0, 1)
SAMPLE_BUDGET = 2 * 10 ** 11
TENTH_NS = 1e-10
PARTS = ("moves", "evaluations", "changes", "lists", "entries", "tests")
ROW_KEYS = ("law", "n", "seed", "cpu_seconds", "wall_seconds", "parts", "chains", "chunks", "reason",
            "final_multiplier")


def campaign_spec() -> dict:
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import study_design as SD
    raw = (ROOT / DESIGN).read_bytes()
    design = dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=DESIGN)
    spec = SD.without_terms(design, control.shipped_spec(), log=lambda *a, **k: None)
    return SD.campaign_spec(design, spec, design["campaigns"][0], 0)


def draw(spec: dict, count: int) -> list:
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
    from graph_scale_dynamics.services.proposer.blind import blind_batch, identity_version, law_stream
    grid = spec["search_policy"]["grid"]
    version = identity_version(grid)
    return blind_batch(random.Random(0), count, list(spec.get("operator_whitelist") or dsl.OPERATORS), grid, set(),
                       set(), fingerprint=dsl.fingerprint,
                       physical_identity=lambda law: equilibrium_identity(law, version=version)[0],
                       complexity_budget=spec.get("complexity_budget"),
                       streams=lambda index: law_stream(SEARCH_SEED, index), first_index=0)


def run_seed(spec: dict, law: dict, n: int, seed: int, *, budget: int = SAMPLE_BUDGET) -> dict:
    from graph_scale_dynamics.domain import chain_list as CL
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.scaleflow import engine_door
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot, seed_work_parts
    from graph_scale_dynamics.scheduling.job_creation import initial_sweeps_multiplier, one_shot_policy
    law_id = dsl.fingerprint(law)
    policy = dict(one_shot_policy(spec, n, law_id, law), work_budget=int(budget))
    cpu, wall = time.process_time(), time.monotonic()
    envelope = run_one_shot(law, n, seed, one_shot=policy, initial_multiplier=initial_sweeps_multiplier(spec, n),
                            simulate=engine_door.simulate_of("rust"))
    cpu, wall = time.process_time() - cpu, time.monotonic() - wall
    terminal = envelope.get("rung_terminal") or {}
    return {"law": law_id, "n": int(n), "seed": int(seed), "cpu_seconds": cpu, "wall_seconds": wall,
            "parts": seed_work_parts(CL.move_accounting(envelope)), "chains": len(CL.ran_names(envelope)),
            "chunks": len(envelope.get("sampling_checkpoints") or []), "reason": terminal.get("reason"),
            "final_multiplier": terminal.get("final_multiplier"), "work": terminal.get("work")}


def sample(out: Path, laws: int, part: int, parts: int) -> int:
    from graph_scale_dynamics.dsl import dsl
    spec = campaign_spec()
    done = set()
    if out.exists():
        done = {(row["law"], row["n"], row["seed"]) for row in map(json.loads, out.read_text().splitlines())}
    jobs = [(law, n, seed) for n in SIZES for law in draw(spec, laws) for seed in SEEDS]
    for index, (law, n, seed) in enumerate(jobs):
        if index % parts != part or (dsl.fingerprint(law), n, seed) in done:
            continue
        row = run_seed(spec, law, n, seed)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({key: row[key] for key in ROW_KEYS}) + "\n")
        print(index, row["law"][:12], n, seed, round(row["cpu_seconds"], 2), row["reason"], flush=True)
    return 0


def units_of(parts: dict, weights: dict) -> int:
    return sum(int(weights[name]) * int(parts[name]) for name in PARTS)


def _quantiles(values) -> dict:
    import numpy as np
    return {f"p{q}": float(np.percentile(values, q)) for q in (5, 50, 95)}


def fit(rows: list) -> dict:
    import numpy as np
    from scipy.optimize import nnls
    kept = [row for row in rows if row["parts"] and row["cpu_seconds"] > 0]
    terms = np.array([[row["parts"][name] for name in PARTS] + [row["n"] * row["chains"]] for row in kept],
                     dtype=float)
    seconds = np.array([row["cpu_seconds"] for row in kept])
    solved, _ = nnls(terms / seconds[:, None], np.ones(len(seconds)))
    weights = {name: int(round(float(value) / TENTH_NS))
               for name, value in zip(PARTS, solved[:len(PARTS)], strict=True)}
    a_unit = seconds / np.array([units_of(row["parts"], weights) for row in kept], dtype=float)
    sizes = {}
    for n in sorted({row["n"] for row in kept}):
        chosen = np.array([row["n"] == n for row in kept])
        over_fit = seconds[chosen] / (terms[chosen] @ solved)
        per_move = seconds[chosen] / terms[chosen, 0]
        sizes[str(n)] = {"seeds": int(chosen.sum()), "seconds_over_fit": _quantiles(over_fit),
                         "spread_95_over_5": float(np.percentile(over_fit, 95) / np.percentile(over_fit, 5)),
                         "per_move_spread_95_over_5": float(np.percentile(per_move, 95) / np.percentile(per_move, 5)),
                         "seconds_a_unit": _quantiles(a_unit[chosen])}
    return {"weights": weights, "seconds_a_unit": float(f"{np.median(a_unit):.2g}"),
            "fixed_seconds_a_node_chain": float(solved[-1]), "laws": len({row["law"] for row in kept}),
            "seeds": len(kept), "sizes": sizes}


def write(sample_paths: list) -> dict:
    rows = [json.loads(line) for path in sample_paths for line in Path(path).read_text().splitlines() if line]
    rows = sorted(({key: row[key] for key in ROW_KEYS} for row in rows), key=lambda r: (r["n"], r["law"], r["seed"]))
    raw = (ROOT / DESIGN).read_bytes()
    reading = {
        "contract": CONTRACT, "unit": "0.1 ns of the sandbox's process time", "written_utc":
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "how": {"design": DESIGN, "design_sha256": hashlib.sha256(raw).hexdigest(), "search_seed": SEARCH_SEED,
                "sizes": list(SIZES), "seeds": list(SEEDS), "engine": "rust", "budget_units": SAMPLE_BUDGET,
                "fit": "non-negative least squares on each seed's relative error, the six parts and a fixed term a "
                       "node and chain; the parts' weights rounded to whole units"},
        "fit": fit(rows), "rows": rows}
    READING.write_text(json.dumps(reading, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return reading


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="work_unit_fit.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("sample")
    run.add_argument("--out", required=True)
    run.add_argument("--laws", type=int, default=48)
    run.add_argument("--part", type=int, default=0)
    run.add_argument("--parts", type=int, default=1)
    made = sub.add_parser("write")
    made.add_argument("samples", nargs="+")
    sub.add_parser("show")
    args = parser.parse_args(argv)
    if args.command == "sample":
        return sample(Path(args.out), args.laws, args.part, args.parts)
    reading = write(args.samples) if args.command == "write" else json.loads(READING.read_text(encoding="utf-8"))
    print(json.dumps({key: reading["fit"][key] for key in ("weights", "seconds_a_unit", "laws", "seeds")}))
    for n, size in reading["fit"]["sizes"].items():
        print(f"{n:>6}: {size['seeds']} seeds, seconds over the fit p5 {size['seconds_over_fit']['p5']:.2f} "
              f"p50 {size['seconds_over_fit']['p50']:.2f} p95 {size['seconds_over_fit']['p95']:.2f} "
              f"({size['spread_95_over_5']:.2f}x; moves alone {size['per_move_spread_95_over_5']:.1f}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
