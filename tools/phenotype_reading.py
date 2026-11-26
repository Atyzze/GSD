#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import phenotype as P  # noqa: E402
from lexicon_reading import _rows, bundle_root, unpacked  # noqa: E402

FROM_ROW = {"mean_degree": "mean_degree", "giant_fraction": "connected_fraction", "d_s": "d_s", "d_V": "d_V",
            "d_B": "d_B", "d_w": "d_w", "reach": "half_volume_radius"}


def laws_of(root: Path) -> dict[tuple[str, str], dict]:
    series: dict[tuple[str, str], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in _rows(root, "rungs.ndjson.gz"):
        key = (str(row["campaign_id"]), str(row["candidate_id"]))
        weight = row.get("seeds") or 1
        for quantity, column in FROM_ROW.items():
            if row.get(column) is not None:
                series[key][quantity].append((int(row["n"]), float(row[column]), float(weight)))
    codes = {(str(law["campaign_id"]), str(law["candidate_id"])): law.get("code") for law in _rows(root, "laws.ndjson.gz")}
    return {key: {"code": codes.get(key), "phenotype": P.of_series({"every start": dict(found)})}
            for key, found in series.items()}


def seen_from_table(path: Path) -> dict[str, dict]:
    cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
    by: dict[str, dict[str, dict[int, list]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for cell in cells.values():
        n, family = int(cell["n"]), cell["family"]
        if cell.get("half_volume_radius") is not None:
            by[family]["reach"][n].append(float(cell["half_volume_radius"]))
        for probe in ("d_s", "d_V", "d_B", "d_w"):
            channel = (cell.get("channels") or {}).get(probe) or {}
            if channel.get("valid") and channel.get("value") is not None:
                by[family][probe][n].append(float(channel["value"]))
    return {family: P.of_series({"every start": {quantity: [(n, statistics.fmean(v), len(v)) for n, v in sorted(s.items())]
                                                 for quantity, s in quantities.items()}})
            for family, quantities in by.items()}


def reading(root: Path, table: Path) -> dict:
    seen = seen_from_table(table)
    laws, counts = [], Counter()
    for (campaign, law), found in sorted(laws_of(root).items()):
        names = P.categories(found["phenotype"])
        counts.update(names)
        like, share = P.nearest_seen(found["phenotype"], seen)
        laws.append({"campaign_id": campaign, "candidate_id": law, "code": found["code"], "categories": names,
                     "reads_like": like, "shared": share, "phenotype": found["phenotype"]})
    return {"contract": P.rule()["contract"], "laws": laws, "categories": dict(counts.most_common())}


def main(argv: list[str] | None = None) -> int:
    from graph_scale_dynamics.observability import lexicon as L
    parser = argparse.ArgumentParser(description="every law's phenotype in a bundle: each quantity over N by the "
                                                 "fewest forms, the categories they make, the geometry each reads like")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--table", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = bundle_root(unpacked(args.bundle))
    table = args.table or next((p for p in (root / "calibration" / "probe_calibration.json", L.table_path())
                                if p is not None and Path(p).is_file()), None)
    if table is None:
        raise SystemExit("no calibration table: give one with --table")
    found = reading(root, Path(table))
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    print(f"{len(found['laws'])} laws; categories: " + "; ".join(f"{k} {v}" for k, v in found["categories"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
