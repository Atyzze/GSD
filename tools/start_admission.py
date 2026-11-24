#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.research import start_admission as A  # noqa: E402

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "start_admission_criterion_2.json"


def rust_energy(spec: dict, n: int, edges) -> float:
    from boltzmann_known_answers import rust_energy as energy
    return energy(spec, n, edges)


def cmd_run(args) -> int:
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    judged = A.judge(criterion, A.measure(criterion, rust_energy))
    judged.update({"criterion": criterion["contract"],
                   "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(A.render(judged), encoding="utf-8")
    print(A.render(judged))
    return 0 if judged["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="which lattices a law of the fourteen terms can tell from a random graph")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--criterion", default=str(CRITERION))
    run.add_argument("--json")
    run.add_argument("--md")
    run.set_defaults(run=cmd_run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
