from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone

from graph_scale_dynamics.db.decision_store import decision_backlog
from graph_scale_dynamics.db.repo import Repo, heartbeat_interval_seconds
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import (
    POLICY_RULE_VERSION as RULE_VERSION, TERMINAL_CANDIDATE_STATES, ensemble_code,
)
from graph_scale_dynamics.domain.version import BUILD_NUMBER, environment_fingerprint, runtime_fingerprint
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.engine.engine import ENGINE_VERSION
from graph_scale_dynamics.measurements.analysis import select_best_runs
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability import law_status, live_panel as _live
from graph_scale_dynamics.observability.rung_distribution import (
    chains_per_seed,
    live_work_candidate_ids,
    rung_distribution_for,
)
from graph_scale_dynamics.operations import campaign_control
from graph_scale_dynamics.operations.compute_ecology import memory_room
from graph_scale_dynamics.operations.lifecycle_recovery import decision_backlog_alerts, stranded_work_alerts
from graph_scale_dynamics.readmodel.rung_standing import rung_standings, waiting_reason
from graph_scale_dynamics.research.coupling import COUPLING_STRATA, coupling_stratum
from graph_scale_dynamics.research.law_identity import identity_context, node_identity
from graph_scale_dynamics.research.proposal_intelligence import (
    SCALING_PROFILES, SEARCH_SPACE_VERSION, scaling_profile,
)
from graph_scale_dynamics.research.proposal_memory import FAMILY_MEMORY_VERSION
from graph_scale_dynamics.research.search_measure import SEARCH_MEASURE_VERSION, dimension_landscape
from graph_scale_dynamics.scaleflow.equilibration import rung_certified
from graph_scale_dynamics.scaleflow.flow import summary_dimensions as _summary_dims
from graph_scale_dynamics.scheduling import rung_eta as _eta
from graph_scale_dynamics.scheduling.cpu import configured_monitor_ceiling, cpu_topology
from graph_scale_dynamics.scheduling.memory import (
    admission_headroom, aggregate_launch_budget_bytes, effective_hard_fraction, memory_deferred_simulations,
    recorded_lease_reservations,
)
from graph_scale_dynamics.scheduling.rungs import extension_enabled, next_unmeasured_rung, rung_extension_config
from graph_scale_dynamics.scheduling.runtime import observed_profile, predict_wall
from graph_scale_dynamics.services.api import campaign_manager
from graph_scale_dynamics.services.api.host import (
    _cpu_iowait_percent, _note_swallowed, _service_process_sample, host_snapshot,
)
from graph_scale_dynamics.services.api.fleet_snapshots import (
    _analysis_runnable_snapshot, _capacity_diagnosis, _database_io_snapshot, _execution_counts,
    _governor_capacity_snapshot, _one_worker_per_core, _scratch_percent_of_host,
)


OP_SHORT = {"edge_count": "E", "degree_anchor": "(d-{k})²", "degree_anchor_abs": "|d-{k}|",
            "degree_square_sum": "Σd²", "degree_cube_sum": "Σd³", "degree_fourth_sum": "Σd⁴",
            "degree_neighbor_gradient": "Σₑ(Δd)²", "wedge_count": "Λ",
            "triangle_count": "△", "triangle_edge_overlap": "△overlap",
            "square_count": "□", "induced_square_count": "□ind",
            "square_edge_overlap": "□overlap", "ollivier_curvature": "κ"}
SCALE_SHORT = {"one": "", "log_N": "·lnN", "inv_log_N": "/lnN", "inv_N": "/N",
               "inv_sqrt_N": "/√N"}
_CAMPAIGN_STATS_CACHE: dict[str, tuple[str, float, dict]] = {}
ALIVE_WITHIN_SECONDS = 2 * heartbeat_interval_seconds() + ticks(1)


def _pushed_as(repo, spec: dict, rows: list[dict]) -> None:
    from graph_scale_dynamics.operations import focus, push, push_ladder
    if not push_ladder.is_push(spec) or not rows:
        return
    try:
        state = focus.load(repo)
    except Exception as exc:
        _note_swallowed("_pushed_as", exc)
        return
    for row in rows:
        home = push.home_of(state, str(row["candidate_id"]))
        if home:
            row["pushed_as"] = home


def _fleet_mode(repo) -> dict | None:
    from graph_scale_dynamics.operations import modes
    try:
        return modes.here(repo)
    except Exception as exc:
        _note_swallowed("_fleet_mode", exc)
        return None


def _fleet_workers(repo) -> dict | None:
    from graph_scale_dynamics.scheduling import worker_count
    try:
        return worker_count.state_of(repo, cpu_topology()[1])
    except Exception as exc:
        _note_swallowed("_fleet_workers", exc)
        return None


def _workload(repo) -> dict | None:
    from graph_scale_dynamics.scheduling import work_groups
    try:
        return work_groups.reading(repo)
    except Exception as exc:
        _note_swallowed("_workload", exc)
        return None


def _published_dims(summary: dict) -> dict:
    return {key: value
            for key, value in _summary_dims(summary).items()}


_CHANNEL_ORDER: tuple[str, ...] = ("d_s", "d_V", "d_B", "d_w")


def _published_channels(summary: dict) -> list[dict]:
    refusals = (summary or {}).get("probe_refusals")
    refusals = refusals if isinstance(refusals, dict) else {}
    channels = []
    for stored in _CHANNEL_ORDER:
        statistic = (summary or {}).get(stored)
        statistic = statistic if isinstance(statistic, dict) else {}
        channels.append({
            "channel": stored,
            "stored_key": stored,
            "mean": statistic.get("mean"),
            "se": statistic.get("se"),
            "n_seeds": statistic.get("n_seeds"),
            "valid_fraction": (summary or {}).get(f"{stored}_valid_fraction"),
            "refusals": dict(refusals.get(stored) or {}),
        })
    return channels


def _ensemble_codes(repo, campaign_id: str) -> dict:
    ordinals: dict[str, dict] = {}
    for row in repo.conn.execute(
        "SELECT candidate_id,n,MIN(graph_ordinal) AS ordinal FROM jobs "
        "WHERE campaign_id=? AND kind='simulate' AND graph_ordinal IS NOT NULL "
        "GROUP BY candidate_id,n", (str(campaign_id),)
    ):
        ordinals.setdefault(str(row["candidate_id"]), {})[int(row["n"])] = int(row["ordinal"])
    return {cid: ensemble_code(by_n) for cid, by_n in ordinals.items()}


def _candidate_stability(phenotype, spec, rung_rows=None) -> dict | None:
    from graph_scale_dynamics.scheduling.base_block import (
        BASE_BLOCK_CONTRACT, base_sizes, extension_sizes)
    from graph_scale_dynamics.scheduling.limits import connectivity_floor
    declared = set(base_sizes(spec or {})) | set(extension_sizes(spec or {}))
    measured = any(int(r["n"]) in declared for r in rung_rows or [])
    if not (isinstance(phenotype, dict) and phenotype.get("contract") == BASE_BLOCK_CONTRACT) and not measured:
        return None
    return {"connectivity_floor": connectivity_floor(spec or {})}


def _ensemble_code_for(repo, campaign_id: str, candidate_id: str) -> str | None:
    by_n = {
        int(row["n"]): int(row["ordinal"])
        for row in repo.conn.execute(
            "SELECT n,MIN(graph_ordinal) AS ordinal FROM jobs "
            "WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "AND graph_ordinal IS NOT NULL GROUP BY n",
            (str(campaign_id), str(candidate_id)),
        )
    }
    return ensemble_code(by_n) if by_n else None


def _child_campaigns_with_generation(repo: Repo, parent_campaign: dict) -> list[dict]:
    rows = repo.child_campaigns(parent_campaign["campaign_id"])
    for row in rows:
        row["spec_generation"] = None
    return rows


def _proposal_mode(spec: dict) -> str:
    proposer = spec.get("proposer") or {}
    family_memory = proposer.get("family_memory") or {}
    return str(family_memory.get("mode", "off" if proposer == {} else "shadow"))


def normalize_base_path(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw == "/":
        return ""
    return "/" + raw.strip("/")


def json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def json_bytes(payload) -> bytes:
    return json.dumps(json_safe(payload), allow_nan=False, separators=(",", ":")).encode("utf-8")


def _scratch_alerts(repo) -> list[dict]:
    try:
        rows = repo.operational_alerts(active_only=True, limit=50)
    except Exception as exc:
        _note_swallowed("scratch_alerts", exc)
        return []
    return [public_row(row, "detail_json") for row in rows if str(row.get("source") or "") == "scratch"]


def public_row(row: dict, *private_keys: str) -> dict:
    hidden = set(private_keys)
    return {key: value for key, value in row.items() if key not in hidden}


def law_label(spec: dict) -> str:
    parts = []
    for term in spec.get("terms", []):
        op = OP_SHORT.get(term["op"], term["op"]).format(**term.get("params", {}))
        coeff = term["coeff"]
        scale = SCALE_SHORT.get(coeff["scale"], f"·N^{coeff.get('p', '?')}")
        parts.append(f"{coeff['c0']:+g}{scale} {op}")
    return "  ".join(parts) or "?"


def _age_seconds(utc: str) -> float:
    try:
        then = datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds()
    except (ValueError, TypeError):
        return 1e9


def _authoritative_dimension_point(candidate_id: str, entry: dict) -> dict | None:
    def latest_dimension(metric: str):
        latest = next((row.get(metric) for row in reversed(entry.get("rungs") or [])
                       if row.get(metric) is not None), None)
        if latest is not None:
            return round(float(latest), 3), "latest_rung"
        return None, None

    d_s_estimate, d_s_source = latest_dimension("d_s")
    d_h_estimate, d_h_source = latest_dimension("d_V")
    d_b_estimate, d_b_source = latest_dimension("d_B")
    d_w_estimate, d_w_source = latest_dimension("d_w")
    if d_s_estimate is None and d_h_estimate is None:
        return None
    return {
        "candidate_id": candidate_id,
        "d_s_estimate": d_s_estimate, "d_s_source": d_s_source,
        "d_v_estimate": d_h_estimate, "d_v_source": d_h_source,
        "d_b_estimate": d_b_estimate, "d_b_source": d_b_source,
        "d_w_estimate": d_w_estimate, "d_w_source": d_w_source,
    }


def _transitions_from_rungs(rungs: list[dict]) -> list[dict]:
    from graph_scale_dynamics.scaleflow.flow import transition_record
    ordered = sorted((r for r in rungs if isinstance(r.get("summary"), dict)), key=lambda r: int(r["n"]))
    out, previous = [], None
    for low, high in zip(ordered, ordered[1:], strict=False):
        previous = transition_record(int(low["n"]), low["summary"], int(high["n"]), high["summary"], previous)
        out.append({"n_from": int(low["n"]), "n_to": int(high["n"]), "record": previous})
    return out


def equilibration_rows(measurements: list[dict], policy: dict) -> list[dict]:
    floor = policy.get("min_effective_samples", 8)
    z_max = policy.get("equilibration_split_z", 3.0)
    by_n: dict[int, list] = {}
    for measurement in select_best_runs(measurements):
        by_n.setdefault(measurement["n"], []).append(measurement["metrics"])
    rows = []
    for n in sorted(by_n):
        certificates = [c for c in ((m.get("health") or {}).get("equilibration") for m in by_n[n]) if c]
        verdict = rung_certified(by_n[n])
        if not certificates and verdict["certified"] is None:
            rows.append({"n": n, "certified": None, "screen_passed": None})
            continue
        effectives = [c["effective_samples"] for c in certificates if c.get("effective_samples") is not None]
        z_values = [max(c["split"].values()) for c in certificates if c.get("split")]
        structural_values = [max(c["structural_split"].values()) for c in certificates if c.get("structural_split")]
        taus = [c["tau_int_sweeps"] for c in certificates if c.get("tau_int_sweeps") is not None]
        rows.append({
            "n": n, "seeds": len(by_n[n]),
            "sweeps": max((c.get("sweeps") or 0 for c in certificates), default=0),
            "multiplier": max((int(c.get("sweeps_multiplier", 1)) for c in certificates), default=1),
            "tau_int_sweeps": round(max(taus), 3) if taus else None,
            "effective_samples": round(min(effectives), 1) if effectives else None,
            "split_z": round(max(z_values), 2) if z_values else None,
            "split_methods": sorted({c.get("split_method") for c in certificates if c.get("split_method")}),
            "structural_delta_max": round(max(structural_values), 3) if structural_values else None,
            "floor": floor, "z_max": z_max,
            "screen_failures": verdict["failures"],
            "screen_passed": verdict["certified"], "certified": verdict["certified"]})
    return rows


def _cached_campaign_stats(repo: Repo, campaign_id: str, status: str) -> dict:
    now = __import__("time").monotonic()
    cached = _CAMPAIGN_STATS_CACHE.get(campaign_id)
    ttl = 15.0 if status == "active" else 3600.0
    if cached and cached[0] == status and now - cached[1] < ttl:
        return cached[2]
    stats = repo.campaign_stats(campaign_id)
    _CAMPAIGN_STATS_CACHE[campaign_id] = (status, now, stats)
    return stats


def _build_exploration_map(nodes: list[dict]) -> dict:
    if not nodes:
        return {"nodes": [], "roots": 0, "state_counts": {},
                "earliest_utc": None, "latest_utc": None}
    ordered = sorted(nodes, key=lambda row: (row.get("created_utc") or "", row["candidate_id"]))
    state_counts = dict(__import__("collections").Counter(row["state"] for row in ordered))
    roots = sum(1 for row in ordered if not row.get("lineage_parent")
                or row.get("lineage_parent") == row.get("candidate_id"))
    stamps = [row.get("created_utc") for row in ordered if row.get("created_utc")]
    stamps += [row.get("event_utc") for row in ordered if row.get("event_utc")]
    return {
        "nodes": ordered,
        "roots": roots,
        "state_counts": state_counts,
        "earliest_utc": min(stamps) if stamps else None,
        "latest_utc": max(stamps) if stamps else None,
    }


def _waiting_to_learn(repo, campaign_id) -> int:
    try:
        row = repo.conn.execute("SELECT sampled_utc,detail_json FROM service_heartbeats WHERE service LIKE "
                                "'controller%' ORDER BY sampled_utc DESC LIMIT 1").fetchone()
        if row is None or _age_seconds(row["sampled_utc"]) > 120:
            return 0
        passes = json.loads(row["detail_json"] or "{}").get("engine_passes") or {}
        return int(((passes.get(str(campaign_id)) or {}).get("decisions") or {}).get("pending:learning") or 0)
    except Exception as exc:
        _note_swallowed("_waiting_to_learn", exc)
        return 0


def _stranded_work_alerts(repo, campaign_id, analysis_version) -> list[dict]:
    reader = getattr(repo, "stranded_candidates", None)
    if not callable(reader):
        return []
    try:
        rows = reader(str(campaign_id), str(analysis_version), limit=500)
        learning = _waiting_to_learn(repo, campaign_id) if rows else 0
        behind = decision_backlog_alerts(decision_backlog(repo.conn, campaign_id) if rows else {},
                                         paused=repo.get_flag("paused") == "1", age_seconds=_age_seconds,
                                         learning=learning)
    except Exception as exc:
        _note_swallowed("_stranded_work_alerts", exc)
        return []
    return (behind + stranded_work_alerts(rows, _ensemble_codes(repo, campaign_id), _age_seconds, learning)
            if rows else [])


def _summary_classification(summary, limits) -> str | None:
    from graph_scale_dynamics.readmodel.rung_classification import classification_from_summary
    stored = (summary or {}).get("rung_terminal_classification")
    return stored or classification_from_summary(summary or {}, limits)


def _count_graphs_grown(counts: dict | None, spec: dict) -> None:
    if counts is not None:
        chains = chains_per_seed(spec)
        counts["graphs_grown"] = int(counts["graph_jobs_created"]) * chains
        counts["graphs_grown_last_hour"] = int(counts["graphs_finished_last_hour"]) * chains


def committing_jobs(repo: Repo) -> dict:
    found = {}
    for row in repo.conn.execute("SELECT service,sampled_utc,detail_json FROM service_heartbeats WHERE detail_json LIKE ?",
                                 ('%"phase": "committing"%',)):
        if _age_seconds(row["sampled_utc"]) > ALIVE_WITHIN_SECONDS:
            continue
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if detail.get("phase") == "committing" and detail.get("job"):
            found[str(row["service"])] = str(detail["job"])
    return found


def _phase(j: dict, committing: dict | None) -> dict:
    return {"phase": "committing"} if committing and committing.get(str(j.get("lease_owner"))) == str(
        j.get("job_id")) else {}


def _running_row(j: dict, lane: dict, duration_samples, campaign_row_spec, rungs, rung_medians,
                 committing: dict | None = None) -> dict:
    started = j.get("started_utc") or j.get("updated_utc")
    age = _age_seconds(started)
    before = float(lane.get("resumed_seconds") or 0.0)
    return {"n": int(j["n"]), "seed": None if j["sealed"] else j["seed"], "sealed": bool(j["sealed"]),
            "owner": j["lease_owner"], "stage": str(j.get("stage") or ""), **lane, **_phase(j, committing),
            "started_utc": started, "since_s": round(age, 1),
            "elapsed_s": round(age + before, 1),
            "eta": _eta.estimate_for_job(duration_samples, campaign_row_spec, j, age + before,
                                         own_by_rung=_eta.own_rung_seconds(rungs),
                                         population_median_by_rung=rung_medians)}


def build_fast_overview(repo: Repo, campaign_id: str) -> dict:
    started = time.monotonic()
    campaign = repo.campaign(campaign_id)
    if not campaign:
        return {"error": "unknown campaign"}
    spec = campaign["spec"]
    version = spec.get("analysis_version", ANALYSIS_VERSION)
    ladder = [int(n) for n in spec.get("ladder", [])]
    paused = repo.get_flag("paused") == "1"

    services_by_role: dict[str, dict] = {}
    for row in repo.conn.execute("SELECT service,pid,sampled_utc,detail_json FROM service_heartbeats ORDER BY service"):
        age = _age_seconds(row["sampled_utc"])
        if age > 120:
            continue
        name = str(row["service"])
        role = "executor" if name.startswith("executor-") else ("resource-governor" if name.startswith("resource-governor-") else name.rsplit("-", 1)[0])
        bucket = services_by_role.setdefault(role, {
            "role": role, "alive": 0, "total": 0, "pids": [],
            "heartbeat_utc": None, "heartbeat_age_seconds": None,
            "latest_event_utc": None, "latest_event_age_seconds": None, "last_event_topic": None, "last_message": None,
            "rss_bytes": 0, "cpu_percent_one_core": 0.0,
            "read_bytes_per_second": 0.0, "write_bytes_per_second": 0.0,
            "io_counters_available_pids": 0, "io_rate_ready_pids": 0,
        })
        bucket["total"] += 1
        if age < ALIVE_WITHIN_SECONDS:
            bucket["alive"] += 1
        pid = int(row["pid"] or 0)
        if pid > 0:
            bucket["pids"].append(pid)
            ps = _service_process_sample(pid)
            if ps.get("rss_bytes") is not None:
                bucket["rss_bytes"] += int(ps["rss_bytes"] or 0)
            if ps.get("io_counters_available"):
                bucket["io_counters_available_pids"] += 1
            if ps.get("io_rate_ready"):
                bucket["io_rate_ready_pids"] += 1
            for key in ("cpu_percent_one_core", "read_bytes_per_second", "write_bytes_per_second"):
                if ps.get(key) is not None:
                    bucket[key] += float(ps[key] or 0.0)
        if bucket["heartbeat_utc"] is None or str(row["sampled_utc"]) > str(bucket["heartbeat_utc"]):
            bucket["heartbeat_utc"] = row["sampled_utc"]
            bucket["heartbeat_age_seconds"] = round(age, 1)
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                detail = {"raw": row["detail_json"]}
            bucket["last_message"] = json.dumps(detail, sort_keys=True, separators=(",", ":"))

    for row in repo.conn.execute(
        "SELECT sc.service,e.created_utc,e.topic,e.payload_json FROM service_cursors sc "
        "LEFT JOIN events e ON e.event_id=sc.last_event_id ORDER BY sc.service"
    ):
        name = str(row["service"])
        role = "executor" if name.startswith("executor-") else ("resource-governor" if name.startswith("resource-governor-") else name.rsplit("-", 1)[0])
        bucket = services_by_role.get(role)
        if bucket is None or not row["created_utc"]:
            continue
        if bucket["latest_event_utc"] is None or str(row["created_utc"]) > str(bucket["latest_event_utc"]):
            bucket["latest_event_utc"] = row["created_utc"]
            bucket["latest_event_age_seconds"] = round(_age_seconds(row["created_utc"]), 1)
            bucket["last_event_topic"] = row["topic"]
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {"raw": row["payload_json"]}
            bucket["last_message"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    services = []
    for bucket in services_by_role.values():
        bucket["pids"] = sorted(set(bucket["pids"]))
        bucket["cpu_percent_one_core"] = round(float(bucket["cpu_percent_one_core"] or 0.0), 2)
        if bucket["io_rate_ready_pids"]:
            bucket["read_bytes_per_second"] = round(float(bucket["read_bytes_per_second"] or 0.0), 1)
            bucket["write_bytes_per_second"] = round(float(bucket["write_bytes_per_second"] or 0.0), 1)
        else:
            bucket["read_bytes_per_second"] = None
            bucket["write_bytes_per_second"] = None
        bucket["io_status"] = ("measured" if bucket["io_rate_ready_pids"] else
                               ("warming" if bucket["io_counters_available_pids"] else "unavailable"))
        bucket["state"] = "current" if bucket["alive"] else "stale"
        services.append(bucket)
    services.sort(key=lambda row: row["role"])

    allocation = repo.scheduler_snapshot() or {
        "total_slots": int(repo.get_flag("compute_total_slots", "1") or 1),
        "analysis_slots": 0, "simulation_slots": 0, "analysis_backlog": 0,
        "queued_simulations": 0, "leased_simulations": 0, "blocked_simulations": 0,
        "paused": paused,
    }
    total_slots = int(allocation.get("total_slots", 0) or 0)
    simulation_busy = int(allocation.get("leased_simulations", 0) or 0)
    analysis_busy = 0 if paused else int(repo.active_analysis_claims() or 0)
    active_slots = simulation_busy + analysis_busy
    physical_cores, logical_threads = cpu_topology()
    governor_capacity = _governor_capacity_snapshot(repo, campaign_id, total_slots)
    analysis_runnable = _analysis_runnable_snapshot(repo, campaign_id, version)
    compute_utilization = {
        "simulation_busy": simulation_busy,
        "simulation_eligible": int(allocation.get("simulation_slots", 0) or 0),
        "analysis_busy": analysis_busy,
        "analysis_eligible": int(allocation.get("analysis_slots", 0) or 0),
        "active_total": active_slots,
        "total_slots": total_slots,
        "scheduler_total_slots": total_slots,
        "governor_slot_limit": governor_capacity.get("governor_slot_limit"),
        "governor_target_slots": governor_capacity.get("target_slots"),
        "certified_safe_max_slots": governor_capacity.get("safe_max_slots"),
        "requested_max_slots": governor_capacity.get("requested_max_slots"),
        "governor_phase": governor_capacity.get("governor_phase"),
        "host_physical_cores": physical_cores,
        "host_logical_threads": logical_threads,
        "queued_simulations": int(allocation.get("queued_simulations", 0) or 0),
        "claimable_analyses": int(analysis_runnable.get("claimable", 0) or 0),
        "deferred_analyses": int(analysis_runnable.get("deferred", 0) or 0),
        "blocked_simulations": int(allocation.get("blocked_simulations", 0) or 0),
        "idle_slots": max(0, total_slots - active_slots),
        "scheduler_snapshot_inconsistent": active_slots > total_slots,
        "claim_lock_waiters": 0,
        "memory_reservation": {"total": 0, "budget": 0, "percent": 0},
    }

    job_counts: dict[str, dict[str, int]] = {}
    for row in repo.conn.execute(
        "SELECT campaign_id,status,COUNT(*) AS n FROM jobs GROUP BY campaign_id,status"
    ):
        job_counts.setdefault(str(row["campaign_id"]), {})[str(row["status"])] = int(row["n"] or 0)
    runtime_counts: dict[str, dict[str, int]] = {}
    compute_seconds: dict[str, dict] = {}
    try:
        compute_seconds = campaign_manager.compute_seconds(repo)
    except Exception as exc:
        _note_swallowed("build_fast_overview", exc)
        compute_seconds = {}

    for row in repo.conn.execute(
        "SELECT jobs.campaign_id,"
        "COUNT(*) FILTER (WHERE kind='simulate') AS graph_jobs_created,"
        "COALESCE(SUM(attempts) FILTER (WHERE kind='simulate'),0) AS simulation_leases,"
        "COALESCE(SUM(attempts) FILTER (WHERE kind='analyze'),0) AS analysis_leases,"
        "COALESCE(MAX(graph_ordinal),0) AS highest_graph_ordinal,"
        "COUNT(*) FILTER (WHERE kind='simulate' AND status='done' "
        "AND result_artifact IS NOT NULL) AS completed_graph_realizations,"
        "COUNT(*) FILTER (WHERE kind='simulate' AND status='done' "
        "AND result_artifact IS NOT NULL AND updated_utc>=?) AS graphs_finished_last_hour "
        "FROM jobs GROUP BY jobs.campaign_id",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600.0)),)
    ):
        created = int(row["graph_jobs_created"] or 0)
        highest = int(row["highest_graph_ordinal"] or 0)
        runtime_counts[str(row["campaign_id"])] = {
            "graph_jobs_created": created,
            "graphs_finished_last_hour": int(row["graphs_finished_last_hour"] or 0),
            "compute": compute_seconds.get(str(row["campaign_id"]), {
                "simulation_core_seconds": 0.0, "analysis_core_seconds": 0.0,
                "core_seconds": 0.0, "unsuccessful_core_seconds": 0.0}),
            "highest_graph_ordinal": highest,
            "burned_graph_ordinals": max(0, highest - created),
            "simulation_leases": int(row["simulation_leases"] or 0),
            "analysis_leases": int(row["analysis_leases"] or 0),
            "completed_graph_realizations": int(row["completed_graph_realizations"] or 0),
        }
    for owner, bucket in runtime_counts.items():
        bucket.update(_execution_counts(repo).get(owner) or {"simulation_executions": 0})
        bucket["claims_without_execution"] = max(
            0, int(bucket.get("simulation_leases", 0))
            - int(bucket.get("simulation_executions", 0))
        )

    candidate_counts = {
        str(row["campaign_id"]): int(row["n"] or 0)
        for row in repo.conn.execute("SELECT campaign_id,COUNT(*) AS n FROM campaign_candidates GROUP BY campaign_id")
    }
    analysis_counts: dict[str, dict[str, int]] = {}
    for row in repo.conn.execute(
        "SELECT campaign_id,status,COUNT(*) AS n FROM analysis_queue GROUP BY campaign_id,status"
    ):
        analysis_counts.setdefault(str(row["campaign_id"]), {})[str(row["status"])] = int(row["n"] or 0)

    campaigns = []
    for row in repo.conn.execute(
        "SELECT campaign_id,status,created_utc,workers_target,spec_json,campaign_role,parent_campaign_id "
        "FROM campaigns ORDER BY created_utc DESC"
    ):
        cid = str(row["campaign_id"])
        cspec = json.loads(row["spec_json"])
        _count_graphs_grown(runtime_counts.get(cid), cspec)
        campaigns.append({
            "campaign_id": cid, "status": row["status"], "created_utc": row["created_utc"],
            "workers_target": row["workers_target"], "mode": cspec.get("mode", "bounded"),
            "name": cspec.get("name"), "campaign_role": row.get("campaign_role") if hasattr(row, 'get') else row["campaign_role"],
            "parent_campaign_id": row["parent_campaign_id"], "channel": None,
            "candidates": candidate_counts.get(cid, 0),
            "job_counts": job_counts.get(cid, {}), "analysis_counts": analysis_counts.get(cid, {}),
            "runtime_counts": runtime_counts.get(cid, {"graph_jobs_created": 0, "graphs_finished_last_hour": 0,
                              "highest_graph_ordinal": 0, "burned_graph_ordinals": 0,
                              "simulation_leases": 0, "analysis_leases": 0,
                              "completed_graph_realizations": 0}),
            "analysis_retrying": 0, "compute_seconds": None, "last_activity_utc": row["created_utc"],
            "cap_blocked": False, "spec_generation": None,
        })

    working_ids = live_work_candidate_ids(repo, campaign_id)
    rows_by_id: dict = {}
    columns = ("SELECT c.candidate_id,c.spec_json,c.dynamics,c.complexity,"
               "c.lineage_parent,c.state,c.state_reason,c.created_utc,c.updated_utc "
               "FROM candidates c WHERE c.campaign_id=? ")
    if working_ids:
        placeholders = ",".join("?" for _ in working_ids)
        for row in repo.conn.execute(
                columns + f"AND c.candidate_id IN ({placeholders})",
                (str(campaign_id), *working_ids)).fetchall():
            rows_by_id[row["candidate_id"]] = row
    for row in repo.conn.execute(
            columns + f"AND c.state NOT IN ({','.join('?' for _ in TERMINAL_CANDIDATE_STATES)}) "
            "ORDER BY c.updated_utc DESC LIMIT 96",
            (str(campaign_id), *sorted(TERMINAL_CANDIDATE_STATES))).fetchall():
        rows_by_id.setdefault(row["candidate_id"], row)
    active_rows = list(rows_by_id.values())[:192]
    try:
        duration_samples: dict = repo.rung_attempt_durations(str(campaign_id))
    except Exception as exc:
        _note_swallowed("build_fast_overview", exc)
        duration_samples = {}
    proposed, active = [], []
    for row in active_rows:
        entry = {
            "candidate_id": row["candidate_id"], "state": row["state"], "state_reason": row["state_reason"],
            "law": law_label(json.loads(row["spec_json"])), "terms": (json.loads(row["spec_json"]) or {}).get("terms") or [],
            "complexity": int(row["complexity"] or 0), "lineage_parent": row["lineage_parent"], "created_utc": row["created_utc"], "updated_utc": row["updated_utc"],
            "rungs": [], "running": [], "probing": [], "queued": [], "upcoming_rungs": ladder[:1],
            "largest_n": None, "measured_rungs": 0,
        }
        if row["state"] == "PROPOSED":
            proposed.append(entry)
        else:
            active.append(entry)

    _pushed_as(repo, spec, active)
    live_ids = [e["candidate_id"] for e in active]
    if live_ids:
        placeholders = ",".join("?" for _ in live_ids)
        rows = repo.conn.execute(
            f"SELECT candidate_id,n FROM rung_summaries WHERE campaign_id=? AND analysis_version=? "
            f"AND candidate_id IN ({placeholders}) ORDER BY candidate_id,n",
            (str(campaign_id), version, *live_ids),
        ).fetchall()
        by_id = {e["candidate_id"]: e for e in active}
        codes = _ensemble_codes(repo, campaign_id)
        for entry in active:
            entry["ensemble_code"] = codes.get(str(entry["candidate_id"]))
        timing = repo.dashboard_live_candidate_timing(str(campaign_id), live_ids)
        rung_spend, rung_medians = timing["rung_spend"], _eta.population_median_by_rung(timing["rung_spend"])
        compute_by_id = timing.get("compute_by_candidate") or {}
        campaign_row_spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
        for rr in rows:
            by_id[rr["candidate_id"]]["rungs"].append(
                {"n": int(rr["n"]),
                 "elapsed_s": round(rung_spend.get((str(rr["candidate_id"]), int(rr["n"])), 0.0), 1)}
            )
        current_by_id = timing["current_by_candidate"]
        committing = committing_jobs(repo)
        try:
            terminal_by_id = repo.dashboard_rung_job_states(str(campaign_id), live_ids)
        except Exception as exc:
            _note_swallowed("build_fast_overview", exc)
            terminal_by_id = {}
        analysis_by_id: dict[str, list[dict]] = {}
        try:
            for ar in repo.conn.execute(
                f"SELECT candidate_id,n,seed,status,next_attempt_utc,error,error_class,attempts,"
                f"memory_reservation_bytes,updated_utc FROM analysis_queue WHERE campaign_id=? "
                f"AND analysis_version=? AND candidate_id IN ({placeholders}) "
                f"AND status IN ('queued','leased')",
                (str(campaign_id), version, *live_ids),
            ).fetchall():
                analysis_by_id.setdefault(str(ar["candidate_id"]), []).append(dict(ar))
        except Exception as exc:
            _note_swallowed("build_fast_overview", exc)
            analysis_by_id = {}
        for entry in active:
            measured = [int(r["n"]) for r in entry["rungs"]]
            jobs = current_by_id.get(entry["candidate_id"], [])
            entry["running"] = [_running_row(j, _live.lane_and_budget(j, _live.base_sizes_set(spec, ladder)),
                                             duration_samples, campaign_row_spec, entry["rungs"], rung_medians,
                                             committing)
                                for j in jobs if j["status"] == "leased"]
            entry["queued"] = [{
                "n": int(j["n"]), "seed": None if j["sealed"] else j["seed"],
                "sealed": bool(j["sealed"]),
            } for j in jobs if j["status"] == "queued"]
            entry["probing"] = _live.probe_rows(analysis_by_id.get(entry["candidate_id"]),
                                                _live.base_sizes_set(spec, ladder))
            entry["compute_seconds"] = round(compute_by_id.get(entry["candidate_id"], 0.0), 1)
            known = set(measured + [int(j["n"]) for j in jobs])
            entry["largest_n"] = max(known) if known else None
            entry["measured_rungs"] = len(measured)
            entry["upcoming_rungs"] = [n for n in ladder if n not in known][:1]
            measured_ns = set(measured)
            standings = rung_standings(
                ladder=sorted(set(int(n) for n in ladder) | known),
                measured_ns=measured_ns,
                jobs=terminal_by_id.get(entry["candidate_id"], []) or [
                    {"n": int(j["n"]), "status": j["status"], "error": j.get("error")}
                    for j in jobs],
                largest_n=entry["largest_n"])
            for _row in standings:
                if _row.get("since_utc"):
                    _row["since_s"] = round(_age_seconds(_row.pop("since_utc")), 1)
            entry["ladder"] = standings
            entry["waiting_reason"] = waiting_reason(standings)
            pending = [row["n"] for row in standings if row["standing"] == "next"]
            if entry["waiting_reason"] is not None:
                pass
            elif pending:
                dead = [j for j in jobs if int(j["n"]) == int(pending[0])
                        and j["status"] in ("failed", "cancelled")
                        and not j.get("result_artifact")]
                if dead:
                    worst = max(dead, key=lambda j: int(j.get("attempts") or 0))
                    entry["waiting_reason"] = (
                        f"N={pending[0]} jobs exist but are {worst['status']} "
                        f"(attempts {worst.get('attempts')}) with no result: "
                        f"{str(worst.get('error') or 'no error recorded')[:160]}; "
                        "the candidate is suspended and the lifecycle reconciler "
                        "must park or requeue it"
                    )
                else:
                    entry["waiting_reason"] = (
                        f"N={pending[0]} is the next rung and has not been admitted yet; "
                        "waiting on scheduler admission, not on compute"
                    )
            else:
                pending_analyses = analysis_by_id.get(str(entry["candidate_id"])) or []
                entry["analysing"] = sum(1 for a in pending_analyses if a.get("status") == "leased")
                if pending_analyses:
                    top = max(pending_analyses, key=lambda a: int(a.get("n") or 0))
                    if top.get("status") == "leased":
                        entry["waiting_reason"] = (
                            f"N={top.get('n')} analysis is running; the decision engine decides "
                            "when its result lands")
                    elif top.get("next_attempt_utc"):
                        entry["waiting_reason"] = (
                            f"N={top.get('n')} analysis deferred until {top.get('next_attempt_utc')} "
                            f"({top.get('error_class') or 'backoff'}: "
                            f"{str(top.get('error') or 'no reason recorded')[:140]}); "
                            "memory admission, not the decision engine, is the constraint")
                    else:
                        entry["waiting_reason"] = (
                            f"N={top.get('n')} analysis queued and claimable; waiting on an "
                            "analysis slot, not on the decision engine")
                    entry["pending_analysis"] = {
                        "n": top.get("n"), "status": top.get("status"),
                        "next_attempt_utc": top.get("next_attempt_utc"),
                        "error_class": top.get("error_class"), "attempts": top.get("attempts"),
                    }
                else:
                    entry["waiting_reason"] = (
                        "every ladder rung has a result; waiting on the decision engine's next decision"
                    )

    dimension_nodes = []
    for entry in active:
        node = _authoritative_dimension_point(entry["candidate_id"], entry)
        if node is not None:
            dimension_nodes.append(node)

    aq = analysis_counts.get(str(campaign_id), {})
    analysis_queue = {"counts": aq, "retrying": 0}
    objective = spec.get("objective")
    provenance = {
        "parent_campaign_id": campaign.get("parent_campaign_id"),
    }
    resources = host_snapshot()
    try:
        memory_reservations, admission = recorded_lease_reservations(repo.conn), admission_headroom(repo.conn)
        memory_reservations.update(budget=admission["budget_bytes"], admission=admission,
                                   deferred_simulations=memory_deferred_simulations(repo.conn),
                                   room=memory_room(repo.conn, admission))
        memory_reservations["percent"] = round(100.0 * float(memory_reservations.get("total") or 0.0)
                                               / max(1.0, float(admission["budget_bytes"] or 0.0)), 1)
    except Exception as exc:
        _note_swallowed("build_fast_overview", exc)
        memory_reservations = {"total": 0, "budget": 0, "percent": 0.0}
    compute_utilization["memory_reservation"] = memory_reservations
    operational_alerts = _stranded_work_alerts(repo, campaign_id, version) + _scratch_alerts(repo)
    stranded = next((a for a in operational_alerts if a.get("code") == "STRANDED_SCIENTIFIC_WORK"), None)
    queued_simulations = int(compute_utilization.get("queued_simulations", 0) or 0)
    queued_analyses = int(analysis_runnable.get("claimable", 0) or 0)
    deferred_analyses = int(analysis_runnable.get("deferred", 0) or 0)
    blocked_simulations = int(compute_utilization.get("blocked_simulations", 0) or 0)
    idle_slots = int(compute_utilization.get("idle_slots", 0) or 0)
    nonterminal_observed = len(active_rows)
    stranded_count = int((stranded or {}).get("stranded", 0) or 0)
    iowait = _cpu_iowait_percent()

    service_read = sum(float(row.get("read_bytes_per_second") or 0.0) for row in services
                       if row.get("read_bytes_per_second") is not None)
    service_write = sum(float(row.get("write_bytes_per_second") or 0.0) for row in services
                        if row.get("write_bytes_per_second") is not None)
    database_io = _database_io_snapshot(repo)
    database_read = float(database_io.get("read_bytes_per_second") or 0.0)
    database_write = float(database_io.get("write_bytes_per_second") or 0.0)
    host_read = resources.get("disk_read_bytes_per_second")
    host_write = resources.get("disk_write_bytes_per_second")
    attributed_read = service_read + database_read
    attributed_write = service_write + database_write
    io_summary = {
        "contract": "gsd-live-io-attribution-2",
        "host_read_bytes_per_second": host_read,
        "host_write_bytes_per_second": host_write,
        "tracked_service_read_bytes_per_second": round(service_read, 1),
        "tracked_service_write_bytes_per_second": round(service_write, 1),
        "database": database_io,
        "database_read_bytes_per_second": database_io.get("read_bytes_per_second"),
        "database_write_bytes_per_second": database_io.get("write_bytes_per_second"),
        "unattributed_read_bytes_per_second": None if host_read is None else round(max(0.0, float(host_read) - attributed_read), 1),
        "unattributed_write_bytes_per_second": None if host_write is None else round(max(0.0, float(host_write) - attributed_write), 1),
        "cpu_iowait_percent": iowait,
        "interpretation": (
            "Host rates are physical-device traffic. Graph Scale Dynamics services and PostgreSQL are sampled separately from /proc; "
            "the remainder is kernel/filesystem writeback, unrelated processes, or sampling skew. tmpfs activity does not count as physical disk I/O."
        ),
    }
    try:
        work_supply = campaign_manager.work_supply(repo)
    except Exception as exc:
        _note_swallowed("capacity_work_supply", exc)
        work_supply = None
    pressure_state, pressure_severity, pressure_explanation = _capacity_diagnosis(
        paused=paused, resources=resources, active_slots=active_slots,
        scheduler_slots=total_slots, runnable_simulations=queued_simulations,
        runnable_analyses=queued_analyses, blocked_simulations=blocked_simulations,
        deferred_analyses=deferred_analyses,
        memory_deferred_analyses=int(analysis_runnable.get("memory_deferred", 0) or 0),
        stranded_nonterminal=stranded_count, nonterminal_observed=nonterminal_observed,
        governor=governor_capacity,
        memory_reservation_percent=float(memory_reservations.get("percent") or 0.0),
        cpu_iowait_percent=iowait,
        scratch_percent=_scratch_percent_of_host(resources),
        admission=memory_reservations.get("admission"),
        deferred_simulations=int(memory_reservations.get("deferred_simulations") or 0),
        supply=work_supply, one_worker_per_core=_one_worker_per_core(repo, total_slots, physical_cores, logical_threads),
        room=memory_reservations.get("room"),
    )
    operational_bottleneck = {
        "contract": "gsd-capacity-diagnosis-live-2",
        "state": pressure_state,
        "severity": pressure_severity,
        "explanation": pressure_explanation,
        "governor": governor_capacity, "memory_room": memory_reservations.get("room"),
        "evidence": {
            "cpu_percent": resources.get("cpu_percent"),
            "cpu_iowait_percent": iowait,
            "memory_load_percent": resources.get("memory_load_percent"),
            "memory_reservation_percent": memory_reservations.get("percent"),
            "total_slots": total_slots,
            "active_slots": active_slots,
            "idle_slots": idle_slots,
            "simulation_busy": simulation_busy,
            "analysis_busy": analysis_busy,
            "queued_simulations": queued_simulations,
            "claimable_analyses": queued_analyses,
            "deferred_analyses": deferred_analyses,
            "blocked_simulations": blocked_simulations,
            "stranded_nonterminal_candidates": stranded_count,
            "nonterminal_candidates_observed": nonterminal_observed,
            "disk_read_bytes_per_second": host_read,
            "disk_write_bytes_per_second": host_write,
        },
        "io_bottleneck_proven": pressure_state == "DISK_IO_LIMITED",
        "note": "Disk throughput alone is not treated as proof of an I/O bottleneck; runnable work, spare scheduler capacity, and measured I/O stall evidence must agree.",
    }

    rung_distribution = rung_distribution_for(repo, campaign_id, duration_samples, spec)

    elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
    return {
        "rung_distribution": rung_distribution,
        "campaign_id": str(campaign_id), "status": campaign.get("status", "active"),
        "mode": spec.get("mode", "bounded"), "name": spec.get("name"), "objective": objective,
        "versions": {"build": BUILD_NUMBER, "build_id": runtime_fingerprint()[:12], "engine": ENGINE_VERSION,
                     "analysis": version, "policy": RULE_VERSION, "environment_id": environment_fingerprint()[:12]},
        "campaign_provenance": provenance, "benchmark_state": "not_recorded", "benchmark_passed": True,
        "paused": paused, "analysis_backlog": int(aq.get("queued", 0) or 0), "analysis_queue": analysis_queue,
        "services": services, "compute_utilization": compute_utilization,
        "fleet_workers": _fleet_workers(repo), "workload": _workload(repo), "fleet_mode": _fleet_mode(repo),
        "runtime_counts": runtime_counts.get(str(campaign_id), {"graph_jobs_created": 0, "graphs_finished_last_hour": 0,
                              "highest_graph_ordinal": 0, "burned_graph_ordinals": 0,
                              "simulation_leases": 0, "analysis_leases": 0,
                              "completed_graph_realizations": 0}),
        "database_activity": None, "system_resources": resources,
        "io_summary": io_summary, "operational_bottleneck": operational_bottleneck,
        "operational_alerts": operational_alerts,
        "campaigns": campaigns, "child_campaigns": [], "archive": None, "ladder": ladder,
        "ladder_runtime": [], "dimension_model": "uncapped_radius_scaling", "proposal_intelligence": None,
        "proposed": proposed, "active": active, "past": [],
        "dimension_points": dimension_nodes,
        "dimension_landscape": {"version": "live-fast-summary-2", "exposure": {"opportunities": None}, "bins": [], "authoritative_endpoint": True},
        "exploration_map": {"included": False, "available_count": candidate_counts.get(str(campaign_id), 0), "nodes": []},
        "past_research": {"included": False, "available_count": sum(
            int(row["n"] or 0) for row in repo.conn.execute(
                "SELECT COUNT(*) AS n FROM campaign_candidates WHERE campaign_id=? AND state IN "
                f"({','.join('?' for _ in TERMINAL_CANDIDATE_STATES)})",
                (str(campaign_id), *sorted(TERMINAL_CANDIDATE_STATES))
            ).fetchall())},
        "dashboard_sections": {"exploration_map": {"mode": "lazy", "included": False},
                               "past_research": {"mode": "lazy", "included": False}},
        "dashboard_response": {"build_ms": elapsed_ms, "stale": False,
                               "contract": "gsd-dashboard-fast-summary-1"},
    }


def build_overview(repo: Repo, campaign_id: str, *,
                   include_exploration: bool = True,
                   include_past: bool = True) -> dict:
    campaign = repo.campaign(campaign_id)
    if not campaign:
        return {"error": "unknown campaign"}
    spec = campaign["spec"]
    ladder = spec.get("ladder", [])
    declared_max_n = max(ladder) if ladder else 0
    budget_max_n = spec.get("budgets", {}).get("max_n", declared_max_n)
    extension = rung_extension_config(spec)
    configured_hard_fraction, effective_hard = effective_hard_fraction(spec, n=None)
    extension["configured_hard_single_job_fraction_total"] = configured_hard_fraction
    extension["hard_single_job_fraction_total"] = effective_hard
    unbounded_by_static_n = extension_enabled(spec)
    if unbounded_by_static_n:
        extension["enabled"] = True
    max_n = declared_max_n if unbounded_by_static_n else budget_max_n
    dimension_model = "uncapped_radius_scaling"
    version = spec.get("analysis_version", ANALYSIS_VERSION)
    job_snapshot = repo.dashboard_job_snapshot(campaign_id)
    job_counts = job_snapshot["counts"]
    jobs_by_candidate = job_snapshot["current_by_candidate"]
    committing = committing_jobs(repo)
    roles: dict[str, dict] = {}
    for row in repo.conn.execute("SELECT * FROM service_heartbeats ORDER BY service"):
        age = _age_seconds(row["sampled_utc"])
        if age > 60:
            continue
        service_name = row["service"]
        role = "executor" if service_name.startswith("executor-") else service_name.rsplit("-", 1)[0]
        bucket = roles.setdefault(role, {"role": role, "alive": 0, "total": 0})
        bucket["total"] += 1
        detail = json.loads(row["detail_json"] or "{}")
        if age < 40:
            bucket["alive"] += 1
        if role == "executor":
            task_role = detail.get("role", "idle")
            bucket[task_role] = bucket.get(task_role, 0) + 1
            bucket["worked"] = bucket.get("worked", 0) + int(bool(detail.get("worked")))
    services = sorted(roles.values(), key=lambda r: r["role"])
    paused = repo.get_flag("paused") == "1"
    allocation = repo.scheduler_snapshot() or {
        "total_slots": int(repo.get_flag("compute_total_slots", "1") or 1),
        "analysis_slots": 0, "simulation_slots": 0, "analysis_backlog": 0,
        "queued_simulations": 0, "leased_simulations": 0,
        "blocked_simulations": 0, "paused": paused,
    }
    total_slots = int(allocation["total_slots"])
    simulation_busy = int(allocation.get("leased_simulations", 0))
    analysis_busy = repo.active_analysis_claims()
    physical_cores, logical_threads = cpu_topology()
    compute_utilization = {
        "simulation_busy": simulation_busy,
        "simulation_eligible": int(allocation["simulation_slots"]),
        "analysis_busy": analysis_busy,
        "analysis_eligible": int(allocation["analysis_slots"]),
        "idle_slots": max(0, total_slots - simulation_busy - analysis_busy),
        "blocked_simulations": int(allocation.get("blocked_simulations", 0)),
        "queued_simulations": int(allocation.get("queued_simulations", 0)),
        "total_slots": total_slots,
        "host_physical_cores": physical_cores,
        "host_logical_threads": logical_threads,
        "configured_monitor_ceiling": round(
            configured_monitor_ceiling(total_slots, logical_threads), 1
        ),
        "below_physical_core_count": total_slots < physical_cores,
    }
    database_activity = repo.database_activity()
    claim_lock_waiters = sum(
        int(row.get("count", 0)) for row in database_activity.get("groups", [])
        if row.get("wait_type") == "Lock" and row.get("wait_event") == "advisory"
    )
    if not claim_lock_waiters:
        claim_lock_waiters = sum(
            int(row.get("count", 0)) for row in database_activity.get("groups", [])
            if str(row.get("wait_event", "")).lower() == "advisory"
        )
    memory_reservations = recorded_lease_reservations(repo.conn)
    memory_reservations["budget"] = aggregate_launch_budget_bytes(repo.conn)
    memory_reservations["percent"] = round(
        100.0 * memory_reservations["total"] / max(1, memory_reservations["budget"]), 1
    )
    compute_utilization["claim_lock_waiters"] = claim_lock_waiters
    compute_utilization["memory_reservation"] = memory_reservations
    benchmark = repo.benchmark(version)
    analysis_queue = repo.analysis_queue_status(campaign_id, version)
    candidates = repo.candidates(campaign_id)
    rung_rows = repo.campaign_rung_summaries(campaign_id, version)
    latest_decisions = repo.latest_engine_decisions(campaign_id)
    proposal_rows = {row["candidate_id"]: row for row in repo.proposal_assessments(campaign_id)}
    proposal_exposure_rows = repo.proposal_exposures(campaign_id)
    proposed, active, past = [], [], []
    exploration_codes = _ensemble_codes(repo, campaign_id) if include_exploration else {}
    exploration_numbers, shared = identity_context(repo, campaign_id, include_exploration)
    exploration_nodes: list[dict] = []
    dimension_nodes: list[dict] = []
    terminal = TERMINAL_CANDIDATE_STATES
    for candidate in candidates:
        cid = candidate["candidate_id"]
        entry = {"candidate_id": cid, "state": candidate["state"],
                 "unfiltered": bool(((proposal_rows.get(cid) or {}).get("assessment") or {})
                                    .get("unfiltered")),
                 "state_reason": candidate["state_reason"],
                 "law": law_label(candidate["spec"]),
                 "terms": (candidate.get("spec") or {}).get("terms") or [],
                 "visual_grammar_version": "hamiltonian-visual-1",
                 "complexity": candidate["complexity"],
                 "lineage_parent": candidate["lineage_parent"],
                 "created_utc": candidate.get("created_utc"),
                 "updated_utc": candidate.get("updated_utc")}
        proposal = proposal_rows.get(cid)
        if proposal:
            entry["proposal_assessment"] = proposal["assessment"] | {
                "mode": proposal["mode"], "source": proposal["source"]
            }
        if candidate["state"] == "PROPOSED":
            entry["largest_n"] = None
            entry["measured_rungs"] = 0
            event_stamps = [candidate.get("updated_utc"), candidate.get("created_utc")]
            event_stamps = [stamp for stamp in event_stamps if stamp]
            entry["event_utc"] = max(event_stamps) if event_stamps else None
            if include_exploration:
                exploration_nodes.append({
                    "candidate_id": cid,
                    "ensemble_code": exploration_codes.get(str(cid)),
                    "candidate_number": exploration_numbers.get(str(cid)), **node_identity(cid, candidate["spec"], shared, campaign_id),
                    "lineage_parent": candidate["lineage_parent"],
                    "law": entry["law"],
                    "terms": entry.get("terms") or [],
                    "state": candidate["state"],
                    "state_reason": candidate.get("state_reason"),
                    "coupling_stratum": coupling_stratum(candidate["spec"]),
                    "scaling_profile": scaling_profile(candidate["spec"]),
                    "coefficient_scales": sorted({str((term.get("coeff") or {}).get("scale") or "one") for term in (candidate["spec"].get("terms") or [])}),
                    "term_operators": sorted({str(term.get("op") or "unknown") for term in (candidate["spec"].get("terms") or [])}),
                    "created_utc": entry.get("created_utc"),
                    "event_utc": entry.get("event_utc"),
                    "complexity": candidate["complexity"],
                    "largest_n": None,
                    "measured_rungs": 0,
                    "d_s_estimate": None,
                    "d_s_source": None,
                    "status_group": "proposed",
                })
            proposed.append(entry)
            continue
        rungs = rung_rows.get(cid, [])
        entry["rungs"] = [{"n": r["n"]} | _published_dims(r["summary"]) for r in rungs]
        measured = [r["n"] for r in rungs]
        from graph_scale_dynamics.scaleflow.probes import LIMIT_TERMINALS as _LIMITS
        campaign_limits = (spec or {}).get("limits") or {}
        entry["probes_valid"] = sum(
            1 for row in entry["rungs"] for key in ("d_s", "d_V", "d_B", "d_w") if row.get(key) is not None)
        entry["limit_hits"] = sorted({
            int(r["n"]) for r in rungs
            if str(_summary_classification(r.get("summary"), campaign_limits) or "") in _LIMITS})
        decision = latest_decisions.get(str(cid))
        if decision:
            entry["engine_decision"] = decision
        candidate_jobs = jobs_by_candidate.get(cid, [])
        running = [{"n": j["n"], "seed": None if j["sealed"] else j["seed"],
                    "sealed": bool(j["sealed"]), "owner": j["lease_owner"], **_phase(j, committing),
                    "started_utc": j.get("started_utc") or j.get("updated_utc"),
                    "since_s": round(_age_seconds(j.get("started_utc") or j.get("updated_utc")), 1)}
                   for j in candidate_jobs if j["status"] == "leased"]
        queued = [{"n": j["n"], "seed": None if j["sealed"] else j["seed"],
                   "sealed": bool(j["sealed"])}
                  for j in candidate_jobs if j["status"] == "queued"]
        known_rungs = set(measured + [j["n"] for j in candidate_jobs])
        horizon = max(known_rungs, default=0)
        entry["running"] = running
        entry["queued"] = queued
        upcoming = [n for n in ladder if n > horizon and (unbounded_by_static_n or n <= max_n)]
        if not upcoming and candidate["state"] not in terminal:
            dynamic_next = next_unmeasured_rung(spec, known_rungs)
            if dynamic_next is not None and dynamic_next > horizon:
                upcoming = [dynamic_next]
        entry["upcoming_rungs"] = upcoming
        entry["largest_n"] = horizon or None
        entry["measured_rungs"] = len(measured)
        event_stamps = [candidate.get("updated_utc"), candidate.get("created_utc")]
        if decision:
            event_stamps.append(decision.get("created_utc"))
        event_stamps = [stamp for stamp in event_stamps if stamp]
        entry["event_utc"] = max(event_stamps) if event_stamps else None
        dimension_node = _authoritative_dimension_point(cid, entry)
        d_s_estimate = None if dimension_node is None else dimension_node.get("d_s_estimate")
        d_s_source = None if dimension_node is None else dimension_node.get("d_s_source")
        if dimension_node is not None:
            dimension_nodes.append(dimension_node)
        if include_exploration:
            exploration_nodes.append({
                "candidate_id": cid,
                "ensemble_code": exploration_codes.get(str(cid)),
                "candidate_number": exploration_numbers.get(str(cid)), **node_identity(cid, candidate["spec"], shared, campaign_id),
                "lineage_parent": candidate["lineage_parent"],
                "law": entry["law"],
                "terms": entry.get("terms") or [],
                "state": candidate["state"],
                "state_reason": candidate.get("state_reason"),
                "status": law_status.of_row({"state": candidate["state"], "state_reason": candidate.get("state_reason"),
                                             "largest_n": entry.get("largest_n")}),
                "coupling_stratum": coupling_stratum(candidate["spec"]),
                "scaling_profile": scaling_profile(candidate["spec"]),
                "coefficient_scales": sorted({str((term.get("coeff") or {}).get("scale") or "one") for term in (candidate["spec"].get("terms") or [])}),
                "term_operators": sorted({str(term.get("op") or "unknown") for term in (candidate["spec"].get("terms") or [])}),
                "created_utc": entry.get("created_utc"),
                "event_utc": entry.get("event_utc"),
                "complexity": candidate["complexity"],
                "largest_n": entry.get("largest_n"),
                "measured_rungs": entry.get("measured_rungs"),
                "d_s_estimate": d_s_estimate,
                "d_s_source": d_s_source,
                "status_group": ("past" if candidate["state"] in terminal else "active"),
            })
        if candidate["state"] in terminal:
            if include_past:
                past.append(entry)
        else:
            active.append(entry)
    _pushed_as(repo, campaign.get("spec") or {}, active)
    child_campaigns = _child_campaigns_with_generation(repo, campaign)
    child_generation = {
        row["child_campaign_id"]: row.get("spec_generation") for row in child_campaigns
    }
    campaigns = []
    for r in repo.conn.execute(
            "SELECT campaign_id,status,created_utc,workers_target,spec_json,campaign_role,"
            "parent_campaign_id,campaign_series_id,science_contract_hash,search_policy_hash,"
            "resource_policy_hash,created_build FROM campaigns ORDER BY created_utc DESC"):
        stats = _cached_campaign_stats(repo, r["campaign_id"], r["status"])
        campaign_spec = json.loads(r["spec_json"])
        link = repo.campaign_link(r["campaign_id"])
        queued_count = int((stats.get("job_counts") or {}).get("queued", 0))
        target = r["workers_target"]
        campaigns.append({"campaign_id": r["campaign_id"], "status": r["status"],
                          "created_utc": r["created_utc"], "workers_target": target,
                          "mode": campaign_spec.get("mode", "bounded"),
                          "name": campaign_spec.get("name"),
                          "campaign_role": r.get("campaign_role") or "discovery",
                          "parent_campaign_id": r.get("parent_campaign_id") or (link and link["parent_campaign_id"]),
                          "campaign_series_id": r.get("campaign_series_id"),
                          "science_contract_hash": r.get("science_contract_hash"),
                          "search_policy_hash": r.get("search_policy_hash"),
                          "resource_policy_hash": r.get("resource_policy_hash"),
                          "created_build": r.get("created_build"),
                          "channel": link and link["channel"],
                          "spec_generation": child_generation.get(r["campaign_id"]),
                          "cap_blocked": bool(queued_count and target == 0)} | stats)
    proposal_mode = _proposal_mode(spec)
    archive_row = repo.conn.execute(
        "SELECT state,summary_json,completed_utc,source_db_logical_bytes,source_blob_bytes "
        "FROM campaign_archives WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    archive_payload = None
    if archive_row is not None:
        archive_payload = {
            "state": archive_row["state"],
            "completed_utc": archive_row["completed_utc"],
            "source_db_logical_bytes": int(archive_row["source_db_logical_bytes"] or 0),
            "source_blob_bytes": int(archive_row["source_blob_bytes"] or 0),
            "summary": json.loads(archive_row["summary_json"] or "{}"),
        }
    proposal_profiles = dict(__import__("collections").Counter(
        scaling_profile(candidate["spec"]) for candidate in candidates
    ))
    proposal_categories = dict(__import__("collections").Counter(
        str(row["assessment"].get("category") or "unclassified") for row in proposal_rows.values()
    ))
    profile = observed_profile(
        repo.conn, campaign_id=campaign_id, nonterminal_only=True
    )
    ladder_runtime = []
    for rung in ladder:
        if rung in profile:
            ladder_runtime.append({"n": rung, "seconds": round(profile[rung], 1),
                                   "observed": True})
        else:
            predicted = predict_wall(profile, rung)
            ladder_runtime.append({"n": rung,
                                   "seconds": None if predicted is None else round(predicted, 1),
                                   "observed": False})
    return {"versions": {"engine": ENGINE_VERSION,
                         "analysis": ANALYSIS_VERSION, "policy": RULE_VERSION,
                         "search_space": SEARCH_SPACE_VERSION,
                         "search_measure": SEARCH_MEASURE_VERSION,
                         "build": BUILD_NUMBER,
                         "build_id": runtime_fingerprint()[:8],
                         "environment_id": environment_fingerprint()[:8],
                         "database": repo.backend},
            "campaigns": campaigns,
            "campaign_id": campaign_id, "status": campaign["status"],
            "archive": archive_payload,
            "reporting_campaign_id": campaign_control.reporting_focus(repo),
            "mode": spec.get("mode", "bounded"), "name": spec.get("name"),
            "campaign_role": campaign.get("campaign_role") or spec.get("campaign_role", "discovery"),
            "campaign_provenance": {
                "parent_campaign_id": campaign.get("parent_campaign_id"),
                "campaign_series_id": campaign.get("campaign_series_id"),
                "created_utc": campaign.get("created_utc"),
                "created_build": campaign.get("created_build"),
                "science_contract_hash": campaign.get("science_contract_hash"),
                "search_policy_hash": campaign.get("search_policy_hash"),
                "resource_policy_hash": campaign.get("resource_policy_hash"),
                "experiment_config_hash": campaign.get("experiment_config_hash"),
            },
            "parent_campaign": repo.campaign_link(campaign_id),
            "child_campaigns": child_campaigns,
            "objective": spec.get("description"),
            "dimension_model": dimension_model,
            "ladder": ladder, "max_n": max_n, "max_n_is_ceiling": not unbounded_by_static_n,
            "rung_extension": extension if unbounded_by_static_n else None,
            "ladder_runtime": ladder_runtime,
            "system_resources": host_snapshot(),
            "paused": paused, "compute_allocation": allocation,
            "compute_utilization": compute_utilization,
            "fleet_workers": _fleet_workers(repo), "workload": _workload(repo), "fleet_mode": _fleet_mode(repo),
            "analysis_backlog": allocation["analysis_backlog"],
            "analysis_queue": analysis_queue,
            "operational_alerts": [public_row(row, "detail_json") for row in
                                   repo.operational_alerts(active_only=True, limit=50)],
            "benchmark_passed": bool(benchmark and benchmark["passed"]),
            "benchmark_state": ("passed" if (benchmark and benchmark["passed"])
                                else "failed" if benchmark else "not_recorded"),
            "services": services, "job_counts": job_counts,
            "database_activity": database_activity,
            "proposal_intelligence": {
                "version": FAMILY_MEMORY_VERSION, "mode": proposal_mode,
                "scaling_profiles": proposal_profiles,
                "categories": proposal_categories,
                "zero_probability_exclusions": False,
            },
            "exploration_map": (
                _build_exploration_map(exploration_nodes) | {
                    "included": True, "available_count": len(candidates),
                    "filter_options": {
                        "operators": list(spec.get("operator_whitelist") or sorted(dsl.OPERATORS)),
                        "coupling_strata": list(COUPLING_STRATA),
                        "scaling_profiles": list(SCALING_PROFILES),
                        "coefficient_scales": list(dsl.SCALES),
                        "states": sorted({str(candidate.get("state") or "") for candidate in candidates if candidate.get("state")}),
                        "status_groups": ["active", "past", "proposed"],
                        "rungs": [int(n) for n in ladder],
                    },
                }
                if include_exploration else
                {"nodes": [], "roots": 0, "state_counts": {}, "earliest_utc": None,
                 "latest_utc": None, "included": False, "available_count": len(candidates),
                 "filter_options": {
                    "operators": list(spec.get("operator_whitelist") or sorted(dsl.OPERATORS)),
                    "coupling_strata": list(COUPLING_STRATA),
                    "scaling_profiles": list(SCALING_PROFILES),
                    "coefficient_scales": list(dsl.SCALES),
                    "states": [], "status_groups": ["active", "past", "proposed"],
                    "rungs": [int(n) for n in ladder],
                 }}
            ),
            "dimension_points": dimension_nodes,
            "dimension_landscape": dimension_landscape(dimension_nodes, proposal_exposure_rows),
            "past_research": {
                "included": bool(include_past),
                "available_count": sum(1 for candidate in candidates if candidate["state"] in terminal),
            },
            "proposed": proposed, "active": active, "past": past}
