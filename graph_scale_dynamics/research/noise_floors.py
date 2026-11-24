from __future__ import annotations

import statistics

import json
from functools import lru_cache
from pathlib import Path

from graph_scale_dynamics.research.numeric import finite as _finite
from graph_scale_dynamics.scaleflow.probes import PROBES

FROZEN = (Path(__file__).resolve().parents[1] / "resources" / "readings" / "noise_floors_analysis-4.0.0.json")


@lru_cache(maxsize=1)
def _frozen() -> dict | None:
    return json.loads(FROZEN.read_text(encoding="utf-8")) if FROZEN.is_file() else None


def frozen_for(calibration_table: dict | None) -> dict | None:
    frozen = _frozen()
    named = (calibration_table or {}).get("estimator_fingerprint")
    if frozen is None or not named or named == frozen["estimator_fingerprint"]:
        return None
    return frozen

FLOOR_N_WINDOW = 2.0


def noise_floors(calibration_table: dict | None) -> dict[str, float | None]:
    from graph_scale_dynamics.calibration import gate_cells
    frozen = frozen_for(calibration_table)
    if frozen is not None:
        return {probe: frozen["floors"].get(probe) for probe in PROBES}
    floors: dict[str, float | None] = {probe: None for probe in PROBES}
    cells = gate_cells(calibration_table)
    for probe in PROBES:
        ses = []
        for cell in cells.values():
            channel = ((cell or {}).get("channels") or {}).get(probe) or {}
            if channel.get("valid") and _finite(channel.get("se")) is not None:
                ses.append(float(channel["se"]))
        floors[probe] = float(statistics.median(ses)) if ses else None
    return floors


def noise_floors_by_n(calibration_table: dict | None) -> dict[str, dict[int, float]]:
    from graph_scale_dynamics.calibration import extension_cells, gate_cells
    frozen = frozen_for(calibration_table)
    if frozen is not None:
        return {probe: {int(n): float(v) for n, v in (frozen["floors_by_n"].get(probe) or {}).items()}
                for probe in PROBES}
    gate = _ses_by_n(gate_cells(calibration_table))
    past = _ses_by_n(extension_cells(calibration_table))
    out: dict[str, dict[int, float]] = {}
    for probe in PROBES:
        rows = dict(gate[probe])
        for n, ses in past[probe].items():
            if not any(n / FLOOR_N_WINDOW <= k <= n * FLOOR_N_WINDOW for k in gate[probe]):
                rows[n] = ses
        out[probe] = {n: float(statistics.median(v)) for n, v in sorted(rows.items())}
    return out


def _ses_by_n(cells: dict) -> dict[str, dict[int, list[float]]]:
    by_n: dict[str, dict[int, list[float]]] = {probe: {} for probe in PROBES}
    for cell in cells.values():
        n = cell.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            continue
        for probe in PROBES:
            channel = ((cell or {}).get("channels") or {}).get(probe) or {}
            se = _finite(channel.get("se")) if channel.get("valid") else None
            if se is not None:
                by_n[probe].setdefault(int(n), []).append(se)
    return by_n


def floor_at(floors_by_n: dict[int, float] | None, n: int, *, fallback: float | None) -> float | None:
    if not floors_by_n:
        return fallback
    lo, hi = float(n) / FLOOR_N_WINDOW, float(n) * FLOOR_N_WINDOW
    near = [v for k, v in floors_by_n.items() if lo <= k <= hi]
    if near:
        return float(statistics.median(near))
    return fallback
