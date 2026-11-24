from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DURABLE = ROOT / "calibration" / "probe_calibration.json"

SKIP_REASON = (
    "no durable calibration table on this host. It is host state, not source, and "
    "build 353 stopped shipping one. Compute it with "
    "`python tools/probe_calibration.py --write`, or restore a previous run from "
    "var/calibration/history/."
)


def table_available() -> bool:
    return DURABLE.is_file()


def require_table() -> dict:
    if not table_available():
        pytest.skip(SKIP_REASON)
    return json.loads(DURABLE.read_text(encoding="utf-8"))


def skip_module_without_table() -> None:
    if not table_available():
        pytest.skip(SKIP_REASON, allow_module_level=True)


def skip_if_recalibration_owed() -> None:
    from graph_scale_dynamics.calibration.owed import reason, recalibration_owed
    document = recalibration_owed()
    if document is not None:
        pytest.skip(reason(document))


def skip_if_references_owed() -> None:
    from graph_scale_dynamics.calibration.owed import reason, recalibration_owed
    from graph_scale_dynamics.observability import starts_reading
    document = recalibration_owed()
    if document is not None and not starts_reading.table_references():
        pytest.skip(reason(document) + "; the lattice starts' references are measured with it")
