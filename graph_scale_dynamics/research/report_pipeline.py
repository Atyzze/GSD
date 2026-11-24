from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import Decimal
import math
from pathlib import Path
from uuid import UUID
import json
import statistics

from graph_scale_dynamics.research.record_report import collect_record_safely
from graph_scale_dynamics.research.snapshot_peers import _replication_timing_summary
from graph_scale_dynamics.research.snapshot_rows import (
    DECISION_ROWS_SQL, JOB_ROWS_SQL, RUNG_ROWS_SQL, grouped_rows, job_spec_read, metrics_read, parsed_rows,
    snapshot_progress as _snapshot_progress,
)
from graph_scale_dynamics.research.analysis_queue_reading import analysis_queue_snapshot as _analysis_queue_snapshot
from graph_scale_dynamics.research.census_cost_reading import census_cost
from graph_scale_dynamics.domain.model import interrupted_sql
from graph_scale_dynamics.operations.dev_mode import provenance as dev_mode_provenance
from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, content_hash, utc_now
from graph_scale_dynamics.research.all_rung_lanes import build_lanes
from graph_scale_dynamics.research.compute_efficiency import (
    build_compute_efficiency_report, phenotype_cost_summary,
)
from graph_scale_dynamics.research.phenotype_symbols import SYMBOL_CONTRACT, symbolize_phenotype
from graph_scale_dynamics.research.report_catalog import REPORT_BY_CODE, REPORT_CATALOG_VERSION
from graph_scale_dynamics.research.density_coupling import density_coupling
from graph_scale_dynamics.scheduling.job_labels import LONGER_STAGE, WINDOW_RERUN_STAGE
from graph_scale_dynamics.research.landscape_audit import build_landscape_audit, snapshot_landscape_rows
from graph_scale_dynamics.research.decision_explanation import candidate_decision_trails
from graph_scale_dynamics.scheduling.memory import (
    AGGREGATE_MEMORY_TARGET_FRACTION, HOST_EMERGENCY_MEMORY_FRACTION_CAP,
    admission_headroom, recorded_lease_reservations,
)
from graph_scale_dynamics.operations.compute_ecology import current_capacity_diagnosis
from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint

from graph_scale_dynamics.scheduling.base_block import snapshot_base_sizes


def _json(row, key):
    value = row.get(key)
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None


def _dist(values):
    clean = sorted(v for value in values if (v := _num(value)) is not None)
    if not clean:
        return {"count": 0, "min": None, "median": None, "p90": None, "max": None}
    def pct(p):
        return clean[min(len(clean)-1, max(0, math.ceil(p * len(clean))-1))]
    return {"count": len(clean), "min": clean[0], "median": statistics.median(clean),
            "p90": pct(0.90), "max": clean[-1]}


def _parse_utc(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_between(a, b):
    x, y = _parse_utc(a), _parse_utc(b)
    return None if x is None or y is None else max(0.0, (y - x).total_seconds())


def _attach_calibration(repo, snapshot: dict) -> dict:
    snapshot["calibration"] = None
    cached = None
    try:
        raw = repo.get_flag("calibration_artifact_json", "")
        cached = json.loads(raw) if raw else None
    except Exception:
        cached = None
    try:
        from graph_scale_dynamics.calibration import (
            AUTHORITATIVE_SEEDS, current_suite_fingerprint, durable_artifact_path, load_table,
            science_fingerprint,
        )
    except Exception:
        snapshot["calibration"] = cached
        return snapshot
    current_science = science_fingerprint()
    if isinstance(cached, dict) and cached.get("contract") == "gsd-calibration-table-1":
        seeds = int(((cached.get("profile") or {}).get("seeds")) or AUTHORITATIVE_SEEDS)
        try:
            expected = current_suite_fingerprint(seeds)
        except Exception:
            expected = None
        if (expected is not None and cached.get("suite_fingerprint") == expected
                and cached.get("science_fingerprint") == current_science):
            snapshot["calibration"] = cached
            snapshot["calibration_source"] = "ledger cache (verified)"
            return snapshot
    for candidate in (repo_flag_path(repo), durable_artifact_path()):
        if candidate is None:
            continue
        document = load_table(candidate)
        if document is not None:
            snapshot["calibration"] = document
            snapshot["calibration_source"] = f"file {candidate}"
            return snapshot
    snapshot["calibration_source"] = "none"
    return snapshot


def repo_flag_path(repo):
    try:
        from pathlib import Path
        value = repo.get_flag("calibration_artifact_path", "")
        return Path(value) if value else None
    except Exception:
        return None


def report_revision_preflight(repo, primary_campaign_id: str) -> dict:
    primary_campaign_id = str(primary_campaign_id)
    if not hasattr(repo, "conn"):
        raise TypeError("report revision preflight requires a repository connection")
    ids = [primary_campaign_id]

    def _agg(sql: str, campaign_id: str) -> dict:
        row = repo.conn.execute(sql, (campaign_id,)).fetchone()
        return dict(row) if row else {}

    lanes: dict[str, list] = {
        "evidence": [], "attempts": [], "landscape": [],
        "robustness": [], "replication": [],
    }
    for campaign_id in ids:
        campaign = repo.campaign(campaign_id) or {}
        evidence = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(completion_sequence),0) seq,"
            "COALESCE(MAX(created_utc),'') latest FROM four_rung_phenotypes WHERE campaign_id=?",
            campaign_id)
        measurements = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') latest "
            "FROM measurements WHERE campaign_id=?", campaign_id)
        decisions = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') latest "
            "FROM engine_decisions WHERE campaign_id=?", campaign_id)
        attempts = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(finished_utc),'') latest "
            "FROM simulation_attempts WHERE campaign_id=?", campaign_id)
        analysis_attempts = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(finished_utc),'') latest "
            "FROM analysis_attempts WHERE campaign_id=?", campaign_id)
        exposures = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(proposal_sequence),0) seq "
            "FROM proposal_exposures WHERE campaign_id=?", campaign_id)
        candidates = _agg(
            "SELECT COUNT(*) c,COALESCE(MAX(updated_utc),'') latest "
            "FROM candidates WHERE campaign_id=?", campaign_id)

        lanes["evidence"].append({"campaign_id": campaign_id, "phenotypes": evidence,
                                  "measurements": measurements, "decisions": decisions,
                                  "candidates": candidates})
        lanes["attempts"].append({"campaign_id": campaign_id, "simulation": attempts,
                                  "analysis": analysis_attempts})
        lanes["landscape"].append({"campaign_id": campaign_id, "phenotypes": evidence,
                                   "exposures": exposures})
        lanes["robustness"].append({"campaign_id": campaign_id, "measurements": measurements,
                                    "decisions": decisions})
        lanes["replication"].append({
            "campaign_id": campaign_id,
            "science_contract_hash": campaign.get("science_contract_hash"),
            "search_policy_hash": campaign.get("search_policy_hash"),
            "search_seed": campaign.get("search_seed"),
            "phenotypes": evidence,
        })

    revisions = {f"{lane}_revision": content_hash(rows)[:20] for lane, rows in lanes.items()}
    return {
        "contract": "gsd-report-preflight-1",
        "campaign": primary_campaign_id,
        "campaign_ids": ids,
        **revisions,
        "report_revision": content_hash(revisions)[:20],
        "checked_utc": utc_now(),
    }


def collect_replication_snapshot(repo, primary_campaign_id: str, *, progress=None) -> dict:
    primary_campaign_id = str(primary_campaign_id)
    if not hasattr(repo, "conn"):
        raise TypeError("replication snapshot collection requires a repository connection")
    ids = [primary_campaign_id]
    owns_transaction = not bool(repo.conn.in_transaction)
    if owns_transaction:
        repo.conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    try:
        if progress is None:
            snapshot = _collect_snapshot_rows(repo, primary_campaign_id)
        else:
            def campaign_progress(update):
                progress(dict(update, campaign_index=1, campaign_count=1,
                              overall_fraction=max(0.0, min(1.0, float(update.get("fraction") or 0.0)))))
            snapshot = _collect_snapshot_rows(repo, primary_campaign_id, progress=campaign_progress)
        snapshot["snapshot_scope"] = "full_primary"
        _attach_calibration(repo, snapshot)
        snapshots = [snapshot]
        _snapshot_progress(progress, stage="finalize", current=8, total=8,
                           detail="computing coherent multi-campaign revision", campaign_id=primary_campaign_id)
        collected = utc_now()
        revision = content_hash({
            "campaigns": [
                {"campaign_id": row.get("campaign_id"),
                 "source_revision": row.get("source_revision"),
                 "heavy_source_revision": row.get("heavy_source_revision")}
                for row in snapshots
            ]
        })[:20]
        group = {
            "snapshot_contract": "repeatable_read_read_only" if owns_transaction else "caller_owned_transaction",
            "campaign_id": primary_campaign_id,
            "primary_campaign_id": primary_campaign_id,
            "campaign_ids": ids,
            "campaign_snapshots": snapshots,
            "snapshot_profile": "full-primary-1",
            "full_campaign_ids": [primary_campaign_id],
            "compact_peer_campaign_ids": [],
            "source_revision": revision,
            "heavy_source_revision": revision,
            "collected_utc": collected,
        }
        if owns_transaction:
            repo.conn.execute("COMMIT")
        return group
    except Exception:
        if owns_transaction:
            repo.conn.rollback_if_open()
        raise


def _collect_snapshot_rows(repo, campaign_id: str, *, progress=None) -> dict:
    _snapshot_progress(progress, stage="campaign", current=1, total=8, detail="campaign contract and analysis version", campaign_id=campaign_id)
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        raise ValueError(f"unknown campaign {campaign_id}")
    analysis_version = repo.campaign_analysis_contract(campaign_id)
    _snapshot_progress(progress, stage="cohort", current=2, total=8, detail="candidates, phenotypes, locality and proposal exposure", campaign_id=campaign_id)
    candidates = repo.candidates(campaign_id)
    phenotypes = repo.campaign_base_block_phenotypes(campaign_id, analysis_version)
    locality = repo.campaign_locality_audit_results(campaign_id, analysis_version)
    exposures = repo.proposal_exposures(campaign_id)
    _snapshot_progress(progress, stage="lifecycle", current=3, total=8, detail="jobs and decisions", campaign_id=campaign_id)
    jobs = parsed_rows(repo.conn, JOB_ROWS_SQL, (campaign_id,), "spec_json", "spec", keep=job_spec_read)
    decisions = grouped_rows(parsed_rows(repo.conn, DECISION_ROWS_SQL, (campaign_id,), "facts_json", "facts",
                                         default="{}"), "candidate_id")
    rung_spend_rows = repo.conn.execute(
        f"SELECT j.candidate_id,j.n,COALESCE(SUM(CASE WHEN NOT {interrupted_sql('a')} THEN a.wall_seconds END),0) "
        f"core_seconds,COALESCE(SUM(CASE WHEN {interrupted_sql('a')} THEN a.wall_seconds END),0) interrupted_seconds,"
        f"COALESCE(SUM(CASE WHEN NOT {interrupted_sql('a')} AND (j.stage LIKE '{LONGER_STAGE}_n%' "
        f"OR j.stage LIKE '{WINDOW_RERUN_STAGE}_n%') "
        "THEN a.wall_seconds END),0) longer_seconds "
        "FROM jobs j LEFT JOIN attempts a ON a.job_id=j.job_id "
        "WHERE j.campaign_id=? AND j.kind='simulate' GROUP BY j.candidate_id,j.n",
        (campaign_id,),
    ).fetchall()
    rung_spend = [{"candidate_id": str(row["candidate_id"]), "n": int(row["n"]),
                   "core_seconds": float(row["core_seconds"] or 0.0),
                   "interrupted_seconds": float(row["interrupted_seconds"] or 0.0),
                   "longer_seconds": float(row["longer_seconds"] or 0.0)}
                  for row in rung_spend_rows]

    _snapshot_progress(progress, stage="measurements", current=4, total=8, detail="measurements, rung summaries and analysis queues", campaign_id=campaign_id)
    measurements = parsed_rows(repo.conn,
        "SELECT m.analysis_id,m.input_artifact,m.candidate_id,m.n,m.seed,m.metrics_json,m.created_utc,"
        "m.probe_seconds_d_s,m.probe_seconds_d_v,m.probe_seconds_d_b,m.probe_seconds_d_w,"
        "aq.producer_job FROM measurements m LEFT JOIN analysis_queue aq "
        "ON aq.campaign_id=m.campaign_id AND aq.input_artifact=m.input_artifact "
        "AND aq.analysis_version=m.analysis_version "
        "WHERE m.campaign_id=? AND m.analysis_version=? ORDER BY m.candidate_id,m.n,m.seed,m.created_utc",
        (campaign_id, analysis_version), "metrics_json", "metrics", keep=metrics_read)
    rungs = parsed_rows(repo.conn, RUNG_ROWS_SQL, (campaign_id, analysis_version), "summary_json", "summary")

    analysis_rows = repo.conn.execute(
        "SELECT candidate_id,n,seed,status,created_utc,updated_utc,next_attempt_utc,attempts,error,error_class,"
        "memory_reservation_bytes FROM analysis_queue "
        "WHERE campaign_id=? AND analysis_version=? ORDER BY candidate_id,n,created_utc",
        (campaign_id, analysis_version),
    ).fetchall()
    analysis_work = [dict(row) for row in analysis_rows]
    rebuild_rows = repo.conn.execute(
        "SELECT candidate_id,status,attempts,max_attempts,error,created_utc,updated_utc,next_attempt_utc "
        "FROM candidate_evidence_rebuilds WHERE campaign_id=? AND analysis_version=? "
        "ORDER BY candidate_id",
        (campaign_id, analysis_version),
    ).fetchall()
    evidence_rebuilds = [dict(row) for row in rebuild_rows]

    _snapshot_progress(progress, stage="state_history", current=5, total=8, detail="state history", campaign_id=campaign_id)
    state_rows = repo.conn.execute(
        "SELECT * FROM candidate_state_history WHERE campaign_id=? ORDER BY state_event_id",
        (campaign_id,),
    ).fetchall()
    state_history = [dict(row) for row in state_rows]

    _snapshot_progress(progress, stage="attempts", current=6, total=8, detail="simulation, analysis and auxiliary attempt provenance", campaign_id=campaign_id)
    attempt_rows = repo.conn.execute(
        "SELECT j.candidate_id,j.n,j.seed,j.job_id,j.kind,j.stage,j.requested_by,"
        "j.created_utc job_created_utc,j.status job_status,"
        "a.attempt_id,a.started_utc,a.finished_utc,a.wall_seconds,a.exit_code,a.build_number,a.runtime_fingerprint,"
        "a.memory_reservation_bytes,"
        "a.user_cpu_seconds,a.system_cpu_seconds,a.peak_rss_bytes,a.peak_uss_bytes,a.peak_pss_bytes,"
        "a.peak_vms_bytes,a.peak_edge_count,a.final_edge_count,a.final_mean_degree,a.artifact_bytes,a.resource_json,"
        "a.error_class "
        "FROM jobs j LEFT JOIN attempts a ON a.job_id=j.job_id WHERE j.campaign_id=? "
        "ORDER BY j.created_utc,j.job_id,a.started_utc,a.attempt_id",
        (campaign_id,),
    ).fetchall()
    attempts = [dict(row) for row in attempt_rows]

    analysis_attempt_rows = repo.conn.execute(
        "SELECT aa.analysis_attempt_id,aa.input_artifact,aa.attempt_number,aa.owner,aa.started_utc,"
        "aa.finished_utc,aa.exit_code,aa.wall_seconds,aa.peak_rss_bytes,aa.peak_uss_bytes,aa.peak_pss_bytes,"
        "aa.error,aa.error_class,aa.resource_json,aa.memory_reservation_bytes,aq.candidate_id,aq.n,aq.seed,aq.producer_job "
        "FROM analysis_attempts aa JOIN analysis_queue aq "
        "ON aq.campaign_id=aa.campaign_id AND aq.input_artifact=aa.input_artifact "
        "AND aq.analysis_version=aa.analysis_version WHERE aa.campaign_id=? AND aa.analysis_version=? "
        "ORDER BY aa.started_utc,aa.analysis_attempt_id",
        (campaign_id, analysis_version),
    ).fetchall()
    analysis_attempts = [dict(row) for row in analysis_attempt_rows]
    auxiliary_attempts = repo.auxiliary_attempts(campaign_id) if hasattr(repo, "auxiliary_attempts") else []

    assessments = repo.proposal_assessments(campaign_id)
    promotions_by_candidate: dict[str, list[dict]] = {}
    promotions = [dict(row) for rows in promotions_by_candidate.values() for row in (rows or [])]
    null_rows = repo.conn.execute(
        "SELECT n,sampler_contract,analysis_version,result_json,created_utc,updated_utc "
        "FROM infinite_temperature_nulls ORDER BY n,sampler_contract,analysis_version"
    ).fetchall()
    nulls = [dict(row) | {"result": json.loads(row["result_json"])} for row in null_rows]

    _snapshot_progress(progress, stage="resources", current=7, total=8, detail="telemetry, governor, scheduler and memory reservations", campaign_id=campaign_id)
    latest_telemetry_row = repo.conn.execute(
        "SELECT sample_id,sampled_utc,cpu_percent,gsd_cpu_percent,external_cpu_percent_estimate,"
        "memory_total_bytes,memory_used_bytes,memory_free_bytes,active_simulations,active_analyses,"
        "active_slot_limit,governor_phase,quality FROM resource_telemetry "
        "ORDER BY sample_id DESC LIMIT 1",
    ).fetchone()
    latest_telemetry = dict(latest_telemetry_row) if latest_telemetry_row else {}

    deferral_rows = repo.conn.execute(
        "SELECT created_utc,payload_json FROM events WHERE topic='memory_admission_deferred' "
        "ORDER BY event_id DESC LIMIT 5000"
    ).fetchall()
    deferrals_by_n: dict = {}
    deferral_latest = None
    for row in deferral_rows:
        payload = _json(dict(row), "payload_json")
        if str(payload.get("campaign_id")) != str(campaign_id):
            continue
        key = str(payload.get("n"))
        entry = deferrals_by_n.setdefault(key, {"events": 0, "jobs": set(), "max_requested_bytes": 0, "budget_bytes": None,
                                                "refusals": {}})
        entry["events"] += 1
        refusal = str(payload.get("refusal") or "unrecorded")
        entry["refusals"][refusal] = entry["refusals"].get(refusal, 0) + 1
        entry["jobs"].add(payload.get("job_id"))
        entry["max_requested_bytes"] = max(entry["max_requested_bytes"], int(payload.get("requested_bytes") or 0))
        entry["budget_bytes"] = payload.get("budget_bytes")
        if deferral_latest is None:
            deferral_latest = row["created_utc"]
    queued_claimability: dict = {
        "by_reason": {}, "total_queued": 0,
        "reading": ("candidate_terminal: the law is in a terminal state the executor will not "
                    "claim for (PARKED laws are exempt for extension-staged jobs); "
                    "next_attempt_future: a memory backoff; claimable: the executors should "
                    "be taking it, so an idle fleet with claimable>0 is an executor fault")}
    try:
        reader = getattr(repo, "queued_simulation_claimability", None)
        for entry in (reader(campaign_id) if callable(reader) else []):
            bucket = queued_claimability["by_reason"].setdefault(
                entry["reason"], {"count": 0, "by_n": {}, "states": {}})
            bucket["count"] += int(entry["count"])
            bucket["by_n"][str(entry["n"])] = bucket["by_n"].get(str(entry["n"]), 0) + int(entry["count"])
            bucket["states"][entry["state"]] = bucket["states"].get(entry["state"], 0) + int(entry["count"])
            queued_claimability["total_queued"] += int(entry["count"])
    except Exception as exc:
        queued_claimability["error"] = f"{type(exc).__name__}: {exc}"[:200]
    memory_deferrals = {
        "latest_utc": deferral_latest,
        "by_n": {k: {"events": v["events"], "distinct_jobs": len(v["jobs"]),
                     "max_requested_bytes": v["max_requested_bytes"], "budget_bytes": v["budget_bytes"],
                     "refusals": dict(sorted(v["refusals"].items()))}
                 for k, v in sorted(deferrals_by_n.items(), key=lambda kv: int(kv[0]))},
        "reading": ("a rung with distinct_jobs high and max_requested_bytes above budget_bytes is "
                    "deferred every backoff and never runs; that is the campaign 6 stall. refusals counts each "
                    "deferral by its reason (from 747; unrecorded before)"),
    }

    from graph_scale_dynamics.scheduling.memory_hold import reading as memory_hold_reading
    memory_refusal_rows = repo.conn.execute(
        "SELECT created_utc,payload_json FROM events WHERE topic='memory_admission_refused' "
        "ORDER BY event_id DESC LIMIT 100"
    ).fetchall()
    memory_refusals = []
    collected_now = utc_now()
    for row in memory_refusal_rows:
        item = dict(row)
        payload = _json(item, "payload_json")
        age = _seconds_between(item.get("created_utc"), collected_now)
        memory_refusals.append({
            "created_utc": item.get("created_utc"),
            "age_seconds": age,
            "candidate_id": payload.get("candidate_id"),
            "n": payload.get("n"),
            "refusal": payload.get("refusal"),
            "requested_bytes": payload.get("requested_bytes"),
            "budget_bytes": payload.get("budget_bytes"),
            "hard_single_job_bytes": payload.get("hard_single_job_bytes"),
        })

    telemetry = repo.conn.execute(
        "SELECT SUM(aggregated_samples) c,MIN(COALESCE(window_started_utc,sampled_utc)) first_utc,"
        "MAX(sampled_utc) last_utc,COALESCE(MAX(sample_id),0) max_sample_id,"
        "SUM(cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_cpu,"
        "SUM(gsd_cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN gsd_cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_gsd_cpu,"
        "SUM(cpu_package_watts*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_package_watts IS NULL THEN 0 ELSE aggregated_samples END),0) avg_watts,"
        "MAX(COALESCE(cpu_temperature_max_celsius,cpu_temperature_celsius)) max_temp,"
        "SUM(CASE WHEN cpu_package_watts IS NULL THEN aggregated_samples ELSE 0 END) power_sensor_missing,"
        "SUM(CASE WHEN cpu_temperature_celsius IS NULL THEN aggregated_samples ELSE 0 END) temperature_sensor_missing "
        "FROM resource_telemetry",
    ).fetchone()
    host_jobs_by_campaign = [dict(row) for row in repo.conn.execute(
        "SELECT campaign_id,n,status,COUNT(*) c FROM jobs WHERE status IN ('queued','leased') "
        "GROUP BY campaign_id,n,status ORDER BY campaign_id,n,status"
    ).fetchall()]
    telemetry_trend = [dict(row) for row in repo.conn.execute(
        "SELECT SUBSTR(sampled_utc,1,13) AS hour_bucket,SUM(aggregated_samples) c,"
        "SUM(cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_cpu,"
        "SUM(gsd_cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN gsd_cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_gsd_cpu,"
        "MAX(COALESCE(cpu_temperature_max_celsius,cpu_temperature_celsius)) max_temp "
        "FROM resource_telemetry GROUP BY SUBSTR(sampled_utc,1,13) ORDER BY hour_bucket",
    ).fetchall()]
    telemetry_by_slot_rows = repo.conn.execute(
        "SELECT active_slot_limit,governor_phase,SUM(aggregated_samples) c,"
        "SUM(cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_cpu,"
        "SUM(gsd_cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN gsd_cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_gsd_cpu,"
        "SUM(external_cpu_percent_estimate*aggregated_samples)/NULLIF(SUM(CASE WHEN external_cpu_percent_estimate IS NULL THEN 0 ELSE aggregated_samples END),0) avg_external_cpu,"
        "SUM(cpu_package_watts*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_package_watts IS NULL THEN 0 ELSE aggregated_samples END),0) avg_watts,"
        "MAX(COALESCE(cpu_temperature_max_celsius,cpu_temperature_celsius)) max_temp,"
        "SUM((memory_used_bytes::DOUBLE PRECISION/NULLIF(memory_total_bytes,0))*aggregated_samples)"
        "/NULLIF(SUM(CASE WHEN memory_total_bytes IS NULL OR memory_total_bytes=0 THEN 0 ELSE aggregated_samples END),0) avg_memory_load "
        "FROM resource_telemetry WHERE active_slot_limit IS NOT NULL "
        "GROUP BY active_slot_limit,governor_phase ORDER BY active_slot_limit,governor_phase",
    ).fetchall()
    telemetry_by_slot = [dict(row) for row in telemetry_by_slot_rows]
    governor_events = repo.resource_governor_events(campaign_id, limit=200)
    telemetry_phase_rows = repo.conn.execute(
        "SELECT governor_phase,SUM(aggregated_samples) c,"
        "SUM(cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_cpu,"
        "SUM(gsd_cpu_percent*aggregated_samples)/NULLIF(SUM(CASE WHEN gsd_cpu_percent IS NULL THEN 0 ELSE aggregated_samples END),0) avg_gsd_cpu,"
        "SUM(external_cpu_percent_estimate*aggregated_samples)/NULLIF(SUM(CASE WHEN external_cpu_percent_estimate IS NULL THEN 0 ELSE aggregated_samples END),0) avg_external_cpu,"
        "SUM((memory_used_bytes::DOUBLE PRECISION/NULLIF(memory_total_bytes,0))*aggregated_samples)"
        "/NULLIF(SUM(CASE WHEN memory_total_bytes IS NULL OR memory_total_bytes=0 THEN 0 ELSE aggregated_samples END),0) avg_memory_load,"
        "SUM((COALESCE(active_simulations,0)+COALESCE(active_analyses,0))*aggregated_samples)::DOUBLE PRECISION"
        "/NULLIF(SUM(aggregated_samples),0) avg_active_work,"
        "MAX(COALESCE(active_simulations,0)+COALESCE(active_analyses,0)) max_active_work "
        "FROM resource_telemetry GROUP BY governor_phase ORDER BY governor_phase",
    ).fetchall()
    telemetry_by_phase = [dict(row) for row in telemetry_phase_rows]
    scheduler_snapshot = dict(repo.scheduler_snapshot() or {})
    scheduler_snapshot["paused"] = bool(scheduler_snapshot.get("paused") or repo.get_flag("paused", "0") == "1")
    host_simulation_work = repo.simulation_work_counts()
    host_active_analysis_claims = repo.active_analysis_claims()
    host_analysis_backlog = repo.analysis_backlog(analysis_version)
    reservations = recorded_lease_reservations(repo.conn)
    admission = admission_headroom(repo.conn)
    reservation_budget = admission["budget_bytes"]
    memory_reservation_snapshot = dict(reservations)
    memory_reservation_snapshot["budget"] = int(reservation_budget)
    memory_reservation_snapshot["admission"] = admission
    memory_reservation_snapshot["target_host_fraction"] = AGGREGATE_MEMORY_TARGET_FRACTION
    memory_reservation_snapshot["emergency_host_fraction"] = HOST_EMERGENCY_MEMORY_FRACTION_CAP
    memory_reservation_snapshot["minimum_host_available_bytes"] = admission["floor_bytes"]
    memory_reservation_snapshot["fraction"] = (
        float(reservations.get("total") or 0) / max(1.0, float(reservation_budget))
    )

    max_event = repo.conn.execute("SELECT COALESCE(MAX(event_id),0) m FROM events").fetchone()["m"]
    max_measurement = repo.conn.execute(
        "SELECT COALESCE(MAX(created_utc),'') m FROM measurements WHERE campaign_id=?", (campaign_id,)
    ).fetchone()["m"]
    heavy_revision_basis = {
        "campaign": campaign_id, "event": int(max_event or 0), "measurement": max_measurement,
        "candidate_count": len(candidates), "job_count": len(jobs), "phenotype_count": len(phenotypes),
        "phenotype_sequence": max((int(row.get("completion_sequence") or 0) for row in phenotypes), default=0),
        "proposal_sequence": max((int(row.get("proposal_sequence") or 0) for row in exposures), default=0),
        "engine_decisions": sum(len(rows) for rows in decisions.values()),
        "simulation_attempts": {
            "count": sum(row.get("attempt_id") is not None for row in attempts),
            "last_finished": max((str(row.get("finished_utc") or "") for row in attempts), default=""),
        },
        "analysis_attempts": {
            "count": len(analysis_attempts),
            "last_finished": max((str(row.get("finished_utc") or "") for row in analysis_attempts), default=""),
        },
        "auxiliary_attempts": {
            "count": len(auxiliary_attempts),
            "last_finished": max((str(row.get("finished_utc") or "") for row in auxiliary_attempts), default=""),
        },
        "promotions": {
            "count": len(promotions),
            "last_updated": max((str(row.get("updated_utc") or row.get("created_utc") or "") for row in promotions), default=""),
        },
    }
    heavy_source_revision = content_hash(heavy_revision_basis)[:20]
    revision = content_hash(heavy_revision_basis | {
        "telemetry_sample": int((dict(telemetry).get("max_sample_id") if telemetry else 0) or 0),
        "governor_event": max((int(row.get("governor_event_id") or 0) for row in governor_events), default=0),
    })[:20]
    phenotypes, replication_timing = _replication_timing_summary(
        repo, campaign_id, campaign, phenotypes, exposures, decisions, analysis_version,
        observation_end_utc=collected_now,
    )
    _snapshot_progress(progress, stage="finalize", current=8, total=8, detail="snapshot rows collected", campaign_id=campaign_id)
    return {
        "campaign": campaign, "campaign_id": campaign_id, "analysis_version": analysis_version,
        "candidates": candidates, "phenotypes": phenotypes, "locality": locality,
        "replication_timing": replication_timing,
        "exposures": exposures, "jobs": jobs, "engine_decisions": decisions, "rungs": rungs,
        "record": collect_record_safely(repo, campaign_id),
        "rung_spend": rung_spend,
        "fleet_ladder_hourly": repo.fleet_ladder_hourly(campaign_id),
        "measurements": measurements, "analysis_work": analysis_work,
        "evidence_rebuilds": evidence_rebuilds,
        "state_history": state_history, "attempts": attempts,
        "analysis_attempts": analysis_attempts, "auxiliary_attempts": auxiliary_attempts,
        "assessments": assessments, "promotions": promotions, "nulls": nulls,
        "telemetry": dict(telemetry) if telemetry else {},
        "host_jobs_by_campaign": host_jobs_by_campaign, "telemetry_trend": telemetry_trend,
        "telemetry_by_slot": telemetry_by_slot, "telemetry_by_phase": telemetry_by_phase,
        "resource_governor_events": governor_events,
        "scheduler_snapshot": scheduler_snapshot,
        "host_simulation_work": host_simulation_work,
        "host_analysis_backlog": int(host_analysis_backlog),
        "host_active_analysis_claims": int(host_active_analysis_claims),
        "memory_reservation_snapshot": memory_reservation_snapshot,
        "latest_telemetry": latest_telemetry,
        "recent_memory_refusals": memory_refusals,
        "memory_deferrals": memory_deferrals,
        "memory_hold": memory_hold_reading(repo.conn),
        "queued_claimability": queued_claimability,
        "active_campaign_count": int(repo.conn.execute(
            "SELECT COUNT(*) c FROM campaigns WHERE status='active'"
        ).fetchone()["c"]),
        "source_revision": revision, "heavy_source_revision": heavy_source_revision,
        "collected_utc": collected_now,
    }


def _work_supply_health(snapshot: dict) -> dict:
    phenotype_ids = {str(row.get("candidate_id")) for row in snapshot.get("phenotypes", [])}
    rung_ns: dict[str, set[int]] = defaultdict(set)
    for row in snapshot.get("rungs", []):
        n = int(row.get("n") or 0)
        if n in snapshot_base_sizes(snapshot):
            rung_ns[str(row.get("candidate_id"))].add(n)
    live_jobs = Counter(str(row.get("candidate_id")) for row in snapshot.get("jobs", [])
                        if str(row.get("status")) in {"queued", "leased"})
    live_analysis = Counter(str(row.get("candidate_id")) for row in snapshot.get("analysis_work", [])
                            if str(row.get("status")) in {"queued", "leased"})
    live_rebuilds = Counter(str(row.get("candidate_id")) for row in snapshot.get("evidence_rebuilds", [])
                            if str(row.get("status")) in {"queued", "leased"})
    terminal = set(TERMINAL_CANDIDATE_STATES)
    ready = []; stranded = []; stranded_by_state = Counter(); in_flight = 0
    for candidate in snapshot.get("candidates", []):
        cid = str(candidate.get("candidate_id")); state = str(candidate.get("state") or "UNKNOWN")
        if all(n in rung_ns.get(cid, set()) for n in snapshot_base_sizes(snapshot)) and cid not in phenotype_ids:
            ready.append(cid)
        pending = live_jobs.get(cid, 0) + live_analysis.get(cid, 0) + live_rebuilds.get(cid, 0)
        if pending:
            in_flight += 1
        elif state not in terminal and state not in {"PROPOSED", "VALIDATING", "HOLDOUT_READY"}:
            stranded.append(cid); stranded_by_state[state] += 1
    return {
        "four_base_summaries_without_durable_phenotype": len(ready),
        "four_base_summaries_without_durable_phenotype_candidates": ready[:100],
        "candidates_with_live_job_analysis_or_rebuild": in_flight,
        "nonterminal_without_pending_compute_or_analysis": len(stranded),
        "nonterminal_without_pending_compute_or_analysis_by_state": dict(stranded_by_state),
        "stranded_candidate_ids": stranded[:100],
        "live_simulation_jobs": int(sum(live_jobs.values())),
        "live_analysis_items": int(sum(live_analysis.values())),
        "live_evidence_rebuilds": int(sum(live_rebuilds.values())),
        "interpretation": (
            "Four published base summaries without a durable phenotype should be transient: the decider builds "
            "and stores the phenotype when it decides on the completed block. A nonterminal candidate with no "
            "queued/leased simulation, analysis, or evidence rebuild is operationally stranded and must clear "
            "within a reconciliation window."
        ),
    }


def _pipeline_blockers(snapshot: dict) -> dict:
    terminal = set(TERMINAL_CANDIDATE_STATES)
    phenotype_ids = {str(row.get("candidate_id")) for row in snapshot.get("phenotypes", [])}
    rungs_by_candidate: dict[str, set[int]] = defaultdict(set)
    jobs_by_candidate: dict[str, list[dict]] = defaultdict(list)
    pending_by_candidate = Counter()
    for row in snapshot.get("rungs", []):
        rungs_by_candidate[str(row.get("candidate_id"))].add(int(row.get("n") or 0))
    for row in snapshot.get("jobs", []):
        cid = str(row.get("candidate_id")); jobs_by_candidate[cid].append(row)
        if str(row.get("status")) in {"queued", "leased"}:
            pending_by_candidate[cid] += 1
    for row in snapshot.get("analysis_work", []):
        if str(row.get("status")) in {"queued", "leased"}:
            pending_by_candidate[str(row.get("candidate_id"))] += 1
    for row in snapshot.get("evidence_rebuilds", []):
        if str(row.get("status")) in {"queued", "leased"}:
            pending_by_candidate[str(row.get("candidate_id"))] += 1

    decisions = snapshot.get("engine_decisions") or {}
    jobs_by_n: dict[tuple[str, int], int] = Counter(
        (str(row.get("candidate_id")), int(row.get("n") or 0)) for row in snapshot.get("jobs", []))
    blocker_counts = Counter(); by_state_rule = Counter(); samples = []
    proposed_waiting = validating = pending_candidates = held = 0
    active_nonterminal = 0
    for candidate in snapshot.get("candidates", []):
        cid = str(candidate.get("candidate_id")); state = str(candidate.get("state") or "UNKNOWN")
        if state in terminal:
            continue
        active_nonterminal += 1
        if state == "PROPOSED":
            proposed_waiting += 1
            continue
        if state == "VALIDATING":
            validating += 1
            continue
        if pending_by_candidate.get(cid, 0):
            pending_candidates += 1
            continue
        rows = decisions.get(cid) or []
        latest = rows[-1] if rows else {}
        rule = str(latest.get("rule") or "NONE")
        action = latest.get("action")
        if action == "hold":
            held += 1
            continue
        if not latest:
            blocker = "NO_ENGINE_DECISION_YET"
        elif action in {"stop", "done"}:
            blocker = "DECIDED_TERMINAL_STATE_NOT_WRITTEN"
        elif not jobs_by_n.get((cid, int(latest.get("next_n") or 0))):
            blocker = "RUNG_BOUGHT_NO_JOB"
        else:
            blocker = "AWAITING_DECISION"
        blocker_counts[blocker] += 1
        by_state_rule[f"{state} / {rule}"] += 1
        if len(samples) < 80:
            samples.append({
                "candidate_id": cid, "state": state, "state_reason": candidate.get("state_reason"),
                "blocker": blocker, "has_durable_phenotype": cid in phenotype_ids,
                "latest_rule": latest.get("rule"), "latest_action": action,
                "latest_decision_id": latest.get("decision_id"), "latest_decision_utc": latest.get("created_utc"),
                "latest_at_n": latest.get("at_n"), "latest_next_n": latest.get("next_n"),
                "published_rungs": sorted(rungs_by_candidate.get(cid, set())),
                "candidate_updated_utc": candidate.get("updated_utc"),
            })

    return {
        "active_nonterminal_candidates": active_nonterminal,
        "candidates_with_pending_work": pending_candidates,
        "proposed_waiting": proposed_waiting,
        "validating": validating,
        "stranded_nonterminal": int(sum(blocker_counts.values())),
        "held": held,
        "blocker_counts": dict(blocker_counts.most_common()),
        "stranded_by_state_and_latest_rule": dict(by_state_rule.most_common()),
        "sample_stranded_candidates": samples,
        "interpretation": (
            "A stranded law is non-terminal (excluding proposal and validation), not held, with no queued or "
            "leased simulation, analysis or evidence rebuild; `held` counts holds, which wait by design. "
            "AWAITING_DECISION clears on the next controller pass; RUNG_BOUGHT_NO_JOB, "
            "DECIDED_TERMINAL_STATE_NOT_WRITTEN and a lasting NO_ENGINE_DECISION_YET are defects. The labels "
            "are diagnoses, not decisions."
        ),
    }


def _trajectory_rows(snapshot: dict) -> list[dict]:
    rows = []
    for item in snapshot["phenotypes"]:
        phenotype = item["phenotype"]
        per_n = phenotype.get("per_n") or {}
        rows.append({
            "candidate_id": item["candidate_id"],
            "probes": {
                probe: (list((phenotype.get("probe_vectors") or {}).get(probe) or [])
                        + list((phenotype.get("extension_probe_vectors") or {}).get(probe) or []))
                for probe in set((phenotype.get("probe_vectors") or {}))
                | set((phenotype.get("extension_probe_vectors") or {}))},
            "probe_flow": phenotype.get("probe_finite_differences") or {},
            "probe_buckets": _ladder_buckets(phenotype),
            "mean_degree": (
                [(per_n.get(str(n)) or {}).get("mean_degree")
                 for n in (phenotype.get("base_sizes") or [])]
                + [((phenotype.get("extension_per_n") or {}).get(str(n)) or {}).get("mean_degree")
                   for n in (phenotype.get("extension_sizes") or [])]),
            "sizes": ([int(n) for n in (phenotype.get("base_sizes") or [])]
                      + [int(n) for n in (phenotype.get("extension_sizes") or [])]),
            "R_half": phenotype.get("half_volume_radius_vector"),
            "symbols": symbolize_phenotype(phenotype),
        })
    return rows


def _ladder_buckets(phenotype: dict) -> dict:
    base = phenotype.get("probe_bucket_vectors") or {}
    extension = phenotype.get("extension_probe_bucket_vectors") or {}
    values = phenotype.get("extension_probe_vectors") or {}
    out = {}
    for probe in set(base) | set(extension) | set(values):
        deep = list(extension.get(probe) or [])
        deep += [None] * (len(values.get(probe) or []) - len(deep))
        out[probe] = list(base.get(probe) or []) + deep
    return out


def _report_d(snapshot):
    rows = _trajectory_rows(snapshot)
    audit = build_landscape_audit(snapshot)
    lanes = build_lanes(snapshot)
    from graph_scale_dynamics.research.stability_score import noise_floors
    calibration = snapshot.get("calibration") if isinstance(snapshot.get("calibration"), dict) else None
    coupling = density_coupling(rows, floors=noise_floors(calibration))
    return {"complete_trajectories": len(rows), "trajectories": rows,
            "density_coupling": coupling,
            "dimensional_occupancy": audit["dimensional_occupancy"],
            "scale_persistence": audit["scale_persistence"],
            "candidate_gaps": audit["candidate_gaps_and_boundaries"],
            "lane_contract": lanes["contract"],
            "neutral_common_prefix": lanes["neutral_common_prefix"],
            "selected_continuation": lanes["selected_continuation"],
            "warning": "Four points describe finite-size flow; they do not establish an asymptotic dimension. Empty bins are candidate gaps, not proof of forbidden dimensions."}


def _report_e(snapshot):
    groups = defaultdict(list)
    specimens = []
    for item in snapshot["phenotypes"]:
        symbol = symbolize_phenotype(item["phenotype"])
        groups[symbol["region_key"]].append(item["candidate_id"])
        specimens.append({"candidate_id": item["candidate_id"], "region_key": symbol["region_key"],
                          "symbols": symbol, "phenotype": item["phenotype"]})
    regions = sorted(({"region_key": key, "count": len(ids), "candidate_ids": ids[:20]} for key, ids in groups.items()), key=lambda r: (-r["count"], r["region_key"]))
    dimensional_by_candidate = {row["candidate_id"]: row for row in snapshot_landscape_rows(snapshot)}
    dimensional_regions = Counter()
    for specimen in specimens:
        row = dimensional_by_candidate.get(str(specimen["candidate_id"])) or {}
        dimensional_regions[str(row.get("dimensional_class") or "UNKNOWN")] += 1
        specimen["dimensional_class"] = row.get("dimensional_class")
        specimen["connectivity_class"] = (row.get("connectivity") or {}).get("classification")
    return {"symbol_contract": SYMBOL_CONTRACT, "region_count": len(regions), "regions": regions,
            "dimensional_family_counts": dict(dimensional_regions),
            "failure_taxonomy": _failure_taxonomy(specimens, dimensional_by_candidate),
            "compute_summary": phenotype_cost_summary(snapshot),
            "specimens": specimens, "interpretation": "Reporting-only qualitative regions; continuous observables remain authoritative."}


def _failure_taxonomy(specimens: list[dict], landscape_by_candidate: dict) -> dict:
    from graph_scale_dynamics.scaleflow.probes import PROBES, Bucket, empty_bucket_counts

    from graph_scale_dynamics.research.stability_score import gate_bucket_names
    by_probe = {probe: dict(empty_bucket_counts(), **{name: 0 for name in gate_bucket_names()}) for probe in PROBES}
    by_law = Counter()
    rung_mix = {probe: Counter() for probe in PROBES}
    examples: dict[str, list[str]] = {}
    for specimen in specimens:
        cid = str(specimen["candidate_id"])
        row = landscape_by_candidate.get(cid) or {}
        buckets = row.get("buckets") or {}
        for probe in PROBES:
            bucket = buckets.get(probe)
            if bucket in by_probe[probe]:
                by_probe[probe][bucket] += 1
            for entry in ((row.get("stability_blocks") or {}).get(probe) or {}).get("rung_bucket_mix", {}).items():
                rung_mix[probe][entry[0]] += entry[1]
        law_story = str(row.get("dimensional_class") or Bucket.NOT_ATTEMPTED.value)
        by_law[law_story] += 1
        examples.setdefault(law_story, [])
        if len(examples[law_story]) < 10:
            examples[law_story].append(cid)
    return {
        "vocabulary": [bucket.value for bucket in Bucket],
        "laws": len(specimens),
        "by_probe": by_probe,
        "by_law": dict(by_law.most_common()),
        "rung_bucket_mix_by_probe": {probe: dict(counts.most_common()) for probe, counts in rung_mix.items()},
        "examples_by_law_class": examples,
        "note": (
            "Shares the bucket vocabulary of the stability score (report 22): a law that "
            "scores zero on a probe appears here under the same reason. Counts are per "
            "probe because one law can drift on one probe and refuse on another."
        ),
    }


def _report_fleet_and_host(snapshot: dict) -> dict:
    from graph_scale_dynamics.research.survey_reports import build_fleet_and_host
    return build_fleet_and_host(snapshot)


def _report_hang_autopsy(snapshot: dict) -> dict:
    from graph_scale_dynamics.research.survey_reports import build_hang_autopsy
    return build_hang_autopsy(snapshot)


def _report_stability(snapshot: dict) -> dict:
    from graph_scale_dynamics.research.stability_score import build_stability_report
    calibration = snapshot.get("calibration") if isinstance(snapshot.get("calibration"), dict) else None
    from graph_scale_dynamics.scheduling.limits import connectivity_floor
    body = build_stability_report(list(snapshot.get("phenotypes") or []), calibration,
                                  connectivity_floor=connectivity_floor((snapshot.get("campaign") or {}).get("spec") or {}))
    return body


def _report_j(snapshot):
    by_action = Counter(); by_rule = Counter(); reasons = Counter(); rows = []
    jobs_created = Counter()
    for cid, decisions in (snapshot.get("engine_decisions") or {}).items():
        for d in decisions:
            by_action[str(d.get("action"))] += 1
            by_rule[str(d.get("rule"))] += 1
            reasons[str(d.get("reason"))] += 1
            jobs_created[str(d.get("rule"))] += int(d.get("jobs_created") or 0)
            rows.append({
                "candidate_id": cid, "decision_id": d.get("decision_id"), "created_utc": d.get("created_utc"),
                "at_n": d.get("at_n"), "next_n": d.get("next_n"), "action": d.get("action"), "rule": d.get("rule"),
                "reason": d.get("reason"), "priority": d.get("priority"), "jobs_created": d.get("jobs_created"),
                "released_hold": d.get("released_hold"),
            })
    return {
        "actions": dict(by_action), "rules": dict(by_rule), "top_reasons": reasons.most_common(30),
        "jobs_created_by_rule": dict(jobs_created), "decisions": rows,
        "candidate_outcome_trails": candidate_decision_trails(snapshot),
    }


def _report_n(snapshot):
    waits=[]; walls=[]; failures=Counter(); failure_classes=Counter()
    for row in snapshot["attempts"]:
        if row.get("started_utc"):
            waits.append(_seconds_between(row.get("job_created_utc"),row.get("started_utc")))
        walls.append(row.get("wall_seconds"))
        if row.get("exit_code") not in (None,0):
            failures[str(row.get("exit_code"))]+=1
            failure_classes[str(row.get("error_class") or "unknown")]+=1
    status=Counter(str(row.get("status")) for row in snapshot["jobs"])
    governor_events = snapshot.get("resource_governor_events") or []
    underfill = [row for row in governor_events if str(row.get("event_kind")) == "scheduler_underfill"]
    recent_underfill = underfill[-50:]
    queue_snapshot = _analysis_queue_snapshot(snapshot)
    pipeline_blockers = _pipeline_blockers(snapshot)
    capacity = current_capacity_diagnosis(snapshot, queue_snapshot, pipeline_blockers)
    return {
        "capacity_diagnosis": capacity,
        "analysis_queue_now": queue_snapshot,
        "census_cost": census_cost(snapshot, queue_snapshot.get("standing_failures")),
        "pipeline_blockers": pipeline_blockers,
        "latest_telemetry": snapshot.get("latest_telemetry") or {},
        "memory_admission_deferrals": snapshot.get("memory_deferrals") or {},
        "memory_hold": snapshot.get("memory_hold") or {},
        "queued_simulation_claimability": snapshot.get("queued_claimability") or {},
        "job_status":dict(status),
        "queue_wait_seconds":_dist(waits),
        "attempt_wall_seconds":_dist(walls),
        "attempt_failure_exit_codes":dict(failures),
        "attempt_failure_classes":dict(failure_classes),
        "attempt_failure_classes_note":(
            "exit code -9 is a SIGKILL from the worker supervisor as often as from the kernel; "
            "the class names the decision. preempted_candidate_terminal is a ladder filter or "
            "decision stopping a law whose rung was still running and is expected under filters; "
            "preempted_campaign_inactive is a close or stop; oom_killed is the memory governor or "
            "the kernel; unknown is a row whose interruption carries no class"),
        "telemetry":snapshot["telemetry"],
        "telemetry_by_phase": snapshot.get("telemetry_by_phase") or [],
        "load_power_profile_by_active_slot": snapshot.get("telemetry_by_slot") or [],
        "current_scheduler": snapshot.get("scheduler_snapshot") or {},
        "current_memory_reservations": snapshot.get("memory_reservation_snapshot") or {},
        "work_supply_health": _work_supply_health(snapshot),
        "scheduler_underfill": {
            "count_in_retained_governor_history": len(underfill),
            "recent": recent_underfill,
            "interpretation": (
                "underfill events are pool-specific: simulation underfill requires queued simulation work "
                "below simulation capacity, and analysis underfill requires queued analysis work below analysis capacity. "
                "A dry simulation queue is work-supply starvation, not scheduler underfill."
            ),
        },
        "gsd_cpu_attribution": {
            "status": "heuristic",
            "method": "host CPU minus cmdline-sampled live GSD process CPU deltas",
            "warning": (
                "short-lived children can exit between telemetry samples, so gsd_cpu/external_cpu may undercount GSD "
                "work and overstate external interference; treat this split as diagnostic, not authoritative energy accounting"
            ),
        },
        "sensor_status": {
            "power_missing_samples": int((snapshot.get("telemetry") or {}).get("power_sensor_missing") or 0),
            "temperature_missing_samples": int((snapshot.get("telemetry") or {}).get("temperature_sensor_missing") or 0),
            "degradation_contract": "missing host sensors are reported and omitted from resource votes; scientific work continues unchanged",
        },
        "interpretation": (
            "capacity_diagnosis is the current operational answer: useful work should saturate CPU slots or RAM admission, "
            "otherwise underfill is named as executor concurrency, scheduler, measured memory pressure, or upstream pipeline starvation. "
            "Scheduling never reads temperature or power telemetry to set concurrency."
        ),
    }


def _report_p(snapshot):
    return build_compute_efficiency_report(snapshot)


def _json_safe_report_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        integral = value.to_integral_value()
        return int(integral) if value == integral else float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_report_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_report_value(item) for item in value]
    return value


def _report_decision_engine(snapshot: dict) -> dict:
    from graph_scale_dynamics.research.decision_engine_report import build_decision_engine_report
    return build_decision_engine_report(snapshot)


BUILDERS = {
    "04": _report_d, "05": _report_e, "10": _report_j,
    "14": _report_n, "16": _report_p, "22": _report_stability,
    "23": _report_hang_autopsy, "25": _report_fleet_and_host, "28": _report_decision_engine,
}


def build_report(code: str, snapshot: dict) -> dict:
    code = str(code).strip()
    if not code.isdigit():
        raise KeyError(f"report identity is the sequential number, got {code!r}")
    code = str(int(code)).zfill(2)
    definition = REPORT_BY_CODE[code]
    body=BUILDERS[code](snapshot)
    source = snapshot
    campaign_id = source.get("campaign_id") or source.get("primary_campaign_id") or snapshot.get("campaign_id")
    producer_fingerprint = runtime_fingerprint()
    payload = {"report_contract":"gsd-report-payload-1","catalog_version":REPORT_CATALOG_VERSION,
               "code":code,"slug":definition.slug,"title":definition.title,"question":definition.question,
               "campaign_id":campaign_id,"source_revision":source.get("source_revision") or snapshot.get("source_revision"),
               "source_collected_utc":source.get("collected_utc") or snapshot.get("collected_utc"),
               "build_number":BUILD_NUMBER,"build_hash":producer_fingerprint,
               "runtime_fingerprint":producer_fingerprint,
               "producer":{"build_number":BUILD_NUMBER,"build_hash":producer_fingerprint,
                           "runtime_fingerprint":producer_fingerprint,
                           "hash_kind":"runtime_fingerprint",
                           "identity_contract":"gsd-report-producer-1",
                           "run_provenance":dev_mode_provenance()},
               "generated_utc":utc_now(),"body":body}
    return _json_safe_report_value(payload)
