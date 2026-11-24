from __future__ import annotations

import hashlib
import json
import os
import secrets
import platform
import time
from pathlib import Path

from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration.cells import family_ladder, plan_cells
from graph_scale_dynamics.calibration.contract import CONTRACT, SUITE_VERSION
from graph_scale_dynamics.calibration.deviation import deviation_report

CELL_CURRENT = "current"
CELL_STALE = "stale"
CELL_MISSING = "missing"
CELL_FAILED = "failed"


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _build_number() -> int | None:
    try:
        from graph_scale_dynamics.domain.version import BUILD_NUMBER
        return int(BUILD_NUMBER)
    except Exception:
        return None


def suite_fingerprint(families: list[dict], *, seeds: int, root: str | None = None) -> str:
    parts = [f"suite_version={SUITE_VERSION}", f"seeds={int(seeds)}"]
    for family in families:
        parts.append(f"{family['name']}={FP.cell_fingerprint(family['name'], root)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def family_headers(families: list[dict], *, max_nodes: int | None = None,
                   root: str | None = None) -> dict:
    return {
        family["name"]: {
            "expectation": family["expectation"],
            "why": family.get("why", ""),
            "theory": dict(family.get("theory") or {}),
            "refusal_gated_from": dict(family.get("refusal_gated_from") or {}),
            "ladder": family_ladder(family, max_nodes),
            "graph_varies_per_seed": bool(family.get("graph_varies_per_seed")),
            "family_fingerprint": FP.family_fingerprint(family["name"], root),
            "cell_fingerprint": FP.cell_fingerprint(family["name"], root),
        }
        for family in families
    }


def new_table(families: list[dict], *, seeds: int, max_nodes: int | None,
              authoritative: bool, profile: str, root: str | None = None) -> dict:
    return {
        "contract": CONTRACT,
        "suite_version": SUITE_VERSION,
        "written_utc": _utc(),
        "analysis_version": FP.analysis_version(root),
        "science_fingerprint": FP.science_fingerprint(),
        "estimator_fingerprint": FP.estimator_fingerprint(root),
        "suite_fingerprint": suite_fingerprint(families, seeds=seeds, root=root),
        "build_number": _build_number(),
        "authoritative": bool(authoritative),
        "profile": {"name": profile, "seeds": int(seeds), "max_nodes": max_nodes},
        "families": family_headers(families, max_nodes=max_nodes, root=root),
        "cells": {},
        "plan": {},
        "deviation": {},
        "runs": [],
        "origin": {"computed_on": platform.node(), "adopted": False, "adopted_from": None,
                   "adopted_utc": None},
    }


def load(path: Path) -> dict | None:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def restamp_header(document: dict, families: list[dict], *, seeds: int,
                   max_nodes: int | None, root: str | None = None) -> dict:
    document.setdefault("created_under", {
        "suite_version": document.get("suite_version"),
        "build_number": document.get("build_number"),
        "science_fingerprint": document.get("science_fingerprint"),
        "written_utc": document.get("written_utc"),
    })
    document["suite_version"] = SUITE_VERSION
    document["build_number"] = _build_number()
    document["suite_fingerprint"] = suite_fingerprint(families, seeds=seeds, root=root)
    document["analysis_version"] = FP.analysis_version(root)
    document["estimator_fingerprint"] = FP.estimator_fingerprint(root)
    document["science_fingerprint"] = FP.science_fingerprint()
    document["families"] = family_headers(families, max_nodes=max_nodes, root=root)
    return document


def write(document: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document["written_utc"] = _utc()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(json.dumps(document, indent=1, sort_keys=True, allow_nan=False, default=float),
                       encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def cell_is_current(cell: dict, root: str | None = None) -> bool:
    stored = cell.get("cell_fingerprint") if isinstance(cell, dict) else None
    if not stored:
        return False
    try:
        return str(stored) == FP.cell_fingerprint(str(cell.get("family")), root)
    except (OSError, ValueError, KeyError, SyntaxError):
        return False


def its_probes_are_current(cell: dict | None, root: str | None = None) -> bool:
    return isinstance(cell, dict) and cell.get("status") == "ok" and cell_is_current(cell, root)


def classify_cells(document: dict, plan: list[dict], root: str | None = None) -> dict:
    from graph_scale_dynamics.calibration import start_reading
    cells = document.get("cells") if isinstance(document.get("cells"), dict) else {}
    out = {CELL_CURRENT: [], CELL_STALE: [], CELL_MISSING: [], CELL_FAILED: []}
    for task in plan:
        cell = cells.get(task["key"])
        if not isinstance(cell, dict):
            out[CELL_MISSING].append(task["key"])
            continue
        expected = FP.cell_fingerprint(task["family"], root)
        if cell.get("status") != "ok":
            out[CELL_FAILED].append(task["key"])
        elif str(cell.get("cell_fingerprint")) != expected or not start_reading.current_where_wanted(cell):
            out[CELL_STALE].append(task["key"])
        else:
            out[CELL_CURRENT].append(task["key"])
    return out


def refresh(document: dict, families: list[dict], *, seeds: int, max_nodes: int | None,
            waivers: list[dict] | None = None, root: str | None = None) -> dict:
    plan = plan_cells(families, seeds=seeds, max_nodes=max_nodes)
    classes = classify_cells(document, plan, root)
    document["families"] = family_headers(families, max_nodes=max_nodes, root=root)
    document["science_fingerprint"] = FP.science_fingerprint()
    document["analysis_version"] = FP.analysis_version(root)
    document["estimator_fingerprint"] = FP.estimator_fingerprint(root)
    document["suite_fingerprint"] = suite_fingerprint(families, seeds=seeds, root=root)
    document["plan"] = {
        "total_cells": len(plan),
        "current": len(classes[CELL_CURRENT]),
        "stale": len(classes[CELL_STALE]),
        "missing": len(classes[CELL_MISSING]),
        "failed": len(classes[CELL_FAILED]),
        "complete": not (classes[CELL_STALE] or classes[CELL_MISSING] or classes[CELL_FAILED]),
    }
    usable = {k: v for k, v in (document.get("cells") or {}).items() if k in set(classes[CELL_CURRENT])}
    if max_nodes is None:
        from graph_scale_dynamics.calibration.cells import extension_ladder
        rungs = {f"{f['name']}:{r['parameter']}": f["name"] for f in families for r in extension_ladder(f)}
        for key, cell in (document.get("cells") or {}).items():
            family = rungs.get(key.rsplit(":", 1)[0])
            if (family and isinstance(cell, dict) and cell.get("status") == "ok"
                    and str(cell.get("cell_fingerprint")) == FP.cell_fingerprint(family, root)):
                usable[key] = cell
    document["deviation"] = deviation_report(families, usable, seeds=seeds, max_nodes=max_nodes,
                                             waivers=waivers)
    return classes


def checkpoint(document: dict, cell: dict, path: Path, families: list[dict], *, seeds: int,
               max_nodes: int | None, waivers: list[dict] | None = None,
               root: str | None = None) -> None:
    from graph_scale_dynamics.calibration.cells import cell_key
    document.setdefault("cells", {})[cell_key(cell["family"], cell["parameter"], cell["seed"])] = cell
    refresh(document, families, seeds=seeds, max_nodes=max_nodes, waivers=waivers, root=root)
    write(document, path)


def verify(document: dict | None, families: list[dict], *, seeds: int, max_nodes: int | None,
           waivers: list[dict] | None = None, root: str | None = None) -> dict:
    report = {"usable": False, "complete": False, "notices": [], "cells": {},
              "science_fingerprint_matches": None, "suite_fingerprint_matches": None,
              "authoritative": None, "verdict": None}
    if not isinstance(document, dict):
        report["notices"].append("no calibration table")
        return report
    if document.get("contract") != CONTRACT:
        report["notices"].append(f"contract {document.get('contract')!r} is not {CONTRACT!r}")
        return report
    if int(document.get("suite_version") or -1) != SUITE_VERSION:
        report["notices"].append(
            f"suite version {document.get('suite_version')} is not {SUITE_VERSION}: a table of another suite holds "
            "cells of another shape and is not resumed from; this suite's table is measured as a new one")
        return report
    report["usable"] = True
    report["authoritative"] = bool(document.get("authoritative"))
    current_science = FP.science_fingerprint()
    recorded_science = str(document.get("science_fingerprint") or "")
    report["science_fingerprint_matches"] = (recorded_science == current_science)
    if not report["science_fingerprint_matches"]:
        report["notices"].append(
            f"table was written under science fingerprint {recorded_science or 'unknown'}, "
            f"runtime is {current_science}; cells are judged by their own fingerprints, "
            "not by this digest")
    expected_suite = suite_fingerprint(families, seeds=seeds, root=root)
    report["suite_fingerprint_matches"] = (str(document.get("suite_fingerprint")) == expected_suite)
    classes = refresh(document, families, seeds=seeds, max_nodes=max_nodes, waivers=waivers, root=root)
    report["cells"] = {k: len(v) for k, v in classes.items()}
    report["cells"]["total"] = sum(len(v) for v in classes.values())
    report["complete"] = bool(document["plan"]["complete"])
    report["verdict"] = document["deviation"].get("verdict")
    if classes[CELL_STALE]:
        by_family: dict[str, int] = {}
        for key in classes[CELL_STALE]:
            by_family[key.split(":", 1)[0]] = by_family.get(key.split(":", 1)[0], 0) + 1
        report["notices"].append(
            "stale cells (their sources changed): " +
            ", ".join(f"{k} x{v}" for k, v in sorted(by_family.items())))
    if classes[CELL_MISSING]:
        report["notices"].append(f"{len(classes[CELL_MISSING])} cell(s) missing")
    if classes[CELL_FAILED]:
        report["notices"].append(f"{len(classes[CELL_FAILED])} cell(s) recorded as failed")
    if (not report["science_fingerprint_matches"] and not classes[CELL_STALE]
            and not classes[CELL_MISSING] and not classes[CELL_FAILED]):
        report["notices"].append(
            "science fingerprint moved but no cell's own inputs did: re-stamped, not re-run")
    return report


def mark_adopted(document: dict, *, source: str, notices: list[str]) -> None:
    document["origin"] = {
        **(document.get("origin") or {}),
        "adopted": True,
        "adopted_from": source,
        "adopted_utc": _utc(),
        "adopted_on": platform.node(),
        "adoption_notices": list(notices),
    }


def record_run(document: dict, run: dict) -> None:
    runs = document.setdefault("runs", [])
    runs.append(run)
    del runs[:-50]


def history_copy(document: dict, history: Path, label: str) -> Path | None:
    try:
        history.mkdir(parents=True, exist_ok=True)
        stamp = _utc().replace(":", "").replace("-", "")
        target = history / f"{label}_{stamp}.json"
        target.write_text(json.dumps(document, indent=1, sort_keys=True, default=float),
                          encoding="utf-8")
        return target
    except OSError:
        return None


def history_recovery_candidates(history: Path, plan: list[dict],
                                durable_current: int,
                                root: str | None = None) -> list[dict]:
    candidates: list[dict] = []
    try:
        files = sorted(Path(history).glob("*.json"))
    except OSError:
        return candidates
    wanted = {task["key"]: task["family"] for task in plan}
    for path in files:
        document = load(path)
        if not document:
            continue
        cells = document.get("cells") or {}
        usable = 0
        for key, family in wanted.items():
            cell = cells.get(key)
            if (cell and str(cell.get("status") or "ok") == "ok"
                    and str(cell.get("cell_fingerprint")) == FP.cell_fingerprint(family, root)):
                usable += 1
        if usable > durable_current:
            candidates.append({"path": str(path), "usable_cells": usable,
                               "written_utc": document.get("written_utc"),
                               "gain": usable - durable_current})
    candidates.sort(key=lambda c: -c["usable_cells"])
    return candidates


def durable_table_is_git_tracked(root: Path | None = None) -> bool:
    import subprocess

    from graph_scale_dynamics.calibration import contract as C

    base = Path(root) if root else C.repository_root()
    relative = f"{C.DURABLE_DIR}/{C.DURABLE_NAME}"
    try:
        done = subprocess.run(["git", "ls-files", "--error-unmatch", relative],
                              cwd=base, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
