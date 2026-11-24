#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

LINKED = ("study.json", "anchors.json", "gates_ledger.json")


def _table(study: Path) -> dict | None:
    study = Path(study)
    if study.is_file():
        return json.loads(study.read_text(encoding="utf-8"))
    for found in sorted(study.glob("**/evidence/probe_calibration.json")):
        return json.loads(found.read_text(encoding="utf-8"))
    return None


def parts_of(study: Path, *, calibration: dict | None = None, tree: Path = ROOT) -> tuple[dict, list[dict]]:
    from graph_scale_dynamics.reporting import study_explorer as E
    index = json.loads((study / "study.json").read_text(encoding="utf-8"))
    parts = []
    for record in index.get("campaigns") or []:
        part = study / str(record.get("bundle") or "")
        if not part.is_dir():
            continue
        parts.append({"campaign": record, "root": part,
                      "part": E.read_part(part, record, tree, calibration=calibration)})
    return index, parts


def read(study: Path, *, calibration: dict | None = None, tree: Path = ROOT, parts: tuple | None = None) -> dict:
    from graph_scale_dynamics.reporting import study_explorer as E
    table = calibration if calibration is not None else _table(study)
    index, read_parts = parts or parts_of(study, calibration=table, tree=tree)
    sid = index.get("study_id") or study.name
    title = f"Study {sid}: the explorer, {index.get('built_utc') or study.name}"
    return E.document(read_parts, title=title, calibration=table,
                      study={"study_id": sid, "built_utc": index.get("built_utc"),
                             "build_number": index.get("build_number"), "bundle": study.name}, tree=tree)


def _document(study: Path, name: str) -> dict | None:
    try:
        return json.loads((study / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def front(study: Path, index: dict, parts: list[dict], *, links: dict, tree: Path = ROOT) -> tuple[str, dict]:
    from graph_scale_dynamics.reporting import study_front as F
    from graph_scale_dynamics.reporting.study_explorer import label_of
    from graph_scale_dynamics.research import advice as A
    anchors = _document(study, "anchors.json")
    advice = A.advise(parts, anchors=anchors)
    cost = F.cost_models([{"campaign_id": str(p["campaign"].get("campaign_id")), "label": label_of(p["campaign"]),
                           "root": p["root"]} for p in parts])
    campaigns = [dict(record, label=label_of(record)) for record in index.get("campaigns") or []]
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    page = F.render(study={"study_id": index.get("study_id") or study.name, "built_utc": index.get("built_utc"),
                           "build_number": index.get("build_number"), "page_build": BUILD_NUMBER,
                           "read_utc": index.get("read_utc")},
                    campaigns=campaigns, links=links, advice=advice, cost=cost, classify=F.classify_summary(parts),
                    missing=index.get("missing"))
    return page, advice


def gate_trees(study: Path, index: dict, parts: list[dict]) -> str:
    import ijson

    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    from graph_scale_dynamics.reporting import gate_trees_page as P
    from graph_scale_dynamics.reporting.study_explorer import _report, label_of
    read = {str(p["campaign"].get("campaign_id")): p["part"] for p in parts}
    columns = []
    for record in index.get("campaigns") or []:
        cid, part = str(record.get("campaign_id")), study / str(record.get("bundle") or "")
        report, tree = (_report(part, "28") if part.is_dir() else None), None
        if report is not None:
            with open(report, "rb") as handle:
                tree = next(ijson.items(handle, "body.gate_tree", use_float=True), None)
        laws, graphs = record.get("laws") or record.get("laws_held"), record.get("graphs")
        columns.append({"campaign_id": cid, "label": label_of(record), "tree": tree,
                        "subtitle": " · ".join(x for x in (f"{laws:,} laws" if laws else "", f"{graphs:,} graphs"
                                                           if graphs is not None else "", str(record.get("state") or ""))
                                               if x)})
    carried = [cid for cid in (str(c["campaign_id"]) for c in columns) if cid in read]
    sid = index.get("study_id") or study.name
    data = P.document(columns, title=f"Study {sid}: the gate trees, {index.get('built_utc') or study.name}",
                      study={"study_id": sid, "built_utc": index.get("built_utc"),
                             "build_number": index.get("build_number"), "page_build": BUILD_NUMBER},
                      explorer_index={cid: i for i, cid in enumerate(carried)},
                      fate_counts={cid: P.fates(read[cid]) for cid in carried})
    return P.render(data, links={"explorer": "explorer.html", "front": "index.html"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/study_explorer.py: see docs/TOOLS.md")
    parser.add_argument("bundle", help="a study bundle: its directory, or the .tar.zst")
    parser.add_argument("--out-dir", help="where the front page, the explorer, the gate trees and the advice go "
                                          "(default: into an unpacked bundle, or a folder beside the archive named "
                                          "for it)")
    parser.add_argument("--out", help="the explorer page's path, if elsewhere")
    parser.add_argument("--calibration", help="a probe_calibration.json, or a bundle that carries one")
    args = parser.parse_args(argv)
    from read_bundle import unpacked as _unpacked

    from graph_scale_dynamics.reporting import study_explorer as E
    from graph_scale_dynamics.reporting import study_front as F
    bundle = Path(args.bundle)
    with tempfile.TemporaryDirectory() as scratch:
        study = _unpacked(bundle, Path(scratch))
        if not (study / "study.json").is_file():
            print(f"no study.json in {bundle}", file=sys.stderr)
            return 2
        calibration = None
        if args.calibration:
            with tempfile.TemporaryDirectory() as other:
                source = Path(args.calibration)
                calibration = _table(source if source.is_file() or source.is_dir() and not source.name.endswith(".zst")
                                     else _unpacked(source, Path(other)))
        table = calibration if calibration is not None else _table(study)
        index, parts = parts_of(study, calibration=table)
        data = read(study, calibration=table, parts=(index, parts))
        if not data["rows"]["law"]:
            print(f"no law read a probe in {bundle}", file=sys.stderr)
            return 2
        inside = bundle.is_dir()
        out_dir = Path(args.out_dir) if args.out_dir else (bundle if inside else bundle.parent / bundle.name.split(".")[0])
        out_dir.mkdir(parents=True, exist_ok=True)
        if not inside or out_dir.resolve() != bundle.resolve():
            for name in LINKED:
                if (study / name).is_file():
                    shutil.copyfile(study / name, out_dir / name)
        links = F.links_inside({})
        links.update({key: None for key, name in (("study", "study.json"), ("anchors", "anchors.json"),
                                                  ("gates_ledger", "gates_ledger.json"))
                      if not (out_dir / name).is_file()})
        if inside and out_dir.resolve() == bundle.resolve():
            links["parts"] = {str(r.get("campaign_id")): f"{r['bundle']}/" for r in index.get("campaigns") or []
                              if (bundle / str(r.get("bundle") or "")).is_dir()}
        page, advice = front(study, index, parts, links=links)
        trees = gate_trees(study, index, parts)
    explorer = Path(args.out) if args.out else out_dir / "explorer.html"
    explorer.write_text(E.render(data), encoding="utf-8")
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "gate_trees.html").write_text(trees, encoding="utf-8")
    (out_dir / "advice.json").write_text(json.dumps(advice, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"{len(data['campaigns'])} campaign(s), {len(data['laws'].get('id') or []):,} laws, "
          f"{len(data['rows']['law']):,} readings, {len(data['families'])} families, {len(data['papers'])} paper cells; "
          f"{advice.get('laws_with_a_reason', 0):,} laws with a reason and {len(advice.get('leads') or [])} leads: "
          f"wrote {out_dir / 'index.html'}, {explorer} ({explorer.stat().st_size / 1e6:.1f} MB), "
          f"{out_dir / 'gate_trees.html'} and {out_dir / 'advice.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
