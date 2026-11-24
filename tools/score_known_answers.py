#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.observability import law_score as L  # noqa: E402
from graph_scale_dynamics.research import score_known_answers as K  # noqa: E402


def _dump(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def cmd_measure(args) -> int:
    from graph_scale_dynamics.research import probes_known_answers as P
    criterion = K.criterion_5()
    started = time.time()
    rows = P.measure(criterion, workers=args.workers, sets=("crossovers", "structures"))
    _dump(K.MEASURED_5, {"contract": "gsd-score-known-answers-measured-2", "criterion": criterion["contract"],
                           "seeds": criterion["seeds"], "seconds": round(time.time() - started, 1), "rows": rows})
    print(f"{len(rows)} graphs read in {time.time() - started:.0f} s: {K.MEASURED_5}")
    return 0


def cmd_read(args) -> int:
    margins, document = K.run()
    _margins_4, fourth = K.run_4()
    _margins_5, fifth = K.run_5()
    if args.write:
        _dump(L.MARGINS_FILE, margins)
        _dump(K.JUDGED, document)
        K.PAGE.write_text(K.render(document), encoding="utf-8")
        _dump(K.JUDGED_4, fourth)
        K.PAGE_4.write_text(K.render_4(fourth), encoding="utf-8")
        _dump(K.JUDGED_5, fifth)
        K.PAGE_5.write_text(K.render_5(fifth), encoding="utf-8")
    print(K.render(document))
    print(K.render_4(fourth))
    print(K.render_5(fifth))
    return 0 if document["passes"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="what settles means for the score, judged on known answers")
    parser.add_argument("--write", action="store_true", help="write the margins, the judged file and its page")
    sub = parser.add_subparsers(dest="command")
    measure = sub.add_parser("measure", help="build and read criterion 5's structures and crossovers on its seeds")
    measure.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    return cmd_measure(args) if args.command == "measure" else cmd_read(args)


if __name__ == "__main__":
    raise SystemExit(main())
