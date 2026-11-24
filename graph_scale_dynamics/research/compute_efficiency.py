from __future__ import annotations

from graph_scale_dynamics.research.cost_model import build_cost_model
from collections import Counter, defaultdict
import json
import math
import statistics
from typing import Any, Iterable

from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
from graph_scale_dynamics.scheduling.base_block import DEFAULT_BASE_SIZES, snapshot_base_sizes
from graph_scale_dynamics.research.phenotype_symbols import symbolize_phenotype
from graph_scale_dynamics.research.proposal_intelligence import proposal_coordinates

FOUR_CYCLE_OPS = frozenset({"square_count", "induced_square_count", "square_edge_overlap"})
NEIGHBOURHOOD_OPS = frozenset({"triangle_count", "triangle_edge_overlap", "degree_neighbor_gradient", *FOUR_CYCLE_OPS})


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _distribution(values: Iterable[Any]) -> dict:
    xs = sorted(x for value in values if (x := _number(value)) is not None)
    if not xs:
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}

    def percentile(p: float) -> float:
        if len(xs) == 1:
            return xs[0]
        pos = max(0.0, min(1.0, p)) * (len(xs) - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return xs[lo]
        weight = pos - lo
        return xs[lo] * (1.0 - weight) + xs[hi] * weight

    return {
        "count": len(xs), "min": xs[0], "median": statistics.median(xs),
        "p90": percentile(0.90), "p95": percentile(0.95), "max": xs[-1],
    }


def _sum(values: Iterable[Any]) -> float:
    return sum(x for value in values if (x := _number(value)) is not None)


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _job_spec(job: dict) -> dict:
    return _json_value(job.get("spec") if "spec" in job else job.get("spec_json"), {})


def sampling_origin(job: dict, base_sizes=None) -> str:
    from graph_scale_dynamics.scheduling.job_labels import BASE, LONGER, RUNG_STAGE, simulation_role
    role = simulation_role(job, base_sizes if base_sizes is not None else DEFAULT_BASE_SIZES)
    if role == LONGER:
        return "LONGER_RUN"
    if str(job.get("stage") or "").startswith(f"{RUNG_STAGE}_n"):
        return "BASE_BREADTH" if role == BASE else "EXTENSION_DEPTH"
    requested_by = str(job.get("requested_by") or "")
    stage = str(job.get("stage") or "")
    token = f"{requested_by} {stage}".upper()
    if "LONGER_RUN" in token:
        return "LONGER_RUN"
    if "MORE_SEEDS" in token:
        return "MORE_SEEDS"
    if "NEXT_RUNG_PROBE" in token or "CONTINUATION_PROBE" in token:
        return "NEXT_RUNG_PROBE"
    if "ROBUSTNESS" in token or "HOLDOUT" in token or "CONFIRM" in token:
        return "DEEP_CONFIRMATION"
    if "EXTENSION" in token:
        return "EXTENSION_DEPTH"
    if "PILOT" in token or "BASE" in token or "NEXT_N" in token:
        return "BASE_BREADTH"
    return "OTHER"


def sweeps_multiplier(job: dict) -> float:
    execution = (_job_spec(job).get("execution") or {})
    value = _number(execution.get("sweeps_multiplier"))
    return value if value is not None and value > 0 else 1.0


def attempted_move_proxy(job: dict) -> float | None:
    spec = _job_spec(job)
    candidate = spec.get("candidate_spec") or {}
    dynamics = candidate.get("dynamics") or {}
    base_sweeps = _number(dynamics.get("sweeps"))
    if base_sweeps is None:
        base_sweeps = _number((spec.get("dynamics") or {}).get("sweeps"))
    n = int(job.get("n") or 0)
    if base_sweeps is None or base_sweeps <= 0 or n <= 0:
        return None
    return 2.0 * n * base_sweeps * sweeps_multiplier(job)


def recorded_moves(row: dict) -> int | None:
    resource = row.get("resource_json")
    if isinstance(resource, str):
        if '"cpu_speed"' not in resource:
            return None
        try:
            resource = json.loads(resource)
        except ValueError:
            return None
    speed = (resource or {}).get("cpu_speed") if isinstance(resource, dict) else None
    moves = (speed or {}).get("moves") if isinstance(speed, dict) else None
    return int(moves) if isinstance(moves, (int, float)) and not isinstance(moves, bool) and moves > 0 else None


def attempted_moves(row: dict) -> float | None:
    recorded = recorded_moves(row)
    return float(recorded) if recorded is not None else attempted_move_proxy(row)


def _moves_basis(rows) -> dict:
    rows = list(rows)
    recorded = sum(1 for row in rows if recorded_moves(row) is not None)
    return {"recorded": recorded, "declared": len(rows) - recorded}


def _candidate_coordinates(snapshot: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for candidate in snapshot.get("candidates") or []:
        cid = str(candidate.get("candidate_id") or "")
        if not cid:
            continue
        try:
            coords = proposal_coordinates(candidate.get("spec") or {})
        except Exception:
            terms = (candidate.get("spec") or {}).get("terms") or []
            signature = "+".join(sorted(str(term.get("op") or "unknown") for term in terms)) or "unknown"
            coords = {
                "operator_signature": signature,
                "family_id": signature,
                "family_label": signature,
            }
        out[cid] = coords
    return out


def _phenotype_regions(snapshot: dict) -> dict[str, str]:
    out = {}
    for row in snapshot.get("phenotypes") or []:
        cid = str(row.get("candidate_id") or "")
        try:
            region = symbolize_phenotype(row.get("phenotype") or {}).get("region_key")
        except Exception:
            region = None
        if cid and region:
            out[cid] = str(region)
    return out


def _candidate_outcomes(snapshot: dict) -> dict[str, str]:
    out = {str(row.get("candidate_id")): str(row.get("state") or "UNKNOWN")
           for row in snapshot.get("candidates") or [] if row.get("candidate_id")}
    for cid, rows in (snapshot.get("engine_decisions") or {}).items():
        ordered = sorted(rows or [], key=lambda row: str(row.get("decision_id") or ""))
        if ordered:
            out[str(cid)] = str(ordered[-1].get("rule") or out.get(str(cid), "UNKNOWN"))
    return out


def _simulation_rows(snapshot: dict) -> list[dict]:
    jobs = {str(row.get("job_id")): row for row in snapshot.get("jobs") or [] if row.get("job_id")}
    source = snapshot.get("attempts")
    if source is None:
        source = snapshot.get("simulation_attempts") or []
    rows = []
    for attempt in source or []:
        if not (attempt.get("attempt_id") or attempt.get("simulation_attempt_id")):
            continue
        job = jobs.get(str(attempt.get("job_id") or ""), {})
        kind = str(attempt.get("kind") or job.get("kind") or "simulate")
        if kind != "simulate":
            continue
        rows.append({**job, **attempt, "kind": "simulate"})
    return rows


def _analysis_rows(snapshot: dict) -> list[dict]:
    return [dict(row) for row in snapshot.get("analysis_attempts") or []]


def _auxiliary_rows(snapshot: dict) -> list[dict]:
    return [dict(row) for row in snapshot.get("auxiliary_attempts") or []]


def _wall(row: dict) -> float:
    return max(0.0, _number(row.get("wall_seconds")) or 0.0)


def _cpu(row: dict) -> float | None:
    process = _number(row.get("process_cpu_seconds"))
    if process is not None:
        return max(0.0, process)
    user = _number(row.get("user_cpu_seconds"))
    system = _number(row.get("system_cpu_seconds"))
    if user is None and system is None:
        resource = _json_value(row.get("resource") if "resource" in row else row.get("resource_json"), {})
        user = _number(resource.get("user_cpu_seconds"))
        system = _number(resource.get("system_cpu_seconds"))
    if user is None and system is None:
        return None
    return max(0.0, (user or 0.0) + (system or 0.0))


def _memory(row: dict) -> tuple[float | None, str | None]:
    pss = _number(row.get("peak_pss_bytes"))
    if pss is not None and pss > 0:
        return pss, "pss"
    uss = _number(row.get("peak_uss_bytes"))
    if uss is not None and uss > 0:
        return uss, "uss"
    rss = _number(row.get("peak_rss_bytes"))
    if rss is not None and rss > 0:
        return rss, "rss_fallback"
    return None, None


def _stage_entry(name: str, rows: list[dict]) -> dict:
    walls = [_wall(row) for row in rows if row.get("wall_seconds") is not None]
    cpus = [_cpu(row) for row in rows]
    cpu_known = [x for x in cpus if x is not None]
    memories = [_memory(row)[0] for row in rows]
    return {
        "stage": name,
        "attempts": len(rows),
        "wall_seconds": _sum(walls),
        "wall_distribution_seconds": _distribution(walls),
        "cpu_seconds_observed": _sum(cpu_known),
        "cpu_seconds_observed_attempts": len(cpu_known),
        "peak_physical_memory_bytes": _distribution(memories),
    }


def stage_cost(snapshot: dict) -> dict:
    sim = _simulation_rows(snapshot)
    analysis = _analysis_rows(snapshot)
    auxiliary = _auxiliary_rows(snapshot)
    stages = [_stage_entry("simulation", sim), _stage_entry("analysis", analysis)]
    by_aux: dict[str, list[dict]] = defaultdict(list)
    for row in auxiliary:
        by_aux[str(row.get("work_kind") or "auxiliary")].append(row)
    stages.extend(_stage_entry(f"auxiliary:{kind}", rows) for kind, rows in sorted(by_aux.items()))
    total_wall = sum(float(row["wall_seconds"]) for row in stages)
    for row in stages:
        row["wall_fraction"] = (row["wall_seconds"] / total_wall) if total_wall > 0 else None
    return {
        "stages": stages,
        "total_measured_wall_seconds": total_wall,
        "cpu_note": "CPU seconds are reported only where process/user+system CPU was recorded; wall time is not silently relabeled as CPU time.",
    }


def _cost_cell(rows: list[dict], total: float) -> dict:
    wall = sum(_wall(row) for row in rows)
    cpus = [_cpu(row) for row in rows]
    return {
        "jobs": len({str(row.get("job_id") or "") for row in rows}),
        "attempts": len(rows), "wall_seconds": wall,
        "wall_fraction": wall / total if total > 0 else None,
        "wall_distribution_seconds": _distribution(_wall(row) for row in rows),
        "cpu_seconds_observed": _sum(v for v in cpus if v is not None),
        "cpu_seconds_observed_attempts": sum(v is not None for v in cpus),
        "peak_physical_memory_bytes": _distribution(_memory(row)[0] for row in rows),
    }


def cost_by_n(snapshot: dict) -> list[dict]:
    jobs = {str(row.get("job_id")): row for row in snapshot.get("jobs") or [] if row.get("job_id")}
    rows_by_n: dict[int, list[dict]] = defaultdict(list)
    for row in _simulation_rows(snapshot):
        n = int(row.get("n") or 0)
        if n > 0:
            rows_by_n[n].append(row)
    total = sum(_wall(row) for rows in rows_by_n.values() for row in rows)
    out = []
    for n, rows in sorted(rows_by_n.items()):
        by_multiplier: dict[float, list[dict]] = defaultdict(list)
        for row in rows:
            job = jobs.get(str(row.get("job_id") or ""), row)
            by_multiplier[sweeps_multiplier(job)].append(row)
        out.append({
            "n": n,
            **_cost_cell(rows, total),
            "by_sweeps_multiplier": [
                {"sweeps_multiplier": multiplier, **_cost_cell(cell_rows, total)}
                for multiplier, cell_rows in sorted(by_multiplier.items())
            ],
        })
    return out


COMPARISON_MIN_ATTEMPTS = 20

COMPARISON_TOLERANCE = 0.10


def _cell_index(rows: list[dict]) -> dict[tuple[int, float], dict]:
    cells: dict[tuple[int, float], dict] = {}
    for row in rows or []:
        n = int(row.get("n") or 0)
        for cell in row.get("by_sweeps_multiplier") or []:
            multiplier = float(cell.get("sweeps_multiplier") or 0.0)
            if n > 0 and multiplier > 0:
                cells[(n, multiplier)] = cell
    return cells


def compare_cost_by_n(baseline: list[dict], candidate: list[dict], *,
                      min_attempts: int = COMPARISON_MIN_ATTEMPTS,
                      tolerance: float = COMPARISON_TOLERANCE) -> dict:
    before, after = _cell_index(baseline), _cell_index(candidate)
    regressions, improvements, unchanged, thin = [], [], [], []

    for key in sorted(before.keys() & after.keys()):
        n, multiplier = key
        old_cell, new_cell = before[key], after[key]
        old_attempts = int(old_cell.get("attempts") or 0)
        new_attempts = int(new_cell.get("attempts") or 0)
        old_median = (old_cell.get("wall_distribution_seconds") or {}).get("median")
        new_median = (new_cell.get("wall_distribution_seconds") or {}).get("median")

        record = {"n": n, "sweeps_multiplier": multiplier,
                  "baseline_attempts": old_attempts, "candidate_attempts": new_attempts,
                  "baseline_median_wall_seconds": old_median,
                  "candidate_median_wall_seconds": new_median}

        if old_median is None or new_median is None or float(old_median) <= 0:
            record["reason"] = "no usable median wall time on one side"
            thin.append(record)
            continue
        if min(old_attempts, new_attempts) < min_attempts:
            record["reason"] = f"fewer than {min_attempts} attempts on one side"
            thin.append(record)
            continue

        change = (float(new_median) - float(old_median)) / float(old_median)
        record["change_fraction"] = change
        if change > tolerance:
            regressions.append(record)
        elif change < -tolerance:
            improvements.append(record)
        else:
            unchanged.append(record)

    return {
        "contract": "gsd-performance-cell-comparison-1",
        "tolerance": tolerance,
        "min_attempts": min_attempts,
        "compared_cells": len(regressions) + len(improvements) + len(unchanged),
        "regressions": regressions,
        "improvements": improvements,
        "unchanged": unchanged,
        "too_thin_to_compare": thin,
        "unmatched_baseline_cells": [{"n": n, "sweeps_multiplier": m}
                                     for n, m in sorted(before.keys() - after.keys())],
        "unmatched_candidate_cells": [{"n": n, "sweeps_multiplier": m}
                                      for n, m in sorted(after.keys() - before.keys())],
        "passed": not regressions,
        "note": (
            "Matched (N, sweeps_multiplier) cells only. Unmatched cells are "
            "reported, never compared: an N bucket mixes sampling regimes and the "
            "mixture moves for scientific reasons, so a per-N comparison reads "
            "that drift as a regression or hides one inside it."
        ),
    }


def _engine_record(row: dict) -> dict:
    resource = row.get("resource_json")
    if isinstance(resource, str):
        try:
            resource = json.loads(resource)
        except ValueError:
            resource = {}
    engine = (resource or {}).get("engine") if isinstance(resource, dict) else None
    return engine if isinstance(engine, dict) else {}


UNSTAMPED_ENGINE = "unstamped (no engine record)"


def _engine_name(row: dict) -> str:
    return str(_engine_record(row).get("name") or UNSTAMPED_ENGINE)


def _engine_fingerprint(row: dict) -> str | None:
    value = _engine_record(row).get("implementation_fingerprint")
    return str(value) if value else None


def sampling_cost_summary(snapshot: dict) -> dict:
    jobs = {str(row.get("job_id")): row for row in snapshot.get("jobs") or [] if row.get("job_id")}
    grouped: dict[tuple[str, float], list[dict]] = defaultdict(list)
    for row in _simulation_rows(snapshot):
        job = jobs.get(str(row.get("job_id") or ""), row)
        grouped[(sampling_origin(job, snapshot_base_sizes(snapshot)), sweeps_multiplier(job))].append(row)
    total = sum(_wall(row) for rows in grouped.values() for row in rows)
    buckets = []
    for (origin, multiplier), rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        wall = sum(_wall(row) for row in rows)
        move_proxy = _sum(attempted_moves(row) for row in rows)
        buckets.append({
            "origin": origin, "sweeps_multiplier": multiplier, "attempts": len(rows),
            "wall_seconds": wall, "wall_fraction": wall / total if total > 0 else None,
            "attempted_move_proxy": move_proxy if move_proxy > 0 else None,
            "wall_seconds_per_attempted_move_proxy": (wall / move_proxy) if move_proxy > 0 else None,
            "moves_basis": _moves_basis(rows),
            "wall_distribution_seconds": _distribution(_wall(row) for row in rows),
        })
    longer = [row for row in buckets if row["origin"] == "LONGER_RUN"]
    by_engine: dict[str, list[dict]] = defaultdict(list)
    for rows_ in grouped.values():
        for row in rows_:
            by_engine[_engine_name(row)].append(row)
    engine_rows = []
    for name, rows_ in sorted(by_engine.items()):
        wall = sum(_wall(row) for row in rows_)
        move_proxy = _sum(attempted_moves(row) for row in rows_)
        engine_rows.append({
            "engine": name, "attempts": len(rows_), "wall_seconds": wall,
            "wall_fraction": wall / total if total > 0 else None,
            "attempted_move_proxy": move_proxy if move_proxy > 0 else None,
            "wall_seconds_per_attempted_move_proxy": (wall / move_proxy) if move_proxy > 0 else None,
            "implementation_fingerprints": sorted({_engine_fingerprint(row) for row in rows_} - {None}),
        })
    return {
        "buckets": buckets,
        "by_engine": engine_rows,
        "by_engine_note": ("wall_seconds_per_attempted_move_proxy across engines on the same "
                           f"population is the speed ratio. {UNSTAMPED_ENGINE!r} rows carry no "
                           "engine record and are reported as their own class: which engine ran "
                           "them is not known from the attempt, and attributing them to one "
                           "would put a campaign's whole unstamped tail inside a named engine's "
                           "ratio. Compare two named engines, never a named one against this."),
        "longer_run_attempts": sum(int(row["attempts"]) for row in longer),
        "longer_run_wall_seconds": sum(float(row["wall_seconds"]) for row in longer),
        "progression_yield": {
            "status": "not_applicable",
            "reason": "the decision engine buys no same-rung refinements (more seeds, longer runs)",
        },
        "classification_note": "Sampling origin is descriptive provenance derived from job stage/requested_by/decision action; it does not alter live policy.",
    }


def operator_cost_summary(snapshot: dict) -> dict:
    coords = _candidate_coordinates(snapshot)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in _simulation_rows(snapshot):
        cid = str(row.get("candidate_id") or "")
        signature = str((coords.get(cid) or {}).get("operator_signature") or "unknown")
        grouped[signature].append(row)
    total = sum(_wall(row) for rows in grouped.values() for row in rows)
    rows = []
    for signature, attempts in grouped.items():
        wall = sum(_wall(row) for row in attempts)
        move_proxy = _sum(attempted_moves(row) for row in attempts)
        rows.append({
            "operator_signature": signature,
            "attempts": len(attempts),
            "candidates": len({str(row.get("candidate_id") or "") for row in attempts}),
            "wall_seconds": wall,
            "wall_fraction": wall / total if total > 0 else None,
            "attempted_move_proxy": move_proxy if move_proxy > 0 else None,
            "wall_seconds_per_attempted_move_proxy": (wall / move_proxy) if move_proxy > 0 else None,
            "moves_basis": _moves_basis(attempts),
            "wall_distribution_seconds": _distribution(_wall(row) for row in attempts),
        })
    rows.sort(key=lambda row: (-row["wall_seconds"], row["operator_signature"]))
    return {
        "operators": rows,
        "warning": "High compute cost is not evidence that an operator is scientifically important.",
    }


def phenotype_cost_summary(snapshot: dict) -> dict:
    regions = _phenotype_regions(snapshot)
    outcomes = _candidate_outcomes(snapshot)
    by_candidate: dict[str, float] = defaultdict(float)
    for row in _simulation_rows(snapshot):
        by_candidate[str(row.get("candidate_id") or "")] += _wall(row)
    for row in _analysis_rows(snapshot):
        by_candidate[str(row.get("candidate_id") or "")] += _wall(row)
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    unresolved = 0.0
    for cid, cost in by_candidate.items():
        region = regions.get(cid, "UNRESOLVED_OR_INCOMPLETE")
        grouped[region].append((cid, cost))
        if region == "UNRESOLVED_OR_INCOMPLETE":
            unresolved += cost
    rows = []
    for region, values in grouped.items():
        rows.append({
            "region_key": region,
            "candidates": len(values),
            "wall_seconds": sum(cost for _, cost in values),
            "candidate_wall_seconds": _distribution(cost for _, cost in values),
            "outcomes": dict(Counter(outcomes.get(cid, "UNKNOWN") for cid, _ in values)),
            "censored": region == "UNRESOLVED_OR_INCOMPLETE",
        })
    rows.sort(key=lambda row: (-row["wall_seconds"], row["region_key"]))
    return {"regions": rows, "unresolved_candidate_wall_seconds": unresolved}


def build_compute_efficiency_report(snapshot: dict) -> dict:
    sim = _simulation_rows(snapshot)
    analysis = _analysis_rows(snapshot)
    auxiliary = _auxiliary_rows(snapshot)
    measured_rows = [*sim, *analysis, *auxiliary]
    started = [str(row.get("started_utc")) for row in measured_rows if row.get("started_utc")]
    finished = [str(row.get("finished_utc")) for row in measured_rows if row.get("finished_utc")]
    missing_wall = sum(row.get("wall_seconds") is None for row in measured_rows)
    warnings = []
    if missing_wall:
        warnings.append(f"{missing_wall} attempt rows have no wall_seconds and are excluded from wall-time totals")
    if not analysis:
        warnings.append("no analysis-attempt ledger rows are present in this snapshot")
    if not sim:
        warnings.append("no simulation-attempt ledger rows are present in this snapshot")

    return {
        "scope_and_completeness": {
            "campaign_id": snapshot.get("campaign_id"),
            "analysis_version": snapshot.get("analysis_version"),
            "current_build_number": BUILD_NUMBER,
            "current_runtime_fingerprint": runtime_fingerprint(),
            "campaign_created_build": (snapshot.get("campaign") or {}).get("created_build"),
            "campaign_created_runtime_fingerprint": (snapshot.get("campaign") or {}).get("created_runtime_fingerprint"),
            "science_contract_hash": (snapshot.get("campaign") or {}).get("science_contract_hash"),
            "search_policy_hash": (snapshot.get("campaign") or {}).get("search_policy_hash"),
            "resource_policy_hash": (snapshot.get("campaign") or {}).get("resource_policy_hash"),
            "experiment_config_hash": (snapshot.get("campaign") or {}).get("experiment_config_hash"),
            "source_revision": snapshot.get("source_revision"),
            "heavy_source_revision": snapshot.get("heavy_source_revision"),
            "source_collected_utc": snapshot.get("collected_utc"),
            "snapshot_contract": snapshot.get("snapshot_contract"),
            "observation_window": {
                "first_started_utc": min(started) if started else None,
                "last_finished_utc": max(finished) if finished else None,
            },
            "counts": {
                "candidates": len(snapshot.get("candidates") or []),
                "jobs": len(snapshot.get("jobs") or []),
                "simulation_attempts": len(sim),
                "analysis_attempts": len(analysis),
                "auxiliary_attempts": len(auxiliary),
                "measurements": len(snapshot.get("measurements") or []),
                "rung_summaries": len(snapshot.get("rungs") if snapshot.get("rungs") is not None else (snapshot.get("rung_summaries") or [])),
                "durable_phenotypes": len(snapshot.get("phenotypes") or []),
            },
            "warnings": warnings,
        },
        "stage_cost": stage_cost(snapshot),
        "cost_by_n": cost_by_n(snapshot),
        "cost_by_sampling": sampling_cost_summary(snapshot),
        "cost_by_operator": operator_cost_summary(snapshot),
        "cost_model": build_cost_model(operator_cost_summary(snapshot)),
        "cost_by_phenotype_and_outcome": phenotype_cost_summary(snapshot),
        "contract": {
            "read_only": True,
            "descriptive_advisory_only": True,
            "live_policy_input": False,
            "missing_evidence_is_not_favorable_evidence": True,
        },
    }
