#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research import probes_baseline as B  # noqa: E402


def cmd_write(args) -> int:
    found = B.measure(top=args.top, workers=args.workers)
    Path(args.file).write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(len(found["graphs"]), "graphs read")
    return 0


def cmd_against(args) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    print(B.render(B.compare(before, after), most=args.most), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="every probe's reading on a wide set of small graphs, and what moved")
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("file")
    write.add_argument("--top", type=int, default=B.START_SIZES[-1])
    write.add_argument("--workers", type=int, default=1)
    write.set_defaults(run=cmd_write)
    against = sub.add_parser("against")
    against.add_argument("before")
    against.add_argument("after")
    against.add_argument("--most", type=int, default=8)
    against.set_defaults(run=cmd_against)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
