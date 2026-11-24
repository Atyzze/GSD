from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Callable, Iterable

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.retention import COMPACT_SCHEMAS, compact_raw_envelope
from graph_scale_dynamics.artifact_store.envelope import validate_raw_envelope
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.domain.model import content_hash, utc_now
from graph_scale_dynamics.scaleflow.flow import rung_summary
from graph_scale_dynamics.measurements.analysis import analyze_envelope, select_best_runs
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

CHAIN_RECORD_KEY = "chain_record_artifact"
ARCHIVE_VERSION = "campaign-archive-v1"


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def compact_curve_tree(value, *, max_points: int = 32):
    value = _finite(value)
    if isinstance(value, dict):
        return {str(k): compact_curve_tree(v, max_points=max_points)
                for k, v in value.items()}
    if isinstance(value, list):
        if len(value) <= max_points:
            return [compact_curve_tree(v, max_points=max_points) for v in value]
        indices = sorted({round(i * (len(value) - 1) / (max_points - 1))
                          for i in range(max_points)})
        sample = [compact_curve_tree(value[i], max_points=max_points) for i in indices]
        numeric = [float(v) for v in value
                   if isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(float(v))]
        out = {"archive_compacted": True, "count": len(value),
               "indices": indices, "sample": sample}
        if numeric:
            out.update({"min": min(numeric), "max": max(numeric),
                        "first": numeric[0], "last": numeric[-1]})
        return out
    return value


def _group_rows(rows: Iterable[dict], key: str, json_columns: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        for column in json_columns:
            if row.get(column) is not None:
                row[column[:-5] if column.endswith("_json") else column] = json.loads(row[column])
                row.pop(column, None)
        grouped[str(row[key])].append(row)
    return grouped


def _candidate_context(repo: Repo, campaign_id: str) -> dict[str, dict]:
    rungs = _group_rows(repo.conn.execute(
        "SELECT * FROM rung_summaries WHERE campaign_id=? ORDER BY candidate_id,n,analysis_version",
        (campaign_id,)).fetchall(), "candidate_id", ("summary_json",))
    decisions = _group_rows(repo.conn.execute(
        "SELECT * FROM engine_decisions WHERE campaign_id=? ORDER BY candidate_id,decision_id",
        (campaign_id,)).fetchall(), "candidate_id", ("facts_json",))
    proposals = _group_rows(repo.conn.execute(
        "SELECT * FROM proposal_assessments WHERE campaign_id=? ORDER BY candidate_id,created_utc",
        (campaign_id,)).fetchall(), "candidate_id", ("assessment_json",))
    audits = _group_rows(repo.conn.execute(
        "SELECT * FROM evidence_audits WHERE campaign_id=? ORDER BY candidate_id,audited_utc",
        (campaign_id,)).fetchall(), "candidate_id", ("detail_json",))
    compute = _group_rows(repo.conn.execute(
        "SELECT j.candidate_id,j.n,COUNT(DISTINCT j.job_id) jobs,COUNT(a.attempt_id) attempts," 
        "COALESCE(SUM(a.wall_seconds),0) core_seconds,MAX(a.peak_rss_bytes) peak_rss_bytes," 
        "MAX(a.peak_edge_count) peak_edge_count,MAX(a.final_edge_count) final_edge_count "
        "FROM jobs j LEFT JOIN attempts a ON a.job_id=j.job_id WHERE j.campaign_id=? "
        "GROUP BY j.candidate_id,j.n ORDER BY j.candidate_id,j.n", (campaign_id,)).fetchall(),
        "candidate_id")
    candidates = {}
    for candidate in repo.candidates(campaign_id):
        cid = candidate["candidate_id"]
        candidates[cid] = {
            "rung_summaries": rungs.get(cid, []),
            "engine_decisions": decisions.get(cid, []),
            "proposal_assessments": proposals.get(cid, []),
            "evidence_audits": audits.get(cid, []),
            "compute_by_n": compute.get(cid, []),
        }
    return candidates


def _archive_analysis_id(job_id: str, artifact_hash: str) -> str:
    digest = content_hash({
        "archive_version": ARCHIVE_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "job_id": str(job_id),
        "input_artifact": str(artifact_hash),
    })
    return f"archive-{digest[:48]}"


def _archive_rung_summaries(repo: Repo, campaign_id: str) -> dict[str, list[dict]]:
    rows = repo.conn.execute(
        "SELECT candidate_id,n,seed,metrics_json FROM campaign_archive_measurements "
        "WHERE campaign_id=? AND verified=1 ORDER BY candidate_id,n,seed,analysis_id",
        (campaign_id,),
    ).fetchall()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            metrics = json.loads(row["metrics_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        grouped[str(row["candidate_id"])].append({
            "n": int(row["n"]), "seed": int(row["seed"]), "metrics": metrics,
        })

    out: dict[str, list[dict]] = {}
    for candidate_id, measurements in grouped.items():
        best = select_best_runs(measurements)
        by_n: dict[int, list[dict]] = defaultdict(list)
        for item in best:
            by_n[int(item["n"])].append(item["metrics"])
        out[candidate_id] = [
            {"n": int(n), "analysis_version": ANALYSIS_VERSION,
             "summary": _finite(rung_summary(metrics))}
            for n, metrics in sorted(by_n.items())
        ]
    return out


def archive_campaign(repo: Repo, store: BlobStore, campaign_id: str, *,
                     progress: Callable[[str], None] | None = None,
                     allow_incomplete: bool = False) -> dict:
    progress = progress or (lambda _message: None)
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        archived = repo.conn.execute(
            "SELECT * FROM campaign_archives WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if archived and archived["state"] == "complete":
            return {"campaign_id": campaign_id, "already_archived": True,
                    "summary": json.loads(archived["summary_json"] or "{}")}
        raise ValueError(f"unknown campaign {campaign_id}")
    if campaign["status"] == "archived":
        archived = repo.conn.execute(
            "SELECT * FROM campaign_archives WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        return {"campaign_id": campaign_id, "already_archived": True,
                "summary": json.loads((archived or {}).get("summary_json", "{}") or "{}")}

    active_children = [row for row in repo.child_campaigns(campaign_id)
                       if row.get("status") == "active"]
    if active_children:
        ids = ", ".join(row["child_campaign_id"] for row in active_children)
        raise ValueError(f"campaign has active linked confirmation campaign(s): {ids}; retire those first")

    source_stats = repo.campaign_stats(campaign_id)
    stopped = repo.stop_campaign_work(campaign_id, reason="campaign archival")
    if repo.get_flag("home_campaign", "") == campaign_id:
        repo.set_flag("home_campaign", "")
    profile = repo.campaign_storage_profile(campaign_id)
    now = utc_now()
    repo._write(
        "INSERT INTO campaign_archives(campaign_id,archive_version,state,source_status,spec_json,"
        "spec_hash,summary_json,source_db_logical_bytes,source_blob_bytes,source_blob_count,"
        "verified_blob_count,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,0,?) "
        "ON CONFLICT(campaign_id) DO UPDATE SET archive_version=excluded.archive_version,"
        "state='building',source_db_logical_bytes=excluded.source_db_logical_bytes,"
        "source_blob_bytes=excluded.source_blob_bytes,source_blob_count=excluded.source_blob_count",
        (campaign_id, ARCHIVE_VERSION, "building", campaign["status"], campaign["spec_json"],
         campaign["spec_hash"], "{}", int(profile.get("db_logical_bytes", 0)),
         int(profile.get("blob_bytes", 0)), int(profile.get("blob_count", 0)), now),
    )

    context = _candidate_context(repo, campaign_id)
    candidates = repo.candidates(campaign_id)
    candidate_count = len(candidates)

    measurement_rows = repo.conn.execute(
        "SELECT m.*,a.size_bytes curves_size FROM measurements m "
        "LEFT JOIN artifacts a ON a.artifact_hash=m.curves_artifact "
        "WHERE m.campaign_id=? ORDER BY m.created_utc,m.analysis_id", (campaign_id,)
    ).fetchall()
    source_measured_inputs = {str(row["input_artifact"]) for row in measurement_rows
                              if row["input_artifact"]}

    existing_runs = {row["job_id"]: int(row["verified"]) for row in repo.conn.execute(
        "SELECT job_id,verified FROM campaign_archive_runs WHERE campaign_id=?", (campaign_id,)).fetchall()}
    existing_archive_measurements = {
        str(row["analysis_id"]): int(row["verified"])
        for row in repo.conn.execute(
            "SELECT analysis_id,verified FROM campaign_archive_measurements WHERE campaign_id=?",
            (campaign_id,),
        ).fetchall()
    }
    run_rows = repo.conn.execute(
        "SELECT j.job_id,j.candidate_id,j.n,j.seed,j.replicate,j.result_artifact,a.size_bytes,"
        "COALESCE(ar.body_state,'present') body_state,ar.compact_artifact,ar.record_artifact,"
        "ar.detail_json retention_detail,"
        "j.created_utc FROM jobs j LEFT JOIN artifacts a ON a.artifact_hash=j.result_artifact "
        "LEFT JOIN artifact_retention ar ON ar.artifact_hash=j.result_artifact "
        "WHERE j.campaign_id=? AND j.result_artifact IS NOT NULL ORDER BY j.created_utc,j.job_id",
        (campaign_id,)).fetchall()
    verified = 0
    generated_measurements = 0
    errors: list[dict] = []
    total_runs = len(run_rows)
    for index, row in enumerate(run_rows, 1):
        job_id = str(row["job_id"])
        artifact_hash = str(row["result_artifact"])
        synthetic_id = _archive_analysis_id(job_id, artifact_hash)
        needs_run_archive = existing_runs.get(job_id) != 1
        needs_archive_analysis = (
            artifact_hash not in source_measured_inputs
            and existing_archive_measurements.get(synthetic_id) != 1
        )
        envelope = None
        compact = None
        ok = 1
        source_size = row["size_bytes"]
        try:
            if source_size is None:
                raise RuntimeError("result artifact is referenced by the job but missing from the artifacts registry")
            body_state = str(row["body_state"])
            raw_available = True
            if body_state == "transient":
                try:
                    store.stat(artifact_hash)
                except FileNotFoundError:
                    raw_available = False
            if body_state == "evicted" or not raw_available:
                if needs_archive_analysis:
                    raise RuntimeError(
                        "raw simulation body is unavailable before authoritative analysis existed"
                    )
                if needs_run_archive:
                    compact_artifact = row["compact_artifact"]
                    if not compact_artifact:
                        raise RuntimeError("unavailable raw simulation has no compact evidence artifact")
                    compact = store.get_json(str(compact_artifact), verify=True)
                    if (str(compact.get("schema")) not in COMPACT_SCHEMAS
                            or int(compact.get("n", -1)) != int(row["n"])
                            or int(compact.get("seed", -1)) != int(row["seed"])):
                        raise RuntimeError("compact simulation evidence does not match source job")
                verified += 1
            else:
                if needs_run_archive or needs_archive_analysis:
                    envelope = store.get_json(artifact_hash, verify=True)
                    validate_raw_envelope(
                        envelope, expected_n=int(row["n"]), expected_seed=int(row["seed"]),
                        expected_job_id=job_id, expected_candidate_id=row["candidate_id"],
                    )
                if needs_run_archive:
                    compact = compact_raw_envelope(envelope)
                verified += 1
        except Exception as exc:
            compact = {"archive_error": f"{type(exc).__name__}: {exc}"}
            ok = 0
            errors.append({"kind": "simulation", "job_id": job_id,
                           "artifact": artifact_hash, "error": str(exc)})
            if not allow_incomplete:
                repo._write("UPDATE campaign_archives SET state='incomplete' WHERE campaign_id=?",
                            (campaign_id,))
                raise RuntimeError(
                    f"archive stopped at simulation artifact {artifact_hash[:16]}: {exc}"
                ) from exc

        if needs_run_archive and row["record_artifact"]:
            compact = dict(compact or {}, **{CHAIN_RECORD_KEY: str(row["record_artifact"])})
        if needs_run_archive:
            repo._write(
                "INSERT INTO campaign_archive_runs(campaign_id,job_id,candidate_id,n,seed,replicate,"
                "source_artifact,source_size_bytes,verified,compact_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(campaign_id,job_id) DO UPDATE SET verified=excluded.verified,compact_json=excluded.compact_json",
                (campaign_id, job_id, row["candidate_id"], int(row["n"]), int(row["seed"]),
                 int(row["replicate"]), artifact_hash, int(source_size or 0), ok,
                 _json(_finite(compact or {})), row["created_utc"]),
            )

        if ok and needs_archive_analysis:
            try:
                if envelope is None:
                    envelope = store.get_json(artifact_hash, verify=True)
                    validate_raw_envelope(
                        envelope, expected_n=int(row["n"]), expected_seed=int(row["seed"]),
                        expected_job_id=job_id, expected_candidate_id=row["candidate_id"],
                    )
                metrics, curves = analyze_envelope(envelope, seed=int(row["seed"]))
                repo._write(
                    "INSERT INTO campaign_archive_measurements(campaign_id,analysis_id,candidate_id,n,seed,"
                    "analysis_version,source_artifact,curves_source_artifact,verified,metrics_json,"
                    "curve_summary_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(campaign_id,analysis_id) DO UPDATE SET verified=excluded.verified,"
                    "metrics_json=excluded.metrics_json,curve_summary_json=excluded.curve_summary_json",
                    (campaign_id, synthetic_id, row["candidate_id"], int(row["n"]), int(row["seed"]),
                     ANALYSIS_VERSION, artifact_hash, None, 1, _json(_finite(metrics)),
                     _json(compact_curve_tree(curves)), utc_now()),
                )
                existing_archive_measurements[synthetic_id] = 1
                generated_measurements += 1
            except Exception as exc:
                errors.append({"kind": "archive_analysis", "job_id": job_id,
                               "artifact": artifact_hash, "error": str(exc)})
                if not allow_incomplete:
                    repo._write("UPDATE campaign_archives SET state='incomplete' WHERE campaign_id=?",
                                (campaign_id,))
                    raise RuntimeError(
                        f"archive analysis failed for simulation artifact {artifact_hash[:16]}: {exc}"
                    ) from exc
                repo._write(
                    "INSERT INTO campaign_archive_measurements(campaign_id,analysis_id,candidate_id,n,seed,"
                    "analysis_version,source_artifact,curves_source_artifact,verified,metrics_json,"
                    "curve_summary_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(campaign_id,analysis_id) DO UPDATE SET verified=excluded.verified,"
                    "metrics_json=excluded.metrics_json,curve_summary_json=excluded.curve_summary_json",
                    (campaign_id, synthetic_id, row["candidate_id"], int(row["n"]), int(row["seed"]),
                     ANALYSIS_VERSION, artifact_hash, None, 0,
                     _json({"archive_error": f"{type(exc).__name__}: {exc}"}), "{}", utc_now()),
                )

        if index % 100 == 0 or index == total_runs:
            progress(
                f"archive {campaign_id}: verified {index}/{total_runs} simulation artifacts; "
                f"analyzed {generated_measurements} previously-unmeasured runs"
            )

    total_measurements = len(measurement_rows)
    for index, row in enumerate(measurement_rows, 1):
        if existing_archive_measurements.get(str(row["analysis_id"])) == 1:
            continue
        curve_summary = {}
        ok = 1
        if row["curves_artifact"]:
            try:
                curves = store.get_json(row["curves_artifact"], verify=True)
                curve_summary = compact_curve_tree(curves)
            except Exception as exc:
                ok = 0
                errors.append({"kind": "curves", "analysis_id": row["analysis_id"],
                               "artifact": row["curves_artifact"], "error": str(exc)})
                if not allow_incomplete:
                    repo._write("UPDATE campaign_archives SET state='incomplete' WHERE campaign_id=?",
                                (campaign_id,))
                    raise RuntimeError(
                        f"archive stopped at curve artifact {row['curves_artifact'][:16]}: {exc}"
                    ) from exc
        try:
            metrics = _finite(json.loads(row["metrics_json"] or "{}"))
        except (TypeError, json.JSONDecodeError) as exc:
            ok = 0
            metrics = {"archive_error": f"invalid metrics_json: {exc}"}
            errors.append({"kind": "metrics", "analysis_id": row["analysis_id"], "error": str(exc)})
            if not allow_incomplete:
                repo._write("UPDATE campaign_archives SET state='incomplete' WHERE campaign_id=?",
                            (campaign_id,))
                raise RuntimeError(f"archive stopped at measurement {row['analysis_id']}: {exc}") from exc
        repo._write(
            "INSERT INTO campaign_archive_measurements(campaign_id,analysis_id,candidate_id,n,seed,"
            "analysis_version,source_artifact,curves_source_artifact,verified,metrics_json,"
            "curve_summary_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(campaign_id,analysis_id) DO UPDATE SET verified=excluded.verified,"
            "metrics_json=excluded.metrics_json,curve_summary_json=excluded.curve_summary_json",
            (campaign_id, row["analysis_id"], row["candidate_id"], int(row["n"]), int(row["seed"]),
             row["analysis_version"], row["input_artifact"], row["curves_artifact"], ok,
             _json(metrics), _json(curve_summary), row["created_utc"]),
        )
        existing_archive_measurements[str(row["analysis_id"])] = ok
        if index % 500 == 0 or index == total_measurements:
            progress(f"archive {campaign_id}: condensed {index}/{total_measurements} existing measurements")

    archive_rungs = _archive_rung_summaries(repo, campaign_id)
    for candidate in candidates:
        cid = candidate["candidate_id"]
        candidate_summary = dict(context.get(cid, {}))
        candidate_summary["archive_rung_summaries"] = archive_rungs.get(cid, [])
        repo._write(
            "INSERT INTO campaign_archive_candidates(campaign_id,candidate_id,spec_json,dynamics,"
            "complexity,lineage_parent,state,state_reason,summary_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,candidate_id) DO UPDATE SET "
            "state=excluded.state,state_reason=excluded.state_reason,summary_json=excluded.summary_json",
            (campaign_id, cid, candidate["spec_json"], candidate["dynamics"],
             int(candidate["complexity"]), candidate["lineage_parent"], candidate["state"],
             candidate["state_reason"], _json(_finite(candidate_summary)), candidate["created_utc"]),
        )

    archived_runs = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_runs WHERE campaign_id=?", (campaign_id,)
    ).fetchone()["c"])
    archived_candidates = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_candidates WHERE campaign_id=?", (campaign_id,)
    ).fetchone()["c"])
    verified_archived_measurements = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_measurements WHERE campaign_id=? AND verified=1",
        (campaign_id,),
    ).fetchone()["c"])
    missing_measurement_runs = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_runs r WHERE r.campaign_id=? AND r.verified=1 "
        "AND NOT EXISTS (SELECT 1 FROM campaign_archive_measurements m WHERE m.campaign_id=r.campaign_id "
        "AND m.source_artifact=r.source_artifact AND m.verified=1)",
        (campaign_id,),
    ).fetchone()["c"])
    if (archived_runs != total_runs or archived_candidates != candidate_count
            or missing_measurement_runs or errors):
        repo._write("UPDATE campaign_archives SET state='incomplete' WHERE campaign_id=?", (campaign_id,))
        raise RuntimeError(
            "archive verification failed; live campaign evidence was left intact "
            f"(runs={archived_runs}/{total_runs}, candidates={archived_candidates}/{candidate_count}, "
            f"unmeasured_runs={missing_measurement_runs}, errors={len(errors)}"
            + (f", the first: {errors[0].get('error')}" if errors else "") + ")"
        )

    verified_curve_blobs = int(repo.conn.execute(
        "SELECT COUNT(DISTINCT curves_source_artifact) c FROM campaign_archive_measurements "
        "WHERE campaign_id=? AND verified=1 AND curves_source_artifact IS NOT NULL",
        (campaign_id,),
    ).fetchone()["c"] or 0)
    verified_blob_count = int(verified + verified_curve_blobs)
    archived_measurements = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_measurements WHERE campaign_id=?", (campaign_id,)
    ).fetchone()["c"])
    total_generated_measurements = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM campaign_archive_measurements WHERE campaign_id=? "
        "AND analysis_id LIKE 'archive-%'", (campaign_id,)
    ).fetchone()["c"] or 0)

    summary = {
        "archive_version": ARCHIVE_VERSION,
        "purpose": "compact scientific archive; raw graph states intentionally omitted",
        "source_status": campaign["status"],
        "candidates": candidate_count,
        "simulation_runs": total_runs,
        "source_measurements": total_measurements,
        "archive_measurements": archived_measurements,
        "archive_generated_measurements": total_generated_measurements,
        "verified_measurements": verified_archived_measurements,
        "verified_simulation_blobs": verified,
        "verification_errors": errors[:100],
        "source_db_logical_bytes": int(profile.get("db_logical_bytes", 0)),
        "source_blob_bytes": int(profile.get("blob_bytes", 0)),
        "source_blob_count": int(profile.get("blob_count", 0)),
        "exclusive_blob_bytes_before_archive": int(profile.get("exclusive_blob_bytes", 0)),
        "compute_seconds": float(source_stats.get("compute_seconds", 0) or 0),
        "last_activity_utc": source_stats.get("last_activity_utc"),
        "source_job_counts": source_stats.get("job_counts") or {},
        "stopped_work": stopped,
        "analysis_completion": {
            "policy": "every verified simulation run has a verified measurement before raw-state retirement",
            "analysis_version_for_backfill": ANALYSIS_VERSION,
            "previously_unmeasured_runs_analyzed_during_archive": total_generated_measurements,
        },
        "raw_data_policy": {
            "preserved": ["candidate specs", "candidate states", "rung summaries", "transitions",
                          "decisions", "proposal/comparison assessments", "measurement metrics",
                          "archive-derived rung summaries", "provenance",
                          "per-run final/acceptance/thermalization diagnostics", "degree histograms",
                          "downsampled estimator curves",
                          "every seed's chain record: each chain's final graph and trajectory, the chain from empty's "
                          "snapshots to N=4,096 (artifact_store/chain_record.py, never evicted)"],
            "discarded_after_gc": ["raw envelopes", "full-resolution curve artifacts"],
        },
    }

    repo.begin_transaction(attempts=12)
    try:
        repo.conn.execute("DELETE FROM campaign_candidates WHERE campaign_id=?", (campaign_id,))
        repo.conn.execute("UPDATE campaigns SET status='archived',workers_target=0 WHERE campaign_id=?",
                          (campaign_id,))
        repo.conn.execute(
            "UPDATE campaign_archives SET state='complete',summary_json=?,verified_blob_count=?,"
            "completed_utc=? WHERE campaign_id=?",
            (_json(_finite(summary)), verified_blob_count, utc_now(), campaign_id),
        )
        repo.conn.execute("COMMIT")
    except Exception:
        repo.conn.rollback_if_open()
        raise
    repo.record_campaign_event(campaign_id, "campaign_archived", {
        "verified_blob_count": verified_blob_count,
        "source_compute_seconds": source_stats.get("compute_seconds"),
    })
    return {"campaign_id": campaign_id, "archived": True, "summary": summary}
