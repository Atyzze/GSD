from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping

LANE_CONTRACT = "gsd-all-rung-lanes-1"

COMMON_PREFIX = (64, 256, 1024, 4096)

DEEP_THRESHOLDS = (16384, 65536, 262144, 1048576)


def is_deep(n: int) -> bool:
    return int(n) > max(COMMON_PREFIX)


def _measurements_by_candidate_n(snapshot: Mapping) -> dict:
    index: dict[tuple[str, int], list] = defaultdict(list)
    for row in snapshot.get("measurements") or []:
        key = (str(row.get("candidate_id") or ""), int(row.get("n") or 0))
        index[key].append(row)
    for rows in index.values():
        rows.sort(key=lambda row: str(row.get("created_utc") or ""))
    return index


def _selection_reason(decisions: Iterable[Mapping], n: int) -> dict:
    best = None
    for decision in decisions or []:
        if decision.get("action") == "run_next" and int(decision.get("next_n") or 0) == int(n):
            best = decision
    if best is None:
        return {"action": None, "reason": "no engine decision in the snapshot bought this rung"}
    return {
        "action": best.get("rule"),
        "decision_id": best.get("decision_id"),
        "created_utc": best.get("created_utc"),
        "reasons": [best.get("reason")],
        "priority": best.get("priority"),
    }


def _probe_cell(summary: Mapping, probe: str) -> dict:
    node = summary.get(probe) if isinstance(summary.get(probe), dict) else {}
    refusals = summary.get("probe_refusals")
    codes = dict((refusals or {}).get(probe) or {}) if isinstance(refusals, dict) else {}
    mean = node.get("mean")
    if mean is not None:
        status = "measured"
    elif codes:
        status = max(sorted(codes), key=lambda code: codes[code])
    else:
        status = "not_attempted"
    return {
        "value": mean,
        "uncertainty": node.get("se"),
        "status": status,
        "n_seeds": node.get("n_seeds"),
        "between_seed_sd": node.get("between_seed_sd"),
        "valid_fraction": summary.get(f"{probe}_valid_fraction"),
        "refusals": codes,
    }


def _rung_row(rung: Mapping, metrics: Mapping) -> dict:
    summary = rung.get("summary") or {}
    health = (metrics or {}).get("health") or {}
    n = int(rung.get("n") or 0)
    probes = {probe: _probe_cell(summary, probe) for probe in ("d_s", "d_V", "d_B", "d_w")}
    measured = [p for p in probes.values() if p["value"] is not None]
    return {
        "n": n,
        "evidence_scope": "selected_deep" if is_deep(n) else "neutral_base",
        "d_s": probes["d_s"],
        "d_V": probes["d_V"],
        "d_B": probes["d_B"],
        "d_w": probes["d_w"],
        "probes_measured": len(measured),
        "seeds": summary.get("seeds"),
        "valid_seeds": (summary.get("d_s") or {}).get("n_seeds")
                       if isinstance(summary.get("d_s"), dict) else None,
        "mean_degree": (summary.get("mean_degree") or {}).get("mean")
                       if isinstance(summary.get("mean_degree"), dict) else None,
        "clustering": (summary.get("clustering") or {}).get("mean")
                      if isinstance(summary.get("clustering"), dict) else None,
        "equilibration_status": (health.get("rung_terminal") or {}).get("classification"),
        "estimator_validity": summary.get("d_s_valid_fraction"),
        "spectral_window": summary.get("d_s_no_window_fraction"),
        "connectivity": (summary.get("connected_fraction") or {}).get("mean")
                        if isinstance(summary.get("connected_fraction"), dict) else None,
        "ess": (summary.get("effective_samples") or {}).get("mean")
               if isinstance(summary.get("effective_samples"), dict) else summary.get("effective_samples"),
        "iat": (summary.get("iat_sweeps") or {}).get("mean")
               if isinstance(summary.get("iat_sweeps"), dict) else summary.get("iat_sweeps"),
        "stationarity_drift": (summary.get("stationarity_drift") or {}).get("mean")
                              if isinstance(summary.get("stationarity_drift"), dict)
                              else summary.get("stationarity_drift"),
    }


def build_lanes(snapshot: Mapping) -> dict:
    rungs_by: dict[str, list] = defaultdict(list)
    for row in snapshot.get("rungs") or []:
        rungs_by[str(row.get("candidate_id") or "")].append(row)
    measurements = _measurements_by_candidate_n(snapshot)
    decisions = snapshot.get("engine_decisions") or {}

    neutral_candidates = 0
    deep_rows: list[dict] = []
    deep_coverage = {f">={threshold}": 0 for threshold in DEEP_THRESHOLDS}
    reason_counts: Counter = Counter()

    for candidate_id, rows in rungs_by.items():
        ordered = sorted(rows, key=lambda row: int(row.get("n") or 0))
        ns = [int(row.get("n") or 0) for row in ordered]
        if set(COMMON_PREFIX).issubset(set(ns)):
            neutral_candidates += 1
        deep_ns = [n for n in ns if is_deep(n)]
        if not deep_ns:
            continue

        rung_rows = []
        for row in ordered:
            n = int(row.get("n") or 0)
            history = measurements.get((str(candidate_id), n)) or []
            metrics = (history[-1].get("metrics") if history else {}) or {}
            rung_rows.append(_rung_row(row, metrics))

        selection = _selection_reason(decisions.get(str(candidate_id)) or [], max(deep_ns))
        reason_counts[str(selection.get("action") or "UNRECORDED")] += 1
        for threshold in DEEP_THRESHOLDS:
            if max(deep_ns) >= threshold:
                deep_coverage[f">={threshold}"] += 1

        deep_rows.append({
            "candidate_id": str(candidate_id),
            "available_n": ns,
            "deep_n": deep_ns,
            "max_n": max(ns) if ns else None,
            "rungs": rung_rows,
            "coordinate_source": "latest_rung",
            "selection_reason": selection,
            "selection_biased": True,
        })

    deep_rows.sort(key=lambda row: (-(row.get("max_n") or 0), row["candidate_id"]))
    return {
        "contract": LANE_CONTRACT,
        "neutral_common_prefix": {
            "lane": "neutral_common_prefix",
            "sizes": list(COMMON_PREFIX),
            "candidates_with_complete_prefix": neutral_candidates,
            "selection_biased": False,
            "prevalence_denominator": True,
            "note": ("Unbiased population lane. Every complete candidate is measured at these "
                     "rungs, so counts here may be used as prevalence denominators."),
        },
        "selected_continuation": {
            "lane": "selected_continuation",
            "candidates": deep_rows,
            "candidate_count": len(deep_rows),
            "deep_coverage": deep_coverage,
            "selection_reason_distribution": dict(sorted(reason_counts.items())),
            "selection_biased": True,
            "prevalence_denominator": False,
            "note": ("Adaptive continuation lane. Candidates appear here because a scientific "
                     "decision granted deeper compute, so these rows are selection-biased by "
                     "construction and must never be used as a prevalence denominator."),
        },
    }


