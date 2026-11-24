#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def command(lane: str, *, allow_skips: bool = False, since: str | None = None) -> list[str]:
    if lane == "full":
        argv = ["--lane", "all", "--require-postgres", "--shards", "auto"]
    elif lane == "fast":
        argv = ["--lane", "fast", "--require-postgres", *(["--changed-since", since] if since else [])]
    else:
        raise ValueError(f"no lane {lane!r}: fast or full")
    return [sys.executable, str(ROOT / "tools" / "test_suite.py"), *argv, *(["--allow-skips"] if allow_skips else [])]


def refusal(root: Path = ROOT) -> str | None:
    from graph_scale_dynamics.operations.folder_guard import live_in_folder
    found = live_in_folder(root)
    return (f"{found}: the lanes start PostgreSQL and fleets of their own; run them in a fresh folder of the archive"
            if found else None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/gate.py: see docs/TOOLS.md")
    parser.add_argument("lane", choices=("fast", "full"))
    parser.add_argument("--allow-skips", action="store_true",
                        help="report skipped tests the release would refuse (a host without node or Chromium)")
    parser.add_argument("--since", default=None,
                        help="the fast lane against this git revision instead of the build's record of its files")
    args = parser.parse_args(argv)
    why = refusal()
    if why:
        print(f"gate refused: {why}", flush=True)
        return 2
    return subprocess.run(command(args.lane, allow_skips=args.allow_skips, since=args.since), cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
