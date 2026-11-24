from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = ROOT / "calibration" / "recalibration_owed.json"
SEED = ROOT / "calibration" / "seed_table.json"
CONTRACT = "gsd-recalibration-owed-1"


def declaration() -> dict | None:
    try:
        document = json.loads(DECLARATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if document.get("contract") == CONTRACT else None


def stale_cells() -> list[str]:
    from graph_scale_dynamics.calibration import contract as C
    from graph_scale_dynamics.calibration.cells import plan_cells, suite_families
    from graph_scale_dynamics.calibration.table import CELL_STALE, classify_cells
    try:
        seed = json.loads(SEED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plan = plan_cells(suite_families(), seeds=C.AUTHORITATIVE_SEEDS)
    return classify_cells(seed, plan, str(ROOT))[CELL_STALE]


def recalibration_owed() -> dict | None:
    from graph_scale_dynamics.calibration.fingerprint import estimator_fingerprint
    document = declaration()
    if document is None or document.get("estimator_fingerprint") != estimator_fingerprint():
        return None
    return document if stale_cells() else None


def reason(document: dict) -> str:
    owed = document.get("owed") or {}
    return (f"recalibration owed since build {document.get('build')}: {owed.get('cells')} seed cells above "
            f"{owed.get('above_nodes')} nodes were measured under estimator {document.get('seed_estimator_fingerprint')}, "
            f"this tree is {document.get('estimator_fingerprint')} ({document.get('why')}); "
            f"`calibration/recalibration_owed.json`")
