from __future__ import annotations

from collections import Counter
import hashlib
import json
import math

from graph_scale_dynamics.research.proposal_intelligence import proposal_coordinates

SEARCH_MEASURE_VERSION = "search-measure-1"
DEFAULT_BIN_WIDTH = 0.25


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def dependence_unit(spec: dict) -> tuple[str, str]:
    coordinates = proposal_coordinates(spec)
    family_id = coordinates["family_id"]
    return f"family:{family_id}", coordinates["family_label"]


def exposure_record(spec: dict, *, source: str, lineage_parent: str | None,
                    pool_id: str, pool_index: int, selected: bool = False,
                    candidate_id: str | None = None) -> dict:
    coordinates = proposal_coordinates(spec)
    unit_id, unit_label = dependence_unit(spec)
    fingerprint_payload = {
        "version": SEARCH_MEASURE_VERSION,
        "pool_id": pool_id,
        "pool_index": int(pool_index),
        "proposal": coordinates["physical_equivalence_id"],
        "source": source,
        "lineage_parent": lineage_parent,
    }
    event_id = hashlib.sha256(_encoded(fingerprint_payload).encode()).hexdigest()
    return {
        "event_id": event_id,
        "version": SEARCH_MEASURE_VERSION,
        "pool_id": pool_id,
        "pool_index": int(pool_index),
        "source": source,
        "lineage_parent": lineage_parent,
        "selected": bool(selected),
        "candidate_id": candidate_id,
        "dependence_unit_id": unit_id,
        "dependence_unit_label": unit_label,
        "coordinates": coordinates,
    }


def exposure_summary(events: list[dict]) -> dict:
    opportunities = [row for row in events if row.get("version") == SEARCH_MEASURE_VERSION]
    selected = [row for row in opportunities if row.get("selected")]
    units = Counter(str(row.get("dependence_unit_id") or "unknown") for row in opportunities)
    sources = Counter(str(row.get("source") or "unknown") for row in opportunities)
    return {
        "version": SEARCH_MEASURE_VERSION,
        "opportunities": len(opportunities),
        "selected": len(selected),
        "selection_rate": (len(selected) / len(opportunities) if opportunities else None),
        "dependence_units": len(units),
        "unit_exposure": dict(units),
        "sources": dict(sources),
    }


def _bin_center(value: float, width: float) -> float:
    return (math.floor(value / width) + 0.5) * width


def dimension_landscape(nodes: list[dict], events: list[dict], *,
                        bin_width: float = DEFAULT_BIN_WIDTH) -> dict:
    width = float(bin_width)
    if not math.isfinite(width) or width <= 0:
        raise ValueError("bin_width must be finite and positive")

    summary = exposure_summary(events)
    exposure_by_unit = Counter(
        str(row.get("dependence_unit_id") or "unknown")
        for row in events if row.get("version") == SEARCH_MEASURE_VERSION
    )
    selected_unit = {
        str(row.get("candidate_id")): str(row.get("dependence_unit_id") or "unknown")
        for row in events
        if row.get("version") == SEARCH_MEASURE_VERSION and row.get("selected")
        and row.get("candidate_id")
    }

    bins: dict[float, dict] = {}
    measured = 0
    calibrated = 0
    stable = 0
    for node in nodes:
        value = node.get("d_s_estimate")
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            continue
        measured += 1
        center = _bin_center(float(value), width)
        bucket = bins.setdefault(center, {
            "center": round(center, 6),
            "raw_count": 0,
            "adjusted_weight": 0.0,
            "stable_raw_count": 0,
            "stable_adjusted_weight": 0.0,
        })
        bucket["raw_count"] += 1
        unit = selected_unit.get(str(node.get("candidate_id")))
        exposure = exposure_by_unit.get(unit, 0) if unit else 0
        weight = (1.0 / exposure) if exposure > 0 else 0.0
        if weight > 0:
            calibrated += 1
        bucket["adjusted_weight"] += weight
        is_stable = bool(node.get("d_s_stable"))
        if is_stable:
            stable += 1
            bucket["stable_raw_count"] += 1
            bucket["stable_adjusted_weight"] += weight

    rows = []
    for center in sorted(bins):
        row = bins[center]
        row["adjusted_weight"] = round(row["adjusted_weight"], 8)
        row["stable_adjusted_weight"] = round(row["stable_adjusted_weight"], 8)
        rows.append(row)
    return {
        "version": SEARCH_MEASURE_VERSION,
        "status": "diagnostic",
        "interpretation": "inverse dependence-unit proposal exposure; not an absolute density",
        "bin_width": width,
        "measured_candidates": measured,
        "calibrated_candidates": calibrated,
        "stable_candidates": stable,
        "coverage_fraction": (calibrated / measured if measured else None),
        "exposure": summary,
        "bins": rows,
    }
