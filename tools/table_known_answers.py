#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research import table_known_answers as K  # noqa: E402

READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
CRITERION = READINGS / "table_known_answers_criterion.json"
TABLE_MEMBER = "probe_calibration.json"


def load_table(path: Path) -> dict:
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read(TABLE_MEMBER).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/table_known_answers.py: see docs/TOOLS.md")
    parser.add_argument("table", type=Path, help="the host's calibration zip, or a table's JSON")
    parser.add_argument("--criterion", type=Path, default=CRITERION)
    parser.add_argument("--against", type=Path, help="the seed the table replaces, for the same readings")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    criterion = json.loads(args.criterion.read_text(encoding="utf-8"))
    against = load_table(args.against) if args.against else None
    judged = K.judge(criterion, load_table(args.table), against)
    judged["judged_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.json:
        args.json.write_text(json.dumps(judged, indent=1) + "\n", encoding="utf-8")
    page = K.render(judged)
    if args.md:
        args.md.write_text(page, encoding="utf-8")
    print(page)
    return 0 if judged["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
