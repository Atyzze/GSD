from __future__ import annotations

from collections import Counter, defaultdict
import math
import statistics
from typing import Iterable

from graph_scale_dynamics.scaleflow.probes import PROBES, Bucket
from graph_scale_dynamics.research.stability_score import noise_floors, noise_floors_by_n, population_summary
from graph_scale_dynamics.research.score_door import score_evidence

LANDSCAPE_AUDIT_VERSION = "landscape-audit-2"
from graph_scale_dynamics.scheduling.base_block import DEFAULT_BASE_SIZES, snapshot_base_sizes
from graph_scale_dynamics.research.numeric import finite as _finite
from graph_scale_dynamics.research.refused_rungs import refused
CONNECTIVITY_FLOOR = 0.90


def snapshot_connectivity_floor(snapshot: dict | None) -> float:
    from graph_scale_dynamics.scheduling.limits import connectivity_floor
    spec = ((snapshot or {}).get("campaign") or {}).get("spec")
    return connectivity_floor(spec) if isinstance(spec, dict) else CONNECTIVITY_FLOOR
DEFAULT_DIMENSION_BIN_WIDTH = 0.50

CONNECTIVITY_FLAT_DELTA = 0.005
CONNECTIVITY_DRIFT_SHRINK_MAX = 0.75


def _slope_vs_log_n(values: Iterable[object], sizes=DEFAULT_BASE_SIZES) -> float | None:
    pairs = []
    for n, value in zip(sizes, values, strict=False):
        value = _finite(value)
        if value is not None:
            pairs.append((math.log(float(n)), value))
    if len(pairs) < 2:
        return None
    mx = statistics.fmean(x for x, _ in pairs)
    my = statistics.fmean(y for _, y in pairs)
    den = sum((x - mx) ** 2 for x, _ in pairs)
    if den <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / den


def stability_signal(values: Iterable[object]) -> dict:
    clean = [_finite(v) for v in values]
    valid = [v for v in clean if v is not None]
    deltas = [b - a for a, b in zip(clean, clean[1:], strict=False) if a is not None and b is not None]
    last_delta = deltas[-1] if deltas else None
    first_delta = deltas[0] if deltas else None
    shrink = None
    if first_delta is not None and last_delta is not None:
        shrink = abs(last_delta) / (abs(first_delta) + 1e-12)
    return {
        "valid_points": len(valid),
        "slope_vs_log_n": _slope_vs_log_n(clean),
        "first_delta": first_delta,
        "last_delta": last_delta,
        "drift_shrink_ratio": shrink,
    }


def connectivity_signal(values: Iterable[object], *, floor: float = CONNECTIVITY_FLOOR) -> dict:
    clean = [_finite(v) for v in values]
    valid = [v for v in clean if v is not None]
    deltas = [b - a for a, b in zip(clean, clean[1:], strict=False) if a is not None and b is not None]
    last_delta = deltas[-1] if deltas else None
    previous_delta = deltas[-2] if len(deltas) >= 2 else None
    floor_failed = any(v < float(floor) for v in valid)
    if not valid:
        classification = "UNAVAILABLE"
    elif floor_failed:
        classification = "FAILED_FLOOR"
    elif last_delta is None:
        classification = "ABOVE_FLOOR_INSUFFICIENT_TREND"
    elif last_delta >= -CONNECTIVITY_FLAT_DELTA:
        classification = "ROBUST_COHERENT"
    elif previous_delta is not None and previous_delta < 0 and abs(last_delta) <= CONNECTIVITY_DRIFT_SHRINK_MAX * abs(previous_delta):
        classification = "ABOVE_FLOOR_STABILIZING"
    else:
        classification = "ABOVE_FLOOR_DECLINING"
    return {
        "floor": float(floor),
        "valid_points": len(valid),
        "minimum": min(valid) if valid else None,
        "endpoint": valid[-1] if valid else None,
        "slope_vs_log_n": _slope_vs_log_n(clean),
        "previous_delta": previous_delta,
        "last_delta": last_delta,
        "classification": classification,
        "floor_failed": floor_failed,
    }


def stability_class(scored: dict) -> str:
    buckets = [scored["buckets"][probe] for probe in PROBES]
    if all(b == Bucket.CONVERGED.value for b in buckets):
        return "STABLE_ALL_PROBES"
    if any(b == Bucket.CONVERGED.value for b in buckets):
        return "STABLE_SOME_PROBES"
    if any(b == Bucket.STILL_DRIFTING.value for b in buckets):
        return "STILL_DRIFTING"
    counts = Counter(b for b in buckets if b)
    if not counts:
        return Bucket.NOT_ATTEMPTED.value
    return max(sorted(counts), key=lambda b: counts[b])


def snapshot_landscape_rows(snapshot: dict) -> list[dict]:
    calibration = snapshot.get("calibration") if isinstance(snapshot.get("calibration"), dict) else None
    return candidate_landscape_rows(list(snapshot.get("phenotypes") or []), calibration_table=calibration,
                                    connectivity_floor=snapshot_connectivity_floor(snapshot))


def candidate_landscape_rows(phenotypes: list[dict], *, calibration_table: dict | None = None,
                             connectivity_floor: float = CONNECTIVITY_FLOOR) -> list[dict]:
    floors = noise_floors(calibration_table)
    floors_by_n = noise_floors_by_n(calibration_table)
    from graph_scale_dynamics.research.stability_score import control_family_reference
    reference = control_family_reference(calibration_table)
    rows = []
    for item in phenotypes:
        phenotype = item.get("phenotype") or {}
        vectors = phenotype.get("probe_vectors") or {}
        connected = list(phenotype.get("connected_fraction_vector") or [])
        conn_sig = connectivity_signal(connected, floor=connectivity_floor)
        scored = score_evidence(phenotype=phenotype, floors=floors, floors_by_n=floors_by_n,
                                connectivity_floor=connectivity_floor, control_reference=reference)
        row = {
            "candidate_id": str(item.get("candidate_id") or ""),
            "phenotype_contract": phenotype.get("contract"),
            "connectivity": conn_sig,
            "stability_blocks": scored["blocks"],
            "buckets": scored["buckets"],
            "valid_rungs": scored["valid_rungs"],
            "dimensional_class": stability_class(scored),
            "connected_fraction_vector": connected,
        }
        for probe in PROBES:
            row[probe] = stability_signal(vectors.get(probe) or [])
            row[f"{probe}_vector"] = list(vectors.get(probe) or [])
        rows.append(row)
    return rows


def _bin_center(value: float, width: float) -> float:
    return (math.floor(float(value) / width) + 0.5) * width


def _histogram(values: list[float], width: float) -> dict:
    counts = Counter(_bin_center(v, width) for v in values)
    bins = [{"center": round(center, 6), "count": counts[center]} for center in sorted(counts)]
    interior_gaps = []
    if counts:
        lo = math.floor(min(values) / width)
        hi = math.floor(max(values) / width)
        occupied_indices = {math.floor(v / width) for v in values}
        for index in range(lo + 1, hi):
            if index in occupied_indices:
                continue
            left = any(i < index for i in occupied_indices)
            right = any(i > index for i in occupied_indices)
            if left and right:
                interior_gaps.append(round((index + 0.5) * width, 6))
    return {"bin_width": width, "bins": bins, "interior_empty_bins": interior_gaps}


def _occupancy_for_n(phenotypes: list[dict], n: int, width: float, floor: float = CONNECTIVITY_FLOOR) -> dict:
    values: dict[str, list[float]] = {probe: [] for probe in PROBES}
    joint = Counter()
    funnel = Counter()
    for item in phenotypes:
        row = ((item.get("phenotype") or {}).get("per_n") or {}).get(str(n)) or {}
        funnel["complete_candidates"] += 1
        present = {probe: None if refused(row.get(f"{probe}_bucket")) else _finite(row.get(probe)) for probe in PROBES}
        conn = _finite(row.get("connected_fraction"))
        terminal = str(row.get("rung_terminal_classification") or "UNKNOWN")
        for probe, value in present.items():
            if value is not None:
                funnel[f"{probe}_valid"] += 1
                values[probe].append(value)
        all_present = all(v is not None for v in present.values())
        if all_present:
            funnel["joint_dimension_valid"] += 1
            joint[tuple(_bin_center(present[probe], width) for probe in PROBES)] += 1
        if conn is not None and conn >= floor:
            funnel["connectivity_above_floor"] += 1
        if all_present and conn is not None and conn >= floor:
            funnel["joint_valid_and_connected"] += 1
        if terminal == "EQUILIBRATED_ACTIVE":
            funnel["equilibrated_active"] += 1
    cells = [
        {**{f"{probe}_center": round(center, 6) for probe, center in zip(PROBES, key, strict=True)}, "count": count}
        for key, count in sorted(joint.items())
    ]
    out = {
        "n": int(n),
        "probes": list(PROBES),
        "gate_funnel": dict(funnel),
        "joint_cells": cells,
        "joint_occupied_cells": len(cells),
    }
    for probe in PROBES:
        out[f"{probe}_histogram"] = _histogram(values[probe], width)
    return out


def _cell_set(row: dict) -> set[tuple]:
    return {tuple(float(cell[f"{probe}_center"]) for probe in PROBES) for cell in row.get("joint_cells") or []}


def _scale_persistence(per_n: list[dict]) -> list[dict]:
    out = []
    for left, right in zip(per_n, per_n[1:], strict=False):
        a, b = _cell_set(left), _cell_set(right)
        union = a | b
        out.append({
            "from_n": left["n"], "to_n": right["n"],
            "occupied_union": len(union),
            "occupied_intersection": len(a & b),
            "jaccard": (len(a & b) / len(union) if union else None),
        })
    return out


def seed_replication_summary(phenotypes: list[dict], base=DEFAULT_BASE_SIZES) -> dict:
    counts = Counter()
    by_n = {}
    for n in base:
        seed_counts = []
        for item in phenotypes:
            row = ((item.get("phenotype") or {}).get("per_n") or {}).get(str(n)) or {}
            value = row.get("measurement_seed_count")
            if isinstance(value, int) and value >= 0:
                seed_counts.append(value)
        by_n[str(n)] = {
            "reported_candidates": len(seed_counts),
            "one_seed": sum(v == 1 for v in seed_counts),
            "multiple_seeds": sum(v >= 2 for v in seed_counts),
            "max_seed_count": max(seed_counts, default=0),
        }
        counts.update(seed_counts)
    deepest = base[-1]
    deepest_row = by_n.get(str(deepest), {})
    deepest_reported = int(deepest_row.get("reported_candidates") or 0)
    deepest_multi = int(deepest_row.get("multiple_seeds") or 0)
    return {
        "by_n": by_n,
        "candidates_with_any_multi_seed_base_rung": sum(
            any((((item.get("phenotype") or {}).get("per_n") or {}).get(str(n)) or {}).get("measurement_seed_count", 0) >= 2
                for n in base)
            for item in phenotypes
        ),
        "deepest_rung_replication": {
            "n": deepest,
            "reported_candidates": deepest_reported,
            "multiple_seeds": deepest_multi,
            "multiple_seed_fraction": (round(deepest_multi / deepest_reported, 4)
                                       if deepest_reported else None),
            "max_seed_count": int(deepest_row.get("max_seed_count") or 0),
            "interpretation": ("reproducibility at the rung the ladder exists to reach. "
                               "`candidates_with_any_multi_seed_base_rung` is satisfied by the "
                               "cheapest rung and must not be read as coverage of this one"),
        },
        "interpretation": "seed count is replication coverage, not agreement; dispersion requires per-seed measurements",
    }


def build_landscape_audit(snapshot: dict, *, bin_width: float = DEFAULT_DIMENSION_BIN_WIDTH) -> dict:
    phenotypes = list(snapshot.get("phenotypes") or [])
    floor = snapshot_connectivity_floor(snapshot)
    candidates = snapshot_landscape_rows(snapshot)
    per_n = [_occupancy_for_n(phenotypes, n, float(bin_width), floor) for n in snapshot_base_sizes(snapshot)]
    connectivity_counts = Counter(row["connectivity"]["classification"] for row in candidates)
    dimensional_counts = Counter(row["dimensional_class"] for row in candidates)
    nulls = list(snapshot.get("nulls") or [])
    locality = list(snapshot.get("locality") or [])
    locality_classes = Counter(str((row.get("result") or {}).get("classification") or row.get("classification") or "UNKNOWN") for row in locality)
    exposures = list(snapshot.get("exposures") or [])
    family_counts = Counter(str((row.get("coordinates") or {}).get("family_id") or row.get("dependence_unit_id") or "unknown") for row in exposures)
    return {
        "version": LANDSCAPE_AUDIT_VERSION,
        "scope_and_completeness": {
            "admitted_candidates": len(snapshot.get("candidates") or []),
            "complete_base_block_phenotypes": len(phenotypes),
            "base_sizes": list(snapshot_base_sizes(snapshot)),
            "dimension_bin_width": float(bin_width),
            "connectivity_floor": floor,
            "reporting_only": True,
        },
        "gate_funnel": {str(row["n"]): row["gate_funnel"] for row in per_n},
        "dimensional_occupancy": per_n,
        "candidate_gaps_and_boundaries": {
            str(row["n"]): {
                **{f"{probe}_interior_empty_bins": row[f"{probe}_histogram"]["interior_empty_bins"]
                   for probe in PROBES},
                "warning": "empty histogram bins are candidate gaps only; exposure, censoring and estimator validity can create them",
            }
            for row in per_n
        },
        "persistent_gap_summary": persistent_gap_summary(per_n),
        "scale_persistence": _scale_persistence(per_n),
        "dimensional_cell_evidence": dimensional_cell_evidence(snapshot, n=4096, bin_width=bin_width),
        "connectivity_viability": {
            "classification_counts": dict(connectivity_counts),
            "candidates": [
                {"candidate_id": row["candidate_id"], **row["connectivity"]}
                for row in candidates
                if row["connectivity"]["classification"] != "ROBUST_COHERENT"
            ],
            "contract": {
                "floor": floor,
                "below_floor": "FAILED_FLOOR",
                "above_floor_continuing_decline": "ABOVE_FLOOR_DECLINING",
                "shrinking_decline": "ABOVE_FLOOR_STABILIZING",
                "flat_or_improving": "ROBUST_COHERENT",
                "effect": "reporting only; no live rejection",
            },
        },
        "dimensional_classes": {
            "counts": dict(dimensional_counts),
            "candidates": [
                {"candidate_id": row["candidate_id"], "class": row["dimensional_class"],
                 "buckets": row["buckets"],
                 "valid_rungs": row["valid_rungs"],
                 **{probe: row[probe] for probe in PROBES},
                 "connectivity": row["connectivity"]}
                for row in candidates
            ],
            "stability": population_summary([
                {"buckets": row["buckets"]} for row in candidates
            ]),
            "classification_rule": {
                "basis": ("research/stability_score.py, each probe's block bucket (CONVERGED, STILL_DRIFTING or a "
                          "refusal), `research/stability_report_parts.definition`"),
                "STABLE_ALL_PROBES": "every block converged",
                "STABLE_SOME_PROBES": "at least one block converged",
                "STILL_DRIFTING": "no block converged, at least one measured and drifting",
                "other": "the refusal bucket named most often across the four blocks",
                "effect": "descriptive ranking only; no search or decision reads it",
            },
        },
        "seed_replication": seed_replication_summary(phenotypes, snapshot_base_sizes(snapshot)),
        "estimator_validity_context": estimator_validity_context(phenotypes, snapshot_base_sizes(snapshot)),
        "sampler_and_null_robustness": {
            "locality_audit_count": len(locality),
            "locality_classifications": dict(locality_classes),
            "locality_detail": sampler_robustness_context(locality),
            "beta_zero_control_count": len(nulls),
            "missing_is_not_support": True,
        },
        "exposure_adjusted_occupancy": exposure_adjusted_occupancy(snapshot, bin_width=bin_width),
        "exposure_context": {
            "proposal_events": len(exposures),
            "dependence_families_observed": len(family_counts),
            "largest_family_exposure": max(family_counts.values(), default=0),
            "warning": "historical search-measure events do not encode every coefficient/operator opportunity; do not infer full-space coverage from admitted candidates",
        },
        "artifact_hypotheses": [
            "a gap can be created when estimator-invalid candidates have no dimension coordinate",
            "a band can be sharpened by finite fit windows or validity thresholds",
            "selected continuation can distort prevalence if mixed with the neutral common-prefix cohort",
            "proposal/admission exposure can create density differences unrelated to landscape volume",
        ],
        "landscape_hypotheses": [
            "a cluster that persists across N, independent seeds, lineages, correct samplers and controls is increasingly consistent with a recurrent landscape basin",
            "a reproducible sharp change between nearby Hamiltonians is consistent with a local boundary/transition and should be tested with stored-spec local contrasts",
            "independent structural families tracing similar multi-rung flow are candidates for universality rather than proposer-local clustering",
        ],
        "limitations": [
            "invalid or censored dimensions generally have no coordinate, so pre-gate dimensional occupancy cannot be reconstructed from phenotype summaries alone",
            "four base rungs do not establish an asymptotic dimension",
            "seed count alone does not establish seed agreement; per-seed dispersion must be measured from raw measurement rows",
            "presence-conditioned term correlations are confounded by interactions and adaptive exposure",
        ],
        "recommended_followups": [
            "compare per-seed dispersion with across-N drift for every plateau-like candidate",
            "compare candidate gaps across N and against null/alternate-sampler evidence",
            "re-run stored artifacts through admissible estimator robustness variants before calling a boundary intrinsic",
            "track recurrence of dimensional cells across independent dependence families and proposal lineages",
        ],
    }


def _distribution(values: Iterable[object]) -> dict:
    clean = sorted(value for raw in values if (value := _finite(raw)) is not None)
    if not clean:
        return {"count": 0, "min": None, "median": None, "p90": None, "max": None}
    index = min(len(clean) - 1, max(0, math.ceil(0.90 * len(clean)) - 1))
    return {
        "count": len(clean), "min": clean[0], "median": statistics.median(clean),
        "p90": clean[index], "max": clean[-1],
    }


def estimator_validity_context(phenotypes: list[dict], base=DEFAULT_BASE_SIZES) -> dict:
    by_n = {}
    for n in base:
        counts = Counter()
        ds_valid_fraction = []
        dh_valid_fraction = []
        for item in phenotypes:
            row = ((item.get("phenotype") or {}).get("per_n") or {}).get(str(n)) or {}
            ds = _finite(row.get("d_s"))
            dh = _finite(row.get("d_V"))
            ds_v = _finite(row.get("d_s_valid_fraction"))
            dh_v = _finite(row.get("d_V_valid_fraction"))
            no_window = _finite(row.get("d_s_no_window_fraction"))
            if ds_v is not None:
                ds_valid_fraction.append(ds_v)
            if dh_v is not None:
                dh_valid_fraction.append(dh_v)
            if ds is not None:
                counts["d_s_coordinate_present"] += 1
            elif no_window is not None and no_window >= 0.5:
                counts["d_s_missing_no_diffusive_window_dominant"] += 1
            else:
                counts["d_s_missing_other_or_unresolved"] += 1
            if dh is not None:
                counts["d_V_coordinate_present"] += 1
            else:
                counts["d_V_missing"] += 1
        by_n[str(n)] = {
            "counts": dict(counts),
            "d_s_valid_fraction": _distribution(ds_valid_fraction),
            "d_V_valid_fraction": _distribution(dh_valid_fraction),
        }
    return {
        "by_n": by_n,
        "interpretation": "dimension coordinates disappear when an estimator is invalid/censored; visible gaps must therefore be checked against these missing-coordinate populations",
    }


def exposure_adjusted_occupancy(snapshot: dict, *, bin_width: float = DEFAULT_DIMENSION_BIN_WIDTH) -> dict:
    exposures = list(snapshot.get("exposures") or [])
    exposure_by_unit = Counter(str(row.get("dependence_unit_id") or "unknown") for row in exposures)
    selected_unit = {
        str(row.get("candidate_id")): str(row.get("dependence_unit_id") or "unknown")
        for row in exposures if row.get("selected") and row.get("candidate_id")
    }
    per_n = []
    for n in snapshot_base_sizes(snapshot):
        cells = defaultdict(lambda: {"raw_count": 0, "adjusted_weight": 0.0, "calibrated_count": 0})
        measured = calibrated = 0
        for item in snapshot.get("phenotypes") or []:
            cid = str(item.get("candidate_id") or "")
            row = ((item.get("phenotype") or {}).get("per_n") or {}).get(str(n)) or {}
            ds, dh = _finite(row.get("d_s")), _finite(row.get("d_V"))
            if ds is None or dh is None:
                continue
            measured += 1
            key = (_bin_center(ds, bin_width), _bin_center(dh, bin_width))
            cell = cells[key]
            cell["raw_count"] += 1
            unit = selected_unit.get(cid)
            exposure = exposure_by_unit.get(unit, 0) if unit else 0
            if exposure > 0:
                weight = 1.0 / float(exposure)
                cell["adjusted_weight"] += weight
                cell["calibrated_count"] += 1
                calibrated += 1
        rows = []
        for (ds, dh), value in sorted(cells.items()):
            rows.append({
                "d_s_center": round(ds, 6), "d_V_center": round(dh, 6),
                "raw_count": value["raw_count"],
                "adjusted_weight": round(value["adjusted_weight"], 10),
                "calibrated_count": value["calibrated_count"],
            })
        per_n.append({
            "n": n, "measured_joint_coordinates": measured, "calibrated_coordinates": calibrated,
            "calibration_coverage": (calibrated / measured if measured else None), "cells": rows,
        })
    return {
        "method": "inverse recorded dependence-unit proposal exposure",
        "bin_width": float(bin_width), "by_n": per_n,
        "interpretation": "diagnostic importance-like reweighting only; it is not an absolute density or a uniform prior over Hamiltonians",
    }


def sampler_robustness_context(locality_rows: list[dict]) -> dict:
    classifications = Counter()
    comparison = Counter()
    ds_differences = []
    candidate_rows = []
    for row in locality_rows:
        result = row.get("result") or {}
        classification = str(result.get("classification") or row.get("classification") or "UNKNOWN")
        classifications[classification] += 1
        comparisons = list(result.get("comparisons") or [])
        for item in comparisons:
            if item.get("agrees_with_canonical") is True:
                comparison["agrees_with_canonical"] += 1
            elif item.get("agrees_with_canonical") is False:
                comparison["does_not_agree_with_canonical"] += 1
            terminal = str(item.get("terminal_classification") or "UNKNOWN")
            comparison[f"terminal:{terminal}"] += 1
            ds, canonical = _finite(item.get("d_s")), _finite(item.get("canonical_d_s"))
            if ds is not None and canonical is not None:
                ds_differences.append(ds - canonical)
        candidate_rows.append({
            "candidate_id": row.get("candidate_id"), "classification": classification,
            "comparisons": len(comparisons),
            "agreements": sum(item.get("agrees_with_canonical") is True for item in comparisons),
        })
    return {
        "audit_candidates": len(locality_rows),
        "classifications": dict(classifications),
        "comparison_counts": dict(comparison),
        "d_s_minus_canonical": _distribution(ds_differences),
        "candidates": candidate_rows,
        "interpretation": "alternate-locality agreement strengthens robustness; unresolved or missing audit evidence is not agreement",
    }


def persistent_gap_summary(per_n: list[dict]) -> dict:
    out = {}
    for metric, key in ((probe, f"{probe}_histogram") for probe in PROBES):
        seen = Counter()
        by_n = {}
        for row in per_n:
            gaps = list((row.get(key) or {}).get("interior_empty_bins") or [])
            by_n[str(row.get("n"))] = gaps
            seen.update(gaps)
        out[metric] = {
            "by_n": by_n,
            "gaps_seen_at_two_or_more_base_sizes": [
                {"center": center, "base_size_count": count}
                for center, count in sorted(seen.items()) if count >= 2
            ],
        }
    out["warning"] = "persistence across N strengthens a gap hypothesis but does not rule out an estimator boundary that also scales with N"
    return out


def dimensional_cell_evidence(snapshot: dict, *, n: int = 4096,
                              bin_width: float = DEFAULT_DIMENSION_BIN_WIDTH) -> dict:
    landscape = {row["candidate_id"]: row for row in snapshot_landscape_rows(snapshot)}
    exposure = {
        str(row.get("candidate_id")): row for row in snapshot.get("exposures") or []
        if row.get("selected") and row.get("candidate_id")
    }
    locality = defaultdict(list)
    for row in snapshot.get("locality") or []:
        cid = str(row.get("candidate_id") or "")
        result = row.get("result") or {}
        locality[cid].append(str(result.get("classification") or row.get("classification") or "UNKNOWN"))
    cells = defaultdict(lambda: {
        "candidate_ids": [], "families": set(), "sources": set(), "lineages": set(),
        "stable_all_probes": 0, "stable_some_probes": 0, "connectivity_floor_pass": 0,
        "multi_seed": 0, "locality_audited": 0, "locality_classifications": Counter(),
    })
    for item in snapshot.get("phenotypes") or []:
        cid = str(item.get("candidate_id") or "")
        p = item.get("phenotype") or {}
        endpoint = (p.get("per_n") or {}).get(str(n)) or {}
        present = {probe: _finite(endpoint.get(probe)) for probe in PROBES}
        if any(v is None for v in present.values()):
            continue
        key = tuple(_bin_center(present[probe], bin_width) for probe in PROBES)
        cell = cells[key]
        cell["candidate_ids"].append(cid)
        e = exposure.get(cid) or {}
        coords = e.get("coordinates") or {}
        family = str(coords.get("family_id") or e.get("dependence_unit_id") or "unknown")
        if family != "unknown":
            cell["families"].add(family)
        if e.get("source"):
            cell["sources"].add(str(e["source"]))
        cell["lineages"].add(str(e.get("lineage_parent") or cid))
        l = landscape.get(cid) or {}
        if l.get("dimensional_class") == "STABLE_ALL_PROBES":
            cell["stable_all_probes"] += 1
        if l.get("dimensional_class") in {"STABLE_ALL_PROBES", "STABLE_SOME_PROBES"}:
            cell["stable_some_probes"] += 1
        if not bool((l.get("connectivity") or {}).get("floor_failed")):
            cell["connectivity_floor_pass"] += 1
        if int(endpoint.get("measurement_seed_count") or 0) >= 2:
            cell["multi_seed"] += 1
        if locality.get(cid):
            cell["locality_audited"] += 1
            cell["locality_classifications"].update(locality[cid])
    rows = []
    for key, cell in cells.items():
        count = len(cell["candidate_ids"])
        families = len(cell["families"])
        if count == 1:
            recurrence = "SINGLETON"
        elif families >= 2:
            recurrence = "RECURRENT_MULTI_FAMILY"
        else:
            recurrence = "RECURRENT_WITHIN_RECORDED_FAMILY"
        rows.append({
            **{f"{probe}_center": round(center, 6) for probe, center in zip(PROBES, key, strict=True)},
            "candidate_count": count,
            "recurrence_class": recurrence, "independent_dependence_families": families,
            "lineage_roots_or_parents": len(cell["lineages"]), "proposal_sources": sorted(cell["sources"]),
            "stable_all_probes_count": cell["stable_all_probes"],
            "stable_some_probes_count": cell["stable_some_probes"],
            "connectivity_floor_pass_count": cell["connectivity_floor_pass"],
            "multi_seed_count": cell["multi_seed"], "locality_audited_count": cell["locality_audited"],
            "locality_classifications": dict(cell["locality_classifications"]),
            "candidate_ids": cell["candidate_ids"][:50],
        })
    rows.sort(key=lambda row: (-row["candidate_count"], -row["independent_dependence_families"],
                               *[row[f"{probe}_center"] for probe in PROBES]))
    return {
        "n": int(n), "bin_width": float(bin_width), "occupied_cells": len(rows), "cells": rows,
        "interpretation": "cell recurrence, family diversity, replication and sampler audits are separate evidence axes; no aggregate score is used",
    }
