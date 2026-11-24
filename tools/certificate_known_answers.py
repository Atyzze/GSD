from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.research import certificate_known_answers as K

CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "certificate_known_answers_criterion_3.json"


def _read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_run(args) -> int:
    criterion = _read(args.criterion)
    judged = K.judge_rungs(criterion, K.measure_rungs(criterion))
    render = K.render_rungs
    judged.update({"criterion": criterion["contract"], "analysis_version": ANALYSIS_VERSION,
                   "measured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if args.json:
        Path(args.json).write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render(judged), encoding="utf-8")
    print(render(judged))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the certificate's effective-sample count on its known answers")
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
