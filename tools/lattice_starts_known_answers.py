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

from graph_scale_dynamics.research import lattice_starts_known_answers as L  # noqa: E402



def cmd_run(args) -> int:
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    judged = L.judge(criterion, L.measure(criterion, workers=args.workers))
    judged.update({"criterion": criterion["contract"],
                   "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(L.render(judged), encoding="utf-8")
    print(L.render(judged))
    return 0 if judged["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the six lattice starts read by every probe at the ladder's sizes")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--criterion", required=True)
    run.add_argument("--json")
    run.add_argument("--md")
    run.add_argument("--workers", type=int, default=1)
    run.set_defaults(run=cmd_run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
