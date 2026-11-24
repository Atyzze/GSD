from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.calibration import ledger as L
from graph_scale_dynamics.calibration import ledger_runs as R
from graph_scale_dynamics.calibration import table as T


def _families(text: str | None):
    return [name.strip() for name in text.split(",") if name.strip()] if text else None


def _from_table(args) -> int:
    document = T.load(Path(args.table))
    if document is None:
        print(f"no readable calibration table at {args.table}", file=sys.stderr)
        return 2
    print(json.dumps(R.adopt_table(ROOT, document), indent=1))
    return 0


def _status(args) -> int:
    tasks = R.plan(args.max_nodes, _families(args.families), args.seeds)
    for row in R.status(ROOT, tasks):
        older = f"; older fingerprints {', '.join(row['older_fingerprints'])}" if row["older_fingerprints"] else ""
        print(f"{row['group']:14s} {row['fingerprint']}  {row['held']:5d} of {row['planned']} cells held, "
              f"{row['missing']} missing  [{', '.join(row['channels'])}]{older}")
    return 0


def _measure(args) -> int:
    tasks = R.plan(args.max_nodes, _families(args.families), args.seeds)

    def progress(records):
        for record in records:
            shown = {name: (round(c["value"], 4) if c.get("valid") else c.get("refusal"))
                     for name, c in record["channels"].items()}
            print(f"{record['cell']:48s} n={record['n']:8d} {shown} [{record['elapsed_seconds']}s]", flush=True)

    result = R.measure_missing(ROOT, args.group, tasks, workers=args.workers, limit=args.limit, progress=progress)
    print(json.dumps(result, indent=1))
    return 0


def _attest(args) -> int:
    result = R.attest(ROOT, args.group, sample=args.sample, seed=args.seed, tolerance=args.tolerance)
    print(json.dumps(result, indent=1))
    return 0 if result["agree"] == result["attested"] else 1


def _verify(_args) -> int:
    found = [problem for path in L.ledger_files(ROOT) for problem in L.problems(path)]
    for problem in found:
        print(problem)
    print(f"{len(L.ledger_files(ROOT))} ledger files, {len(found)} problems")
    return 1 if found else 0


def _snapshot(args) -> int:
    print(json.dumps(R.view_snapshot(ROOT), indent=1))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tools/ledger.py: see docs/TOOLS.md")
    commands = parser.add_subparsers(dest="command", required=True)
    from_table = commands.add_parser("from-table", help="file a table's cells in the ledger, measuring nothing")
    from_table.add_argument("--table", default=str(ROOT / "calibration" / "seed_table.json"),
                            help="the table (default calibration/seed_table.json)")
    for name, helptext in (("status", "cells held and missing per probe group"),
                           ("measure", "measure an appended group's missing cells")):
        command = commands.add_parser(name, help=helptext)
        command.add_argument("--max-nodes", type=int, default=65536, help="largest rung planned (default 65,536)")
        command.add_argument("--families", default=None, help="comma-separated families (default all)")
        command.add_argument("--seeds", type=int, default=R.AUTHORITATIVE_SEEDS,
                             help="seeds a rung (default the authoritative count)")
        if name == "measure":
            command.add_argument("--group", required=True, help="the appended probe group")
            command.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                                 help="processes (default half the cores)")
            command.add_argument("--limit", type=int, default=None, help="measure at most this many cells")
    attest = commands.add_parser("attest", help="re-measure held cells and file the agreement")
    attest.add_argument("--group", required=True, help="the appended probe group")
    attest.add_argument("--sample", type=int, default=8, help="cells re-measured (default 8)")
    attest.add_argument("--seed", type=int, default=0, help="the draw of cells (default 0)")
    attest.add_argument("--tolerance", type=float, default=R.DEFAULT_TOLERANCE,
                        help="relative deviation that still agrees (default 1e-9)")
    commands.add_parser("verify", help="check every ledger file's hashes and chain")
    commands.add_parser("snapshot", help="the roots of the current view")
    args = parser.parse_args(argv)
    handlers = {"from-table": _from_table, "status": _status, "measure": _measure, "attest": _attest,
                "verify": _verify, "snapshot": _snapshot}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
