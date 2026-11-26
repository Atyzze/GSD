#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from graph_scale_dynamics.observability import lexicon as L  # noqa: E402


def unpacked(path: Path) -> Path:
    if path.is_file():
        from read_bundle import scratch_dir
        from read_bundle import unpacked as unpack
        return unpack(path, scratch_dir("gsd-lexicon-"))
    return path


def bundle_root(path: Path) -> Path:
    if (path / "study.json").is_file():
        return path
    found = sorted(p.parent for p in path.glob("*/study.json"))
    if len(found) != 1:
        raise SystemExit(f"{path} holds {len(found)} study bundles: name one")
    return found[0]


def _rows(root: Path, name: str):
    path = root / "tables" / name
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def laws_of(root: Path) -> list[dict]:
    top: dict[tuple[str, str], dict] = {}
    for row in _rows(root, "rungs.ndjson.gz"):
        key = (str(row["campaign_id"]), str(row["candidate_id"]))
        if key not in top or int(row["n"]) > int(top[key]["n"]):
            top[key] = row
    out = []
    for law in _rows(root, "laws.ndjson.gz"):
        key = (str(law["campaign_id"]), str(law["candidate_id"]))
        rung = top.get(key)
        out.append({"campaign_id": key[0], "candidate_id": key[1], "code": law.get("code"),
                    "law_score": (law.get("law_score") or {}).get("score") if isinstance(law.get("law_score"), dict)
                    else law.get("law_score"),
                    "n": int(rung["n"]) if rung else None, "features": L.features_of_rung_row(rung) if rung else {}})
    return out


def table_of(root: Path, given: Path | None) -> dict:
    for path in ([given] if given else []) + [root / "calibration" / "probe_calibration.json", L.table_path()]:
        if path is not None and Path(path).is_file():
            return L.table_profiles(Path(path))
    raise SystemExit("no calibration table: give one with --table")


def render(found: dict, top: int) -> str:
    lines = [f"# Every law against every known type ({found['contract']})", "",
             "Each law at its deepest size, its nearest type and how many of that type's own spreads away; a law "
             f"further than {L.lexicon()['new_zone_beyond']} from every type is near none: a new zone.", "",
             "| type | laws |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in found["by_type"].items()]
    scored = sorted((law for law in found["laws"] if law.get("law_score")), key=lambda law: -(law["law_score"] or 0))
    lines += ["", f"## The {min(top, len(scored))} best-scoring laws", "", "| law | score | N | type | spreads | next |",
              "|---|---|---|---|---|---|"]
    for law in scored[:top]:
        near = sorted(law["near"].items(), key=lambda item: item[1])
        second = f"{near[1][0]} ({near[1][1]})" if len(near) > 1 else ""
        lines.append(f"| {law.get('code') or law['candidate_id']} | {law['law_score']} | {law['n']} | "
                     f"{law['type'] or ('a new zone' if law['new_zone'] else 'unread')} | {law['spreads']} | {second} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="every law of a bundle against every known type: the lexicon's "
                                                 "matrix, each law at its deepest size")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--table", type=Path, help="the calibration table (default: the bundle's, then this tree's)")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    parser.add_argument("--top", type=int, default=100)
    args = parser.parse_args(argv)
    root = bundle_root(unpacked(args.bundle))
    found = L.matrix(laws_of(root), table_of(root, args.table))
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    text = render(found, args.top)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
