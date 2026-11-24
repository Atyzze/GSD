from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import adopt as ADOPT
from graph_scale_dynamics.calibration import table as T
from graph_scale_dynamics.calibration.contract import DURABLE_DIR, DURABLE_NAME

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/adopt_calibration.py: see docs/TOOLS.md")
    parser.add_argument("--table", default=str(ROOT / DURABLE_DIR / DURABLE_NAME),
                        help="the table (default this folder's durable table)")
    parser.add_argument("--sample", type=int, default=2,
                        help="cheapest cells re-measured per family, besides its largest to 4,096 (default 2)")
    parser.add_argument("--tolerance", type=float, default=1e-9,
                        help="relative difference treated as reproduction (default 1e-9)")
    parser.add_argument("--repeat", type=int, default=2,
                        help="measurements per sampled cell; 2 establishes this host's "
                             "run-to-run noise floor (default 2, 1 disables the floor)")
    parser.add_argument("--apply", action="store_true",
                        help="write the re-stamped table (default is a dry run)")
    parser.add_argument("--why", default="",
                        help="the edit being adopted across, recorded on the table")
    args = parser.parse_args(argv)

    path = Path(args.table)
    document = T.load(path)
    if document is None:
        print(f"no readable calibration table at {path}", file=sys.stderr)
        return 2
    report = ADOPT.verify_and_adopt(document, sample=max(1, args.sample), tolerance=args.tolerance,
                                    repeat=max(1, args.repeat),
                                    reason=f"tools/adopt_calibration.py: {args.why.strip() or 'no reason given'}")
    print(f"stale cells: {report['stale_cells']}; sampled: {report['sampled']}; worst deviation "
          f"{report['worst_deviation']:.2e}, host spread {report['worst_host_spread']:.2e}")
    for line in report["notices"]:
        print(line)
    if report["refused"]:
        for refusal in report["refused"]:
            print(f"  MOVED {refusal['cell']}: " + "; ".join(refusal["problems"]), file=sys.stderr)
        print("REFUSING: the edit was not value-neutral, so the table is genuinely stale and must be recalibrated.",
              file=sys.stderr)
        return 1
    if not report["adopted"]:
        return 0 if report["stale_cells"] == 0 else 2
    if not args.apply:
        print("dry run: pass --apply to re-stamp the table")
        return 0
    backup = path.with_suffix(path.suffix + ".before-adopt")
    shutil.copy2(path, backup)
    T.write(document, path)
    print(f"re-stamped {report['restamped']} cell(s), {report['kept_stale']} left stale; previous file kept at {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
