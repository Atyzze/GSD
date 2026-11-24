from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research import curvature_known_answers as K

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "curvature_known_answers_criterion_2.json"


def cmd_run(args) -> int:
    criterion = json.loads(Path(args.criterion).read_text(encoding="utf-8"))
    judged = K.judge(criterion, K.measure(criterion))
    judged.update({"criterion": criterion["contract"],
                   "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(K.render(judged), encoding="utf-8")
    print(K.render(judged))
    return 0 if judged["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the curvature probe against Ollivier's curvature")
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
