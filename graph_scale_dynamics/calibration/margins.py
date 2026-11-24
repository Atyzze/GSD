from __future__ import annotations

import math
import time
from collections import defaultdict

MARGINS_CONTRACT = "d-s-margins-1"
SURVEY_RUNGS = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)
GEOMETRY, NULL = "MEASURE", "REFUSE"


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def margins(d_s: dict | None, curves: dict | None) -> dict:
    from graph_scale_dynamics.measurements.spectral_whole_range import whole_range

    d_s = d_s or {}
    evidence = (d_s.get("diffusive_window_evidence")
                or (d_s.get("window") or {}).get("diffusive_window_evidence") or {})
    whole = whole_range((curves or {}).get("return_probability") or {})
    return {"contract": MARGINS_CONTRACT,
            "plateau": {"comparable": bool(evidence.get("comparable")),
                        "delta_aicc": _finite(evidence.get("delta_aicc")),
                        "is_power_law": evidence.get("is_power_law")},
            "whole_range": {"comparable": bool(whole.get("whole_range_comparable")),
                            "delta_aicc": _finite(whole.get("whole_range_delta_aicc")),
                            "points": whole.get("whole_range_points"),
                            "is_power_law": whole.get("whole_range_is_power_law")}}


def margin_task(task: dict) -> dict:
    import numpy as np

    from graph_scale_dynamics.calibration.cells import build_graph, suite_families
    from graph_scale_dynamics.measurements.estimators import _measure_graph

    family = suite_families([task["family"]])[0]
    started = time.monotonic()
    try:
        n, edges = build_graph(family, task["parameter"], task["seed"])
        result, curves = _measure_graph(n, edges, np.random.default_rng(int(task["seed"])), measure_geometry=False)
        record = margins(result.get("d_s"), curves)
        value = _finite((result.get("d_s") or {}).get("d_s")) if (result.get("d_s") or {}).get("valid") else None
        record["d_s"] = value
        stored = task.get("stored_d_s")
        record["matches_the_cell"] = (value == stored) if (value is not None or stored is not None) else True
    except Exception as exc:  # noqa: BLE001
        record = {"contract": MARGINS_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
    record["backfilled_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return dict(task, margins=record, elapsed=round(time.monotonic() - started, 3))


def margins_plan(document: dict, families: list[dict], *, max_n: int | None = None) -> list[dict]:
    wanted = {f["name"] for f in families}
    todo = []
    for key, cell in (document.get("cells") or {}).items():
        if cell.get("family") not in wanted or cell.get("status") != "ok":
            continue
        if isinstance(cell.get("d_s_margins"), dict) and not cell["d_s_margins"].get("error"):
            continue
        n = int(cell.get("n") or 0)
        if max_n is not None and n > int(max_n):
            continue
        d_s = (cell.get("channels") or {}).get("d_s") or {}
        todo.append({"key": key, "family": cell["family"], "parameter": cell["parameter"], "seed": int(cell["seed"]),
                     "n": n, "stored_d_s": _finite(d_s.get("value")) if d_s.get("valid") else None})
    todo.sort(key=lambda t: (t["n"], t["family"], t["seed"]))
    return todo


def survey_rung(n: int) -> int:
    return min(SURVEY_RUNGS, key=lambda rung: abs(math.log(max(1, int(n))) - math.log(rung)))


def bands(rows: list[dict]) -> dict:
    grouped: dict[int, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    reported: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        kind = {GEOMETRY: "geometry", NULL: "no finite dimension"}.get(row.get("expectation"))
        if kind is None:
            continue
        rung = survey_rung(int(row["n"]))
        for margin in ("plateau", "whole_range"):
            value = _finite(row.get(margin))
            if value is not None:
                grouped[rung][margin][kind].append(value)
        if kind == "no finite dimension" and row.get("valid") and _finite(row.get("plateau")) is not None:
            reported[rung][str(row["family"])].append(float(row["plateau"]))
    out = {}
    for rung in sorted(grouped):
        entry = {}
        for margin, kinds in grouped[rung].items():
            geometry, null = kinds.get("geometry") or [], kinds.get("no finite dimension") or []
            entry[margin] = {"geometry": ([round(min(geometry), 2), round(max(geometry), 2)] if geometry else None),
                             "no_finite_dimension": ([round(min(null), 2), round(max(null), 2)] if null else None),
                             "separated": (min(geometry) > max(null)) if geometry and null else None,
                             "cells": {"geometry": len(geometry), "no_finite_dimension": len(null)}}
        entry["null_families_reported"] = {family: [round(min(v), 2), round(max(v), 2)]
                                           for family, v in sorted(reported[rung].items())}
        out[str(rung)] = entry
    return out


def table_rows(document: dict) -> list[dict]:
    from graph_scale_dynamics.calibration.cells import suite_families
    from graph_scale_dynamics.calibration.table import cell_is_current

    kinds = {f["name"]: f.get("expectation") for f in suite_families()}
    rows = []
    for cell in (document.get("cells") or {}).values():
        if not cell_is_current(cell):
            continue
        found = cell.get("d_s_margins")
        if not isinstance(found, dict) or found.get("error"):
            continue
        rows.append({"family": cell.get("family"), "expectation": kinds.get(cell.get("family")), "n": cell.get("n"),
                     "valid": bool(((cell.get("channels") or {}).get("d_s") or {}).get("valid")),
                     "plateau": (found.get("plateau") or {}).get("delta_aicc"),
                     "whole_range": (found.get("whole_range") or {}).get("delta_aicc")})
    return rows


BANDS_FILE = "d_s_margin_bands.json"
BANDS_CONTRACT = "d-s-margin-bands-2"
SEED_TABLE = "calibration/seed_table.json"


def from_table(document: dict, *, table_sha256: str) -> dict:
    rows = table_rows(document or {})
    return {"contract": BANDS_CONTRACT,
            "source": {"table": SEED_TABLE, "table_sha256": table_sha256,
                       "estimator_fingerprint": (document or {}).get("estimator_fingerprint")},
            "bands": bands(rows), "cells_with_margins": len(rows),
            "max_n": max((int(r["n"]) for r in rows if r.get("n")), default=None), "seeds": None,
            "computed_utc": (document or {}).get("written_utc"),
            "reading": ("Where d_s's two AICc margins put the calibration's geometry families and its families with "
                        "no finite dimension, per survey rung, from every cell of the seed table that carries its "
                        "margins (tools/calibrate_margins.py --write). Reporting only; no gate reads it.")}


def seed_bands(root=None) -> dict:
    import hashlib
    import json
    from pathlib import Path

    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    raw = (base / SEED_TABLE).read_bytes()
    return from_table(json.loads(raw), table_sha256=hashlib.sha256(raw).hexdigest())


def committed_bands() -> dict | None:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "resources" / "calibration" / BANDS_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def place(delta, n: int, table: dict | None) -> str:
    value = _finite(delta)
    if value is None:
        return "no comparison"
    if value <= 2.0:
        return "not reported (2 or less)"
    entry = ((table or {}).get("bands") or {}).get(str(survey_rung(n))) or {}
    plateau = entry.get("plateau") or {}
    geometry, null = plateau.get("geometry"), plateau.get("no_finite_dimension")
    if not geometry or not null:
        return "reported, no band at this rung"
    in_geometry, in_null = value >= geometry[0], value <= null[1]
    if in_geometry and in_null:
        return "reported, where both kinds of family sit"
    if in_null:
        return "reported, where only families with no finite dimension sit"
    if in_geometry:
        return "reported, where only geometry families sit"
    return "reported, between the two kinds"
