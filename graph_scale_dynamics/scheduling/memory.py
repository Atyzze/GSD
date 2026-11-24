from __future__ import annotations

import json
import math
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

from graph_scale_dynamics.domain.cadence import ticks
from typing import Any, Callable, Iterator

import psutil

from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_MEMORY_FLOOR as PREEMPT_MEMORY_FLOOR
from graph_scale_dynamics.scheduling.rungs import rung_extension_config
from graph_scale_dynamics.scheduling.runtime import power_fit

GIB = 1024 ** 3
HOST_HARD_SINGLE_JOB_FRACTION_CAP = 0.60
SINGLE_JOB_CEILING_FRACTION = 0.25
GIVEN_BACK_CEILING_FRACTION = 0.35
RUNAWAY_RESERVATION_MULTIPLE = 4.0
RUNAWAY_MIN_BYTES = 2 * 1024 ** 3
RUNAWAY = "runaway"
RUNAWAY_SEEN_SLACK = 1.25
AGGREGATE_MEMORY_TARGET_FRACTION = 0.80
HOST_EMERGENCY_MEMORY_FRACTION_CAP = 0.90
HOST_MIN_AVAILABLE_FRACTION = 0.10
HOST_MIN_AVAILABLE_BYTES = 10 * GIB
HOST_MIN_AVAILABLE_FIXED_FROM_BYTES = 40 * GIB
MEMORY_SHED_MARGIN_BYTES = 2 * GIB
MEMORY_PSI_SOME_AVG10_LIMIT = 5.0
MEMORY_PSI_FULL_AVG10_LIMIT = 1.0
PREDICTION_SANITY_TOTAL_MULTIPLIER = 2.0
MAX_SAME_RUNG_PREDICTION_RATIO = 4.0
MAX_SAME_RUNG_EDGE_RATIO = 4.0
FLEET_PROFILE_QUANTILE = 0.95
LOCAL_RSS_ONLY_PROFILE_QUANTILE = 0.90
RSS_ONLY_ANALYSIS_HARD_CAP_FRACTION = 0.50


DEFAULT_PROCESS_INTERCEPT_FLOOR_BYTES = 896 * 1024 ** 2
MEMORY_CLAIM_LOCK = "gsd:compute-memory-claim"
TRANSIENT_MEMORY_BACKOFF_SECONDS = 5


@dataclass(frozen=True)
class MemorySnapshot:
    total: int
    available: int


def system_memory() -> MemorySnapshot:
    vm = psutil.virtual_memory()
    return MemorySnapshot(total=int(vm.total), available=int(vm.available))


PREDICTION_PROFILE_CACHE_SECONDS = ticks(1)
_PROFILE_CACHE: dict[tuple, tuple[float, Any]] = {}


MEASURED_PEAKS_CACHE_SECONDS = ticks(15)


def _cached_profile(key: tuple, compute, ttl: float | None = None):
    ttl = PREDICTION_PROFILE_CACHE_SECONDS if ttl is None else float(ttl)
    if ttl <= 0:
        return compute()
    now = time.monotonic()
    hit = _PROFILE_CACHE.get(key)
    if hit is not None and (now - hit[0]) < ttl:
        return hit[1]
    value = compute()
    if len(_PROFILE_CACHE) > 4096:
        _PROFILE_CACHE.clear()
    _PROFILE_CACHE[key] = (now, value)
    return value


def reset_prediction_caches() -> None:
    _PROFILE_CACHE.clear()


def memory_pressure_snapshot() -> dict[str, float | bool | None]:
    result: dict[str, float | bool | None] = {
        "available": False, "some_avg10": None, "full_avg10": None,
    }
    try:
        text = open("/proc/pressure/memory", "r", encoding="utf-8").read()
    except (OSError, UnicodeError):
        return result
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] not in {"some", "full"}:
            continue
        values = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            try:
                values[key] = float(value)
            except ValueError:
                continue
        if "avg10" in values:
            result[f"{parts[0]}_avg10"] = float(values["avg10"])
    result["available"] = True
    return result


def host_memory_launch_guard(*, snapshot: MemorySnapshot | None = None) -> dict[str, Any]:
    mem = snapshot or system_memory()
    total = max(1, int(mem.total))
    available = max(0, int(mem.available))
    min_available = host_available_floor_bytes(total)
    used_fraction = 1.0 - (float(available) / float(total))
    psi = memory_pressure_snapshot()
    reasons: list[str] = []
    if used_fraction >= HOST_EMERGENCY_MEMORY_FRACTION_CAP:
        reasons.append("host_emergency_fraction")
    if available < min_available:
        reasons.append("host_available_floor")
    some = psi.get("some_avg10")
    full = psi.get("full_avg10")
    if isinstance(some, (int, float)) and float(some) >= MEMORY_PSI_SOME_AVG10_LIMIT:
        reasons.append("memory_psi_some")
    if isinstance(full, (int, float)) and float(full) >= MEMORY_PSI_FULL_AVG10_LIMIT:
        reasons.append("memory_psi_full")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "total_bytes": total,
        "available_bytes": available,
        "min_available_bytes": min_available,
        "used_fraction_from_available": used_fraction,
        "emergency_fraction": HOST_EMERGENCY_MEMORY_FRACTION_CAP,
        "psi": psi,
    }


def _observed_peak_profile(conn, kind: str) -> dict[int, dict[str, int]]:
    return _cached_profile(("fleet", kind), lambda: _query_peak_profile(conn, kind))


def _memory_observation(row) -> tuple[int, str]:
    pss = int(row.get("peak_pss_bytes") or 0)
    uss = int(row.get("peak_uss_bytes") or 0)
    rss = int(row.get("peak_rss_bytes") or row.get("peak") or 0)
    if pss > 0:
        return pss, "pss"
    if uss > 0:
        return uss, "uss"
    return rss, "rss_only"


def _quantile_index(size: int, quantile: float) -> int:
    if size <= 1:
        return 0
    return min(size - 1, max(0, int(math.ceil(float(quantile) * size)) - 1))


def _profile_from_rows(rows, *, fleet: bool) -> dict[int, dict[str, int | str]]:
    grouped: dict[int, list[dict[str, int | str]]] = {}
    for raw in rows:
        row = dict(raw)
        n = int(row.get("n") or 0)
        edges = int(row.get("edges") or 0)
        peak, metric = _memory_observation(row)
        if n <= 0 or edges <= 0 or peak <= 0:
            continue
        grouped.setdefault(n, []).append({
            "edge_count": edges,
            "peak_rss_bytes": peak,
            "reservation_peak_bytes": peak,
            "memory_metric": metric,
            "observed_rss_bytes": int(row.get("peak_rss_bytes") or row.get("peak") or 0),
        })
    has_physical = any(
        str(item["memory_metric"]) in {"pss", "uss"}
        for points in grouped.values() for item in points
    )
    profile: dict[int, dict[str, int | str]] = {}
    for n, points in grouped.items():
        if has_physical:
            physical = [
                item for item in points
                if str(item["memory_metric"]) in {"pss", "uss"}
            ]
            if not physical:
                continue
            points = physical
        points.sort(key=lambda item: int(item["reservation_peak_bytes"]))
        if fleet:
            index = _quantile_index(len(points), FLEET_PROFILE_QUANTILE)
        elif all(str(item["memory_metric"]) == "rss_only" for item in points):
            index = _quantile_index(len(points), LOCAL_RSS_ONLY_PROFILE_QUANTILE)
        else:
            index = len(points) - 1
        profile[n] = points[index]
    return dict(sorted(profile.items()))


def _query_peak_profile(conn, kind: str) -> dict[int, dict[str, int | str]]:
    if kind == "simulation":
        rows = conn.execute(
            "SELECT j.n AS n,COALESCE(a.final_edge_count,a.peak_edge_count) AS edges,"
            "a.peak_rss_bytes,a.peak_uss_bytes,a.peak_pss_bytes FROM attempts a "
            "JOIN jobs j ON j.job_id=a.job_id WHERE j.kind='simulate' "
            "AND a.peak_rss_bytes IS NOT NULL AND a.peak_rss_bytes>0 "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count) IS NOT NULL "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count)>0"
        ).fetchall()
    elif kind == "analysis":
        rows = conn.execute(
            "SELECT q.n AS n,MAX(COALESCE(a.final_edge_count,a.peak_edge_count)) AS edges,"
            "q.peak_rss_bytes,q.peak_uss_bytes,q.peak_pss_bytes FROM analysis_queue q "
            "JOIN attempts a ON a.job_id=q.producer_job "
            "WHERE q.peak_rss_bytes IS NOT NULL AND q.peak_rss_bytes>0 "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count) IS NOT NULL "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count)>0 "
            "GROUP BY q.n,q.input_artifact,q.peak_rss_bytes,q.peak_uss_bytes,q.peak_pss_bytes"
        ).fetchall()
    else:
        raise ValueError(f"unknown memory profile kind {kind!r}")
    return _profile_from_rows(rows, fleet=True)


def _observed_candidate_peak_profile(conn, kind: str, campaign_id: str,
                                     candidate_id: str) -> dict[int, dict[str, int]]:
    return _cached_profile(
        ("candidate", kind, str(campaign_id), str(candidate_id)),
        lambda: _query_candidate_peak_profile(conn, kind, campaign_id, candidate_id),
    )


def _query_candidate_peak_profile(conn, kind: str, campaign_id: str,
                                  candidate_id: str) -> dict[int, dict[str, int | str]]:
    if kind == "simulation":
        rows = conn.execute(
            "SELECT j.n AS n,COALESCE(a.final_edge_count,a.peak_edge_count) AS edges,"
            "a.peak_rss_bytes,a.peak_uss_bytes,a.peak_pss_bytes FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.kind='simulate' AND j.campaign_id=? AND j.candidate_id=? "
            "AND a.peak_rss_bytes IS NOT NULL AND a.peak_rss_bytes>0 "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count)>0",
            (campaign_id, candidate_id),
        ).fetchall()
    elif kind == "analysis":
        rows = conn.execute(
            "SELECT q.n AS n,MAX(COALESCE(a.final_edge_count,a.peak_edge_count)) AS edges,"
            "q.peak_rss_bytes,q.peak_uss_bytes,q.peak_pss_bytes FROM analysis_queue q "
            "JOIN attempts a ON a.job_id=q.producer_job "
            "WHERE q.campaign_id=? AND q.candidate_id=? "
            "AND q.peak_rss_bytes IS NOT NULL AND q.peak_rss_bytes>0 "
            "AND COALESCE(a.final_edge_count,a.peak_edge_count)>0 "
            "GROUP BY q.n,q.input_artifact,q.peak_rss_bytes,q.peak_uss_bytes,q.peak_pss_bytes",
            (campaign_id, candidate_id),
        ).fetchall()
    else:
        raise ValueError(f"unknown memory profile kind {kind!r}")
    return _profile_from_rows(rows, fleet=False)


MEASURED_INTERCEPT_MAX_RUNG_N = 256
MEASURED_INTERCEPT_MIN_POINTS = 4
MEASURED_INTERCEPT_MARGIN = 1.25
MEASURED_INTERCEPT_FLOOR_BYTES = 64 * 1024 ** 2


def measured_process_intercept_bytes(profile: dict | None) -> int | None:
    small = [peak for n, _edges, peak in _profile_points(profile)
             if n <= MEASURED_INTERCEPT_MAX_RUNG_N and peak > 0]
    if len(small) < MEASURED_INTERCEPT_MIN_POINTS:
        return None
    return int(max(MEASURED_INTERCEPT_FLOOR_BYTES,
                   math.ceil(max(small) * MEASURED_INTERCEPT_MARGIN)))


def _profile_points(profile: dict | None) -> list[tuple[int, int, int]]:
    points: list[tuple[int, int, int]] = []
    for raw_n, value in (profile or {}).items():
        n = int(raw_n)
        if isinstance(value, dict):
            edges = int(value.get("edge_count") or 0)
            peak = int(value.get("reservation_peak_bytes") or value.get("peak_rss_bytes")
                       or value.get("peak") or 0)
        elif isinstance(value, (tuple, list)) and len(value) >= 2:
            edges, peak = int(value[0]), int(value[1])
        else:
            edges, peak = n, int(value)
        if n > 0 and edges > 0 and peak > 0:
            points.append((n, edges, peak))
    return sorted(points)


def _project_edges_from_points(points: list[tuple[int, int, int]], n: int) -> int | None:
    if not points:
        return None
    n = max(1, int(n))
    exact = [edges for pn, edges, _ in points if pn == n]
    if exact:
        return max(exact)
    recent = points[-6:]
    if len(recent) == 1:
        pn, edges, _ = recent[0]
        projected = float(edges) * n / float(pn)
    else:
        fit = power_fit({pn: float(edges) for pn, edges, _ in recent})
        empirical = 0.0
        if fit is not None:
            a, exponent = fit
            exponent = max(1.0, min(2.0, float(exponent)))
            empirical = a * (n ** exponent)
        linear = max(float(edges) / float(pn) for pn, edges, _ in recent[-2:]) * n
        projected = max(empirical, linear)
    complete = n * (n - 1) // 2
    if complete <= 0:
        return 1
    return max(1, min(complete, int(math.ceil(projected))))


def _observed_candidate_edge_points(conn, campaign_id: str,
                                    candidate_id: str) -> list[tuple[int, int, int]]:
    return _cached_profile(
        ("edges", str(campaign_id), str(candidate_id)),
        lambda: _query_candidate_edge_points(conn, campaign_id, candidate_id),
    )


def _query_candidate_edge_points(conn, campaign_id: str,
                                 candidate_id: str) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        "SELECT j.n AS n,COALESCE(a.final_edge_count,a.peak_edge_count) AS edges,"
        "COALESCE(a.peak_rss_bytes,1) AS peak FROM attempts a "
        "JOIN jobs j ON j.job_id=a.job_id "
        "WHERE j.kind='simulate' AND j.campaign_id=? AND j.candidate_id=? "
        "AND COALESCE(a.final_edge_count,a.peak_edge_count) IS NOT NULL "
        "AND COALESCE(a.final_edge_count,a.peak_edge_count)>0",
        (campaign_id, candidate_id),
    ).fetchall()
    by_n: dict[int, tuple[int, int, int]] = {}
    for row in rows:
        n, edges, peak = int(row["n"]), int(row["edges"]), int(row["peak"])
        current = by_n.get(n)
        if current is None or edges > current[1]:
            by_n[n] = (n, edges, peak)
    return [by_n[n] for n in sorted(by_n)]


def projected_candidate_edges(conn, campaign_id: str, candidate_id: str, n: int) -> int | None:
    return _project_edges_from_points(
        _observed_candidate_edge_points(conn, campaign_id, candidate_id), n
    )


def producer_job_edge_count(conn, producer_job: str | None) -> int | None:
    if not producer_job:
        return None
    row = conn.execute(
        "SELECT final_edge_count,peak_edge_count FROM attempts WHERE job_id=? "
        "AND finished_utc IS NOT NULL AND COALESCE(final_edge_count,peak_edge_count)>0 "
        "ORDER BY CASE WHEN exit_code=0 THEN 0 ELSE 1 END,finished_utc DESC LIMIT 1",
        (str(producer_job),),
    ).fetchone()
    if row is None:
        return None
    final_edges = int(row["final_edge_count"] or 0)
    if final_edges > 0:
        return final_edges
    peak_edges = int(row["peak_edge_count"] or 0)
    return peak_edges if peak_edges > 0 else None


def _model_settings(spec: dict, kind: str,
                    measured_intercept: int | None = None) -> tuple[int, int, float]:
    cfg = rung_extension_config(spec)
    if kind == "simulation":
        per_node = int(cfg["simulation_fallback_bytes_per_node"])
        base = int(cfg["simulation_base_bytes"])
    elif kind == "analysis":
        per_node = int(cfg["analysis_fallback_bytes_per_node"])
        base = int(cfg["analysis_base_bytes"])
    else:
        raise ValueError(f"unknown memory kind {kind!r}")
    safety = max(1.0, float(cfg["prediction_safety_multiplier"]))
    floor = max(0, int(cfg["process_intercept_floor_bytes"]))
    if measured_intercept is not None:
        floor = min(floor, int(measured_intercept))
    base = max(base, floor)
    return max(1, per_node), max(0, base), safety


MAX_EDGE_EXTRAPOLATION = 64.0

MIN_RATE_FIT_EDGE_SPAN = 8.0
MIN_MARGINAL_PEAK_FRACTION = 0.75
LEARNED_PREDICTION_CEILING_RATIO = 4.0


def _marginal_bytes_per_edge(points: list[tuple[int, int, int]], base: int) -> float | None:
    slopes: list[float] = []
    for i in range(len(points)):
        _n_a, edges_a, peak_a = points[i]
        for j in range(i + 1, len(points)):
            _n_b, edges_b, peak_b = points[j]
            low, high = min(edges_a, edges_b), max(edges_a, edges_b)
            if low <= 0 or float(high) < MIN_RATE_FIT_EDGE_SPAN * float(low):
                continue
            span = float(edges_b - edges_a)
            if span == 0.0:
                continue
            slopes.append((float(peak_b) - float(peak_a)) / span)
    if slopes:
        slopes.sort()
        middle = len(slopes) // 2
        median = (slopes[middle] if len(slopes) % 2
                  else 0.5 * (slopes[middle - 1] + slopes[middle]))
        return max(0.0, median)
    _n, edges, peak = max(points, key=lambda point: point[1])
    marginal = max(0.0, float(peak) - float(base))
    if edges > 0 and marginal >= MIN_MARGINAL_PEAK_FRACTION * float(peak):
        return marginal / float(edges)
    return None


def _anchored_peak_bytes(points: list[tuple[int, int, int]], target_edges: int,
                         rate: float | None) -> float:
    below = [point for point in points if point[1] <= target_edges]
    pool = below or [min(points, key=lambda point: point[1])]
    anchor_peak = float(max(peak for _n, _edges, peak in pool))
    anchor_edges = max(1, max(edges for _n, edges, _peak in pool))
    if rate is None:
        return anchor_peak
    extra = max(0.0, float(target_edges) - float(anchor_edges))
    extra = min(extra, MAX_EDGE_EXTRAPOLATION * float(anchor_edges))
    return anchor_peak + rate * extra


def predict_peak_bytes(conn, spec: dict, n: int, kind: str, *, profile: dict | None = None,
                       edge_count: int | None = None) -> int:
    n = max(1, int(n))
    profile = _observed_peak_profile(conn, kind) if profile is None else profile
    measured_intercept = measured_process_intercept_bytes(profile)
    fallback_per_node, base, safety = _model_settings(
        spec, kind, measured_intercept=measured_intercept)
    points = _profile_points(profile)
    if not points:
        return int(base + fallback_per_node * n)

    target_edges = max(1, int(edge_count)) if edge_count is not None else _project_edges_from_points(points, n)
    if target_edges is None:
        target_edges = n
    observed_exact = max([peak for pn, _edges, peak in points if pn == n] or [0])

    prior = float(base + fallback_per_node * n)

    recent = points[-6:]
    if measured_intercept is not None:
        prior = min(prior, LEARNED_PREDICTION_CEILING_RATIO
                    * float(max(peak for _pn, _edges, peak in recent)))
    rate = _marginal_bytes_per_edge(recent, base)
    calibrated = _anchored_peak_bytes(recent, target_edges, rate)
    anchor = max(prior, float(observed_exact),
                 float(max(peak for _pn, _edges, peak in recent)))
    ceiling = LEARNED_PREDICTION_CEILING_RATIO * anchor
    bounded = min(calibrated, ceiling)
    return int(math.ceil(max(prior, float(observed_exact), bounded) * safety))


def _deterministic_fallback_peak_bytes(spec: dict, n: int, kind: str) -> int:
    per_node, base, safety = _model_settings(spec, kind)
    return int(math.ceil((float(base) + float(per_node) * max(1, int(n))) * safety))


def fallback_reservation_bytes(spec: dict, n: int, kind: str) -> int:
    return _deterministic_fallback_peak_bytes(spec, n, kind)


def sane_peak_prediction_bytes(conn, spec: dict, n: int, kind: str, *,
                               profile: dict | None = None, edge_count: int | None = None,
                               snapshot: MemorySnapshot | None = None,
                               trust_same_rung: bool = False) -> tuple[int, bool, int | None]:
    try:
        raw = int(predict_peak_bytes(
            conn, spec, n, kind, profile=profile, edge_count=edge_count
        ))
    except (OverflowError, ValueError, TypeError):
        return _deterministic_fallback_peak_bytes(spec, n, kind), True, None
    mem = snapshot or system_memory()
    deterministic_fallback = _deterministic_fallback_peak_bytes(spec, n, kind)
    sanity = max(1, int(mem.total)) * PREDICTION_SANITY_TOTAL_MULTIPLIER
    if raw <= 0 or raw > sanity:
        return deterministic_fallback, True, raw

    if trust_same_rung and profile:
        points = _profile_points(profile)
        same_rung = [(edges, peak) for pn, edges, peak in points if int(pn) == int(n)]
        if same_rung:
            observed_edges, observed_peak = min(
                same_rung, key=lambda item: abs(item[0] - int(edge_count or item[0]))
            )
            target_edges = max(1, int(edge_count or observed_edges))
            edge_ratio = max(
                float(target_edges) / float(max(1, observed_edges)),
                float(max(1, observed_edges)) / float(target_edges),
            )
            _per_node, _base, safety = _model_settings(spec, kind)
            empirical_anchor = max(
                deterministic_fallback,
                int(math.ceil(float(observed_peak) * float(safety))),
            )
            if (edge_ratio <= MAX_SAME_RUNG_EDGE_RATIO
                    and raw > int(math.ceil(empirical_anchor * MAX_SAME_RUNG_PREDICTION_RATIO))):
                return empirical_anchor, True, raw

    return raw, False, raw


def host_available_floor_bytes(total_bytes: int) -> int:
    override = str(os.environ.get("GSD_HOST_MEMORY_FLOOR_BYTES", "")).strip()
    if override:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    total = max(0, int(total_bytes))
    if total >= HOST_MIN_AVAILABLE_FIXED_FROM_BYTES:
        return int(HOST_MIN_AVAILABLE_BYTES)
    return int(total * HOST_MIN_AVAILABLE_FRACTION)


def _observed_bytes(detail_json, keys=("pss", "rss")) -> int | None:
    try:
        detail = json.loads(detail_json) if isinstance(detail_json, str) else (detail_json or {})
    except (TypeError, ValueError):
        return None
    for key in keys:
        value = detail.get(key) if isinstance(detail, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


EXPECTED_PEAK_QUANTILE = 0.95
EXPECTED_PEAK_SLACK = 1.10
TYPICAL_PEAK_QUANTILE = 0.50
SPIKE_OVERLAP = 2


def _measured_quantile(conn, kind: str, n: int, quantile: float) -> int | None:
    if conn is None:
        return None
    peaks = _cached_profile(("measured-peaks", kind, int(n)),
                            lambda: _measured_peaks(conn, kind, int(n), MEASURED_FLOOR_RECENT_LIMIT),
                            ttl=MEASURED_PEAKS_CACHE_SECONDS)
    if not peaks or len(peaks) < MEASURED_FLOOR_MIN_SAMPLES:
        return None
    return peaks[_quantile_index(len(peaks), quantile)]


def _growth_basis(conn, row: dict, quantiles: dict | None = None) -> tuple[int | None, int]:
    kind = "analysis" if row["kind"] == "analysis" else "simulation"
    n = int(row["n"] or 0)
    own = int(row.get("observed_bytes") or 0)
    if quantiles is not None:
        p50, p95 = quantiles.get((kind, n), (None, None))
    else:
        p95 = _measured_quantile(conn, kind, n, EXPECTED_PEAK_QUANTILE)
        p50 = _measured_quantile(conn, kind, n, TYPICAL_PEAK_QUANTILE) if p95 else None
    if not p95:
        return None, max(int(row["reserved_bytes"]), own)
    p50 = p50 or p95
    return int(p50), max(int(math.ceil(float(p95) * EXPECTED_PEAK_SLACK)), own)


def lease_memory_observations(conn) -> list[dict]:
    detail = "CASE WHEN left(h.detail_json,1)='{' THEN h.detail_json::jsonb END"
    rows = conn.execute(
        "SELECT 'simulation' AS kind,j.job_id AS id,j.n,j.memory_reservation_bytes AS reserved,"
        "h.detail_json,(SELECT a.started_utc FROM attempts a WHERE a.job_id=j.job_id "
        "ORDER BY a.started_utc DESC, a.number DESC LIMIT 1) AS started_utc "
        f"FROM jobs j LEFT JOIN service_heartbeats h ON h.service=j.lease_owner AND ({detail})->>'job'=j.job_id "
        "WHERE j.kind='simulate' AND j.status='leased' "
        "UNION ALL SELECT 'analysis' AS kind,q.input_artifact AS id,q.n,q.memory_reservation_bytes AS reserved,"
        "h.detail_json,(SELECT aa.started_utc FROM analysis_attempts aa WHERE aa.campaign_id=q.campaign_id "
        "AND aa.input_artifact=q.input_artifact AND aa.analysis_version=q.analysis_version "
        "ORDER BY aa.started_utc DESC, aa.attempt_number DESC LIMIT 1) AS started_utc FROM analysis_queue q "
        f"LEFT JOIN service_heartbeats h ON h.service=q.lease_owner AND ({detail})->>'artifact'=q.input_artifact "
        "WHERE q.status='leased'"
    ).fetchall()
    out = []
    for row in rows:
        out.append({"kind": str(row["kind"]), "id": str(row["id"]), "n": int(row["n"] or 0),
                    "reserved_bytes": max(0, int(row["reserved"] or 0)),
                    "observed_bytes": _observed_bytes(row["detail_json"]),
                    "current_bytes": _observed_bytes(row["detail_json"], ("pss_now",)),
                    "started_utc": row["started_utc"]})
    return out


SMALL_POOL_FRACTION = 0.01


def small_pool_limit_bytes(total_bytes: int) -> int:
    return int(max(0, int(total_bytes)) * SMALL_POOL_FRACTION)


def _is_small(row: dict, limit: int) -> bool:
    held = int(row.get("current_bytes") or row.get("observed_bytes") or 0)
    return max(int(row.get("reserved_bytes") or 0), held) <= int(limit)


def admitted(row: dict) -> bool:
    return (int(row.get("reserved_bytes") or 0) > 0 or int(row.get("current_bytes") or 0) > 0
            or int(row.get("observed_bytes") or 0) > 0)


def admission_headroom(conn, *, snapshot: MemorySnapshot | None = None,
                       observations: list[dict] | None = None,
                       quantiles: dict | None = None) -> dict[str, Any]:
    mem = snapshot or system_memory()
    total = max(1, int(mem.total))
    available = max(0, int(mem.available))
    floor = host_available_floor_bytes(total)
    rows = lease_memory_observations(conn) if observations is None else observations
    reserved = {"simulation": 0, "analysis": 0}
    growth = {"simulation": 0, "analysis": 0}
    held_total = 0
    spikes: list[int] = []
    small_limit = small_pool_limit_bytes(total)
    large_growth = 0
    for row in rows:
        if not admitted(row):
            continue
        kind = "analysis" if row["kind"] == "analysis" else "simulation"
        reserved[kind] += int(row["reserved_bytes"])
        held = int(row.get("current_bytes") or 0)
        held_total += held
        typical, peak = _growth_basis(conn, row, quantiles)
        to_come = max(0, (peak if typical is None else typical) - held)
        growth[kind] += to_come
        if typical is not None:
            spikes.append(max(0, peak - max(typical, held)))
        if not _is_small(row, small_limit):
            large_growth += to_come
    spike_room = sum(sorted(spikes, reverse=True)[:SPIKE_OVERLAP])
    unrealised = growth["simulation"] + growth["analysis"] + spike_room
    headroom = max(0, available - floor - unrealised)
    return {
        "total_bytes": total, "available_bytes": available, "floor_bytes": floor,
        "shed_below_bytes": max(0, floor - min(MEMORY_SHED_MARGIN_BYTES, floor // 4)),
        "reserved_bytes": reserved["simulation"] + reserved["analysis"],
        "reserved_by_lane": reserved, "held_bytes": held_total,
        "unrealised_bytes": unrealised, "unrealised_by_lane": growth, "spike_room_bytes": spike_room,
        "headroom_bytes": headroom,
        "budget_bytes": reserved["simulation"] + reserved["analysis"] + headroom,
        "small_pool_limit_bytes": small_limit,
        "lent_bytes": large_growth,
        "small_pool_headroom_bytes": max(0, available - floor - (unrealised - large_growth)),
        "small_pool_budget_bytes": (reserved["simulation"] + reserved["analysis"]
                                    + max(0, available - floor - (unrealised - large_growth))),
        "ceiling_bytes": max(0, total - floor),
        "leases": len(rows),
    }


def memory_deferred_simulations(conn) -> int:
    now = time.time()
    row = conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE kind='simulate' AND status='queued' "
        "AND next_attempt_utc IS NOT NULL AND next_attempt_utc>? AND next_attempt_utc<=?",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + TRANSIENT_MEMORY_BACKOFF_SECONDS + 1)))).fetchone()
    return int(row["c"] or 0) if row else 0


def aggregate_launch_budget_bytes(conn, *, snapshot: MemorySnapshot | None = None,
                                  quantiles: dict | None = None) -> int:
    return int(admission_headroom(conn, snapshot=snapshot, quantiles=quantiles)["budget_bytes"])


def admission_quantiles(conn, observations: list[dict] | None = None) -> dict:
    rows = lease_memory_observations(conn) if observations is None else observations
    rungs = sorted({("analysis" if row["kind"] == "analysis" else "simulation", int(row["n"] or 0))
                    for row in rows})
    out = {}
    for kind, n in rungs:
        p95 = _measured_quantile(conn, kind, n, EXPECTED_PEAK_QUANTILE)
        out[(kind, n)] = (_measured_quantile(conn, kind, n, TYPICAL_PEAK_QUANTILE) if p95 else None, p95)
    return out


def memory_shed_reason(conn, job: dict, *, snapshot: MemorySnapshot | None = None,
                       observations: list[dict] | None = None, now: float | None = None,
                       saved_at=None, kind: str = "simulation") -> str | None:
    mem = snapshot or system_memory()
    total = max(1, int(mem.total))
    floor = host_available_floor_bytes(total)
    shed_below = max(0, floor - min(MEMORY_SHED_MARGIN_BYTES, floor // 4))
    available = max(0, int(mem.available))
    if available >= shed_below:
        return None
    rows = list(lease_memory_observations(conn) if observations is None else observations)
    me = ("analysis" if kind == "analysis" else "simulation", str(job.get("job_id")))
    clock = time.time() if now is None else float(now)

    def holds(row: dict) -> int:
        return int(row.get("current_bytes") or row.get("observed_bytes") or row["reserved_bytes"] or 0)

    def cost(row: dict) -> tuple[float, str]:
        held = max(holds(row), 64 * 1024 ** 2)
        started = _utc_seconds(row.get("started_utc"))
        kept = saved_at(str(row["id"])) if callable(saved_at) and row["kind"] == "simulation" else None
        since = max(x for x in (started, kept) if x is not None) if (started or kept) else None
        ran = max(0.0, clock - since) if since is not None else 0.0
        return ran / float(held), str(row["id"])

    needed = floor - available
    freed = 0
    for row in sorted(rows, key=cost):
        if freed >= needed:
            break
        if (row["kind"], str(row["id"])) == me:
            return PREEMPT_MEMORY_FLOOR
        freed += holds(row)
    return None


def _utc_seconds(stamp) -> float | None:
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def own_earlier_seed_bytes(spec: dict, kind: str, local_profile: dict | None, n: int) -> int | None:
    value = (local_profile or {}).get(int(n))
    if not isinstance(value, dict) or str(value.get("memory_metric") or "rss_only") not in ("pss", "uss"):
        return None
    peak = int(value.get("reservation_peak_bytes") or 0)
    if peak <= 0:
        return None
    _per_node, _base, safety = _model_settings(spec, kind)
    return int(math.ceil(float(peak) * float(safety)))


def predicted_claim_peak_bytes(conn, *, kind: str, campaign_id: str,
                               candidate_id: str, n: int, spec: dict,
                               producer_job: str | None = None) -> int:
    fleet_profile = _observed_peak_profile(conn, kind)
    local_profile = _observed_candidate_peak_profile(
        conn, kind, str(campaign_id), str(candidate_id)
    )
    target_n = max(1, int(n))
    edges = (producer_job_edge_count(conn, producer_job)
             if kind == "analysis" and producer_job else None)
    if edges is None:
        edges = projected_candidate_edges(
            conn, str(campaign_id), str(candidate_id), target_n
        )
    seen = runaway_seen_bytes(conn, kind, str(campaign_id), str(candidate_id), target_n)
    floor = int(math.ceil(float(seen) * RUNAWAY_SEEN_SLACK)) if seen else 0
    own = own_earlier_seed_bytes(spec, kind, local_profile, target_n)
    if own is not None:
        measured = _measured_quantile(conn, kind, target_n, EXPECTED_PEAK_QUANTILE)
        own = max(own, int(math.ceil(float(measured) * EXPECTED_PEAK_SLACK))) if measured is not None else own
        return max(own, floor)
    selected_profile = local_profile or fleet_profile
    has_same_rung_anchor = bool(selected_profile and int(target_n) in selected_profile)
    prediction, _fallback, _raw = sane_peak_prediction_bytes(
        conn, spec, target_n, kind,
        profile=selected_profile,
        edge_count=edges,
        trust_same_rung=has_same_rung_anchor,
    )
    if kind == "analysis" and selected_profile:
        metrics = {
            str(value.get("memory_metric") or "rss_only")
            for value in selected_profile.values() if isinstance(value, dict)
        }
        if metrics and metrics <= {"rss_only"}:
            hard = hard_process_limit_bytes(spec, n=target_n)
            bridge = max(
                _deterministic_fallback_peak_bytes(spec, target_n, kind),
                int(float(hard) * RSS_ONLY_ANALYSIS_HARD_CAP_FRACTION),
            )
            prediction = min(int(prediction), int(bridge))
    measured = _measured_quantile(conn, kind, target_n, EXPECTED_PEAK_QUANTILE)
    if measured is not None:
        own = int(prediction) if local_profile and int(target_n) in local_profile else 0
        prediction = max(int(math.ceil(float(measured) * EXPECTED_PEAK_SLACK)), own)
    return max(int(prediction), floor)


def runaway_seen_bytes(conn, kind: str, campaign_id: str, candidate_id: str, n: int) -> int:
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_MEMORY_RUNAWAY
    if conn is None:
        return 0
    if kind == "analysis":
        query = ("SELECT MAX(a.peak_rss_bytes) AS seen FROM analysis_attempts a JOIN analysis_queue q "
                 "ON q.campaign_id=a.campaign_id AND q.input_artifact=a.input_artifact "
                 "WHERE q.campaign_id=? AND q.candidate_id=? AND q.n=? AND a.error_class=?")
    else:
        query = ("SELECT MAX(a.peak_rss_bytes) AS seen FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
                 "WHERE j.campaign_id=? AND j.candidate_id=? AND j.n=? AND a.error_class=?")
    row = conn.execute(query, (campaign_id, candidate_id, int(n), ATTEMPT_CLASS_MEMORY_RUNAWAY)).fetchone()
    return int((row["seen"] if row is not None else 0) or 0)


SETTLED_RESERVATION_SLACK = 1.5
EARLY_RESERVATION_SETTLE_SECONDS = 2.0
EARLY_RESERVATION_SLACK = 3.0
EARLY_RESERVATION_MIN_REDUCTION_FRACTION = 0.50
SETTLED_RESERVATION_WRITE_BAND = 0.125


MEASURED_FLOOR_MIN_SAMPLES = 5
MEASURED_FLOOR_RECENT_LIMIT = 20
MEASURED_FLOOR_QUANTILE = 0.9
MEASURED_FLOOR_SLACK = 1.25


def measured_peak_quantile_bytes(conn, kind: str, n: int, *, quantile: float = MEASURED_FLOOR_QUANTILE,
                                 limit: int = MEASURED_FLOOR_RECENT_LIMIT,
                                 minimum: int = MEASURED_FLOOR_MIN_SAMPLES) -> int | None:
    peaks = _measured_peaks(conn, kind, n, limit)
    if not peaks or len(peaks) < int(minimum):
        return None
    return peaks[_quantile_index(len(peaks), quantile)]


def _measured_peaks(conn, kind: str, n: int, limit: int) -> list[int] | None:
    if conn is None:
        return None
    try:
        if kind == "analysis":
            rows = conn.execute(
                "SELECT a.peak_pss_bytes pss, a.peak_rss_bytes rss FROM analysis_attempts a "
                "JOIN analysis_queue q ON q.campaign_id=a.campaign_id AND q.input_artifact=a.input_artifact "
                "AND q.analysis_version=a.analysis_version "
                "WHERE q.n=? AND a.exit_code=0 AND a.finished_utc IS NOT NULL "
                "ORDER BY a.finished_utc DESC LIMIT ?", (int(n), int(limit))).fetchall()
        else:
            rows = conn.execute(
                "SELECT a.peak_pss_bytes pss, a.peak_rss_bytes rss FROM attempts a "
                "JOIN jobs j ON j.job_id=a.job_id "
                "WHERE j.kind='simulate' AND j.n=? AND a.exit_code=0 AND a.finished_utc IS NOT NULL "
                "ORDER BY a.finished_utc DESC LIMIT ?", (int(n), int(limit))).fetchall()
    except Exception:
        return None
    return [p for p in sorted(int(r["pss"] or r["rss"] or 0) for r in rows) if p > 0]


def evidence_floor_bytes(conn, spec: dict, n: int, kind: str) -> int:
    prior = _deterministic_fallback_peak_bytes(spec, n, kind)
    measured = measured_peak_quantile_bytes(conn, kind, n)
    if measured is None:
        return prior
    return max(1, min(prior, int(math.ceil(float(measured) * MEASURED_FLOOR_SLACK))))


def settled_reservation_bytes(spec: dict, n: int, kind: str, observed_peak_bytes: int,
                              *, snapshot: MemorySnapshot | None = None,
                              slack: float = SETTLED_RESERVATION_SLACK,
                              floor_bytes: int | None = None, hard_cap_bytes: int | None = None) -> int:
    observed = max(0, int(observed_peak_bytes))
    floor = int(floor_bytes) if floor_bytes else _deterministic_fallback_peak_bytes(spec, n, kind)
    settled = max(floor, int(math.ceil(observed * max(1.0, float(slack)))))
    hard_cap = (int(hard_cap_bytes) if hard_cap_bytes else hard_process_limit_bytes(spec, snapshot=snapshot, n=n))
    return max(1, min(settled, hard_cap))


def early_reservation_release_bytes(spec: dict, n: int, kind: str,
                                    observed_peak_bytes: int, current_bytes: int,
                                    *, snapshot: MemorySnapshot | None = None,
                                    floor_bytes: int | None = None) -> int | None:
    current = max(1, int(current_bytes))
    candidate = settled_reservation_bytes(
        spec, n, kind, observed_peak_bytes, snapshot=snapshot,
        slack=EARLY_RESERVATION_SLACK, floor_bytes=floor_bytes,
    )
    if candidate >= current:
        return None
    reduction = float(current - candidate) / float(current)
    if reduction < EARLY_RESERVATION_MIN_REDUCTION_FRACTION:
        return None
    return int(candidate)


def reservation_restatement_is_material(current_bytes: int, settled_bytes: int) -> bool:
    current = max(1, int(current_bytes))
    return abs(int(settled_bytes) - current) / float(current) >= SETTLED_RESERVATION_WRITE_BAND


def recorded_lease_reservations(conn) -> dict[str, int]:
    row = conn.execute(
        "SELECT "
        "COALESCE((SELECT SUM(memory_reservation_bytes) FROM jobs "
        "WHERE kind='simulate' AND status='leased'),0) simulation,"
        "COALESCE((SELECT SUM(memory_reservation_bytes) FROM analysis_queue "
        "WHERE status='leased'),0) analysis"
    ).fetchone()
    simulation = int(row["simulation"] or 0)
    analysis = int(row["analysis"] or 0)
    return {"simulation": simulation, "analysis": analysis,
            "total": simulation + analysis}


LAUNCH_RAMP_SECONDS = 20.0
LAUNCH_BURST_SECONDS = 2.0
LAUNCH_BURST_AVAILABLE_FRACTION = 0.15
LAUNCH_BURST_MAX_GRANTS = 64


def recent_launch_reservations(conn, *, seconds: float = LAUNCH_RAMP_SECONDS) -> dict[str, int]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - max(0.0, float(seconds))))
    try:
        row = conn.execute(
            "SELECT "
            "COALESCE((SELECT SUM(memory_reservation_bytes) FROM jobs "
            "WHERE kind='simulate' AND status='leased' AND updated_utc>=?),0) sim_bytes,"
            "COALESCE((SELECT COUNT(*) FROM jobs "
            "WHERE kind='simulate' AND status='leased' AND updated_utc>=?),0) sim_count,"
            "COALESCE((SELECT SUM(memory_reservation_bytes) FROM analysis_queue "
            "WHERE status='leased' AND updated_utc>=?),0) ana_bytes,"
            "COALESCE((SELECT COUNT(*) FROM analysis_queue "
            "WHERE status='leased' AND updated_utc>=?),0) ana_count",
            (cutoff, cutoff, cutoff, cutoff),
        ).fetchone()
        return {"bytes": int(row["sim_bytes"] or 0) + int(row["ana_bytes"] or 0),
                "count": int(row["sim_count"] or 0) + int(row["ana_count"] or 0),
                "readable": True}
    except Exception:
        return {"bytes": 0, "count": 0, "readable": False}


def launch_ramp_state(conn, *, snapshot: MemorySnapshot | None = None) -> dict[str, Any]:
    ramp = recent_launch_reservations(conn, seconds=LAUNCH_RAMP_SECONDS)
    burst = recent_launch_reservations(conn, seconds=LAUNCH_BURST_SECONDS)
    mem = snapshot or system_memory()
    total = max(1, int(mem.total))
    available = max(0, int(mem.available))
    unfaulted = max(0, int(ramp["bytes"]))
    effective_available = max(0, available - unfaulted)
    floor = host_available_floor_bytes(total)
    burst_limit = int(available * LAUNCH_BURST_AVAILABLE_FRACTION)
    reasons: list[str] = []
    if effective_available < floor:
        reasons.append("launch_ramp_unfaulted")
    if int(burst["bytes"]) > burst_limit:
        reasons.append("launch_burst_bytes")
    if burst["count"] >= LAUNCH_BURST_MAX_GRANTS:
        reasons.append("launch_burst_count")
    return {"allowed": not reasons, "reasons": reasons,
            "window_seconds": LAUNCH_RAMP_SECONDS,
            "recent_grants": ramp["count"], "recent_reserved_bytes": ramp["bytes"],
            "burst_grants": burst["count"], "burst_reserved_bytes": burst["bytes"],
            "burst_limit_bytes": burst_limit,
            "available_bytes": available,
            "effective_available_bytes": effective_available,
            "min_available_bytes": floor}


def admit_recorded_claim(conn, *, kind: str, reservation_bytes: int,
                         budget_bytes: int, job_id: str | None = None,
                         owner: str | None = None, lease_generation: int | None = None,
                         campaign_id: str | None = None, artifact: str | None = None,
                         analysis_version: str | None = None,
                         claim_token: str | None = None,
                         hard_single_job_bytes: int | None = None,
                         snapshot: MemorySnapshot | None = None,
                         reserved_bytes: int | None = None) -> dict[str, Any]:
    reservation = max(0, int(reservation_bytes))
    budget = max(0, int(budget_bytes))
    hard_cap = int(hard_single_job_bytes) if hard_single_job_bytes else 0
    predicted = reservation
    clamped = bool(hard_cap and reservation > hard_cap)
    if clamped:
        reservation = hard_cap
    recorded = recorded_lease_reservations(conn)
    proposed = (int(recorded["total"]) if reserved_bytes is None else int(reserved_bytes)) + reservation
    guard = host_memory_launch_guard(snapshot=snapshot)
    ramp = launch_ramp_state(conn, snapshot=snapshot)
    refusal = None
    if not bool(guard.get("allowed")):
        refusal = "transient_host_pressure"
    elif not bool(ramp.get("allowed")):
        refusal = "transient_launch_ramp"
    elif reservation > int(guard.get("total_bytes") or 0) - int(guard.get("min_available_bytes") or 0):
        refusal = "permanent_over_budget"
    elif proposed > budget:
        refusal = "transient_memory_floor"
    if refusal is not None:
        return {**recorded, "requested": reservation, "budget": budget,
                "predicted": predicted, "clamped_to_ceiling": clamped,
                "hard_single_job_bytes": hard_cap,
                "host_guard": guard, "launch_ramp": ramp,
                "proposed_total": proposed, "within_budget": False,
                "refusal": refusal,
                "permanent": refusal.startswith("permanent"),
                "recorded": False}
    if kind == "simulation":
        if job_id is None or owner is None or lease_generation is None:
            raise ValueError("simulation reservation requires job lease identity")
        changed = conn.execute(
            "UPDATE jobs SET memory_reservation_bytes=? WHERE job_id=? "
            "AND status='leased' AND lease_owner=? AND lease_generation=?",
            (reservation, job_id, owner, int(lease_generation)),
        )
    elif kind == "analysis":
        if (campaign_id is None or artifact is None or analysis_version is None
                or owner is None or claim_token is None):
            raise ValueError("analysis reservation requires analysis lease identity")
        changed = conn.execute(
            "UPDATE analysis_queue SET memory_reservation_bytes=? "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=? "
            "AND status='leased' AND lease_owner=? AND claim_token=?",
            (reservation, campaign_id, artifact, analysis_version, owner, claim_token),
        )
    else:
        raise ValueError(f"unknown memory kind {kind!r}")
    recorded_ok = int(getattr(changed, "rowcount", 0) or 0) == 1
    return {**recorded, "requested": reservation, "budget": budget,
            "predicted": predicted, "clamped_to_ceiling": clamped,
            "host_guard": guard,
            "proposed_total": proposed, "within_budget": bool(recorded_ok),
            "recorded": bool(recorded_ok)}


def locked_admission(repo, *, kind: str, reservation_bytes: int,
                     hard_single_job_bytes: int | None = None, **lease) -> dict[str, Any]:
    quantiles = admission_quantiles(repo.conn)
    repo.acquire_blocking_lock(MEMORY_CLAIM_LOCK)
    try:
        snapshot = system_memory()
        headroom = admission_headroom(repo.conn, snapshot=snapshot, quantiles=quantiles)
        small = int(reservation_bytes) <= int(headroom["small_pool_limit_bytes"])
        from graph_scale_dynamics.scheduling.memory_hold import held_bytes
        held = held_bytes(repo.conn, job_id=lease.get("job_id")) if kind == "simulation" else 0
        budget = max(0, int(headroom["small_pool_budget_bytes" if small else "budget_bytes"]) - held)
        verdict = admit_recorded_claim(repo.conn, kind=kind, reservation_bytes=reservation_bytes,
                                       budget_bytes=budget, hard_single_job_bytes=hard_single_job_bytes,
                                       snapshot=snapshot, reserved_bytes=headroom.get("reserved_bytes"), **lease)
        return {**verdict, "pool": "small" if small else "large", "lent_bytes": headroom["lent_bytes"],
                "held_bytes": held}
    finally:
        repo.release_service_lock(MEMORY_CLAIM_LOCK)


@contextmanager
def returned_on_failure(release: Callable[[], object],
                        report: Callable[[BaseException, bool], object] | None = None) -> Iterator[None]:
    try:
        yield
    except BaseException as error:
        try:
            released = bool(release())
        except Exception as cleanup:
            released = False
            print(f"[claim] could not return a failed claim: {type(cleanup).__name__}: {cleanup}",
                  file=sys.stderr, flush=True)
        if report is not None:
            try:
                report(error, released)
            except Exception as unreported:
                print(f"[claim] returned={released} but not recorded: {unreported}", file=sys.stderr, flush=True)
        raise


def report_returned_claim(repo, kind: str, **identity) -> Callable[[BaseException, bool], None]:
    def report(error: BaseException, released: bool) -> None:
        repo.emit("claim_failed_before_child", {"kind": kind, "released": bool(released),
                                                "error": f"{type(error).__name__}: {error}"[:300],
                                                **identity})
    return report


def effective_hard_fraction(spec: dict, n=None) -> tuple[float, float]:
    cfg = rung_extension_config(spec)
    raw_extension = spec.get("rung_extension") or {}
    resource_limits = spec.get("resource_limits") or {}
    raw_fraction = resource_limits.get(
        "hard_single_job_fraction_total",
        raw_extension.get("hard_single_job_fraction_total", cfg["hard_single_job_fraction_total"]),
    )
    configured = min(0.90, max(0.05, float(raw_fraction)))
    return configured, min(SINGLE_JOB_CEILING_FRACTION, HOST_HARD_SINGLE_JOB_FRACTION_CAP)


def hard_process_limit_bytes(spec: dict, *, snapshot: MemorySnapshot | None = None,
                             n=None) -> int:
    mem = snapshot or system_memory()
    _, effective = effective_hard_fraction(spec, n)
    return max(1, int(max(1, int(mem.total)) * effective))


def given_back_limit_bytes(*, snapshot: MemorySnapshot | None = None) -> int:
    mem = snapshot or system_memory()
    return max(1, int(max(1, int(mem.total)) * min(GIVEN_BACK_CEILING_FRACTION, HOST_HARD_SINGLE_JOB_FRACTION_CAP)))


def process_stop_bytes(spec: dict, n, opening_reservation_bytes: int | None, *,
                       snapshot: MemorySnapshot | None = None) -> tuple[int, str]:
    ceiling = hard_process_limit_bytes(spec, snapshot=snapshot, n=n)
    opening = int(opening_reservation_bytes or 0)
    if opening <= 0:
        return ceiling, "ceiling"
    runaway = max(RUNAWAY_MIN_BYTES, int(RUNAWAY_RESERVATION_MULTIPLE * opening))
    return (runaway, RUNAWAY) if runaway < ceiling else (ceiling, "ceiling")
