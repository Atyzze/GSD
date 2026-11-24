from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.engine import engine as python_engine
from graph_scale_dynamics.research import boltzmann_known_answers as K
from graph_scale_dynamics.services.worker.engine_registry import ENGINE_PYTHON, ENGINE_RUST, resolve_engine

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "boltzmann_known_answers_criterion_4.json"


def rust_energy(spec: dict, n: int, edges) -> float:
    from graph_scale_dynamics.services.worker import engine_rs
    ctx = python_engine.ChainContext(n=n, candidate_spec=spec, spec_ops={term["op"] for term in spec["terms"]})
    _state, energy = engine_rs.init_declared(ctx, [(int(a), int(b)) for a, b in edges], None,
                                             python_engine._energy_model(spec, n)[1])
    return float(energy)


def engines_of(names) -> dict:
    energy = {ENGINE_PYTHON: python_engine.configuration_energy, ENGINE_RUST: rust_energy}
    return {name: {"run": resolve_engine({"engine": name})[1], "energy": energy[name]} for name in names}


def _cell(job) -> dict:
    criterion, law_index, law, n, name = job
    return K.measure_cell(criterion, law_index, law, n, name, engines_of([name])[name])


def measure(criterion: dict, workers: int) -> tuple[list[dict], dict]:
    laws = K.draw_laws(criterion)
    names = sorted(criterion["engines"])
    jobs = [(criterion, index, law, n, name) for name in names for index, law in enumerate(laws)
            for n in criterion["sizes"]]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_cell, jobs, chunksize=1))
    else:
        rows = [_cell(job) for job in jobs]
    return rows, K.energies_agree(criterion, laws, engines_of(names))


def cmd_run(args) -> int:
    from graph_scale_dynamics.resources import committed
    criterion = committed.read(args.criterion)
    rows, energies = measure(criterion, args.workers)
    judged = K.judge(criterion, rows, energies)
    judged.update({"criterion": criterion["contract"],
                   "engine_fingerprints": {name: resolve_engine({"engine": name})[2]
                                           for name in sorted(criterion["engines"])},
                   "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(K.render(judged), encoding="utf-8")
    print(K.render(judged))
    return 0 if judged["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the engines' chains against exact Boltzmann measures")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--criterion", default=str(CRITERION))
    run.add_argument("--json")
    run.add_argument("--md")
    run.add_argument("--workers", type=int, default=1)
    run.set_defaults(run=cmd_run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
