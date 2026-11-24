from __future__ import annotations


def storage_profile(conn, campaign_id: str) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    archive = conn.execute(
        "SELECT * FROM campaign_archives WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    if not exists and archive is None:
        return {"campaign_id": campaign_id, "exists": False}
    source_status = None
    if exists:
        source_status = conn.execute(
            "SELECT status FROM campaigns WHERE campaign_id=?", (campaign_id,)
        ).fetchone()["status"]
    if archive is not None and (not exists or source_status == "archived"):
        db = conn.execute(
            "SELECT COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_archives x WHERE campaign_id=?),0)+"
            "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_archive_candidates x WHERE campaign_id=?),0)+"
            "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_archive_runs x WHERE campaign_id=?),0)+"
            "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_archive_measurements x WHERE campaign_id=?),0) b",
            (campaign_id, campaign_id, campaign_id, campaign_id),
        ).fetchone()["b"]
        return {"campaign_id": campaign_id, "exists": True, "archived": True,
                "db_logical_bytes": int(db or 0), "blob_bytes": 0,
                "exclusive_blob_bytes": 0, "blob_count": 0}

    db = conn.execute(
        "SELECT "
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaigns x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_candidates x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(cs)) FROM candidate_specs cs WHERE EXISTS "
        " (SELECT 1 FROM campaign_candidates cc WHERE cc.campaign_id=? AND cc.candidate_id=cs.candidate_id)),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM jobs x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(a)) FROM attempts a JOIN jobs j ON j.job_id=a.job_id WHERE j.campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM measurements x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM rung_summaries x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM engine_decisions x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM analysis_queue x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM candidate_evidence_rebuilds x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM proposal_assessments x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM proposal_exposures x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM analysis_attempts x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM auxiliary_attempts x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM campaign_events x WHERE campaign_id=?),0)+"
        "COALESCE((SELECT SUM(pg_column_size(x)) FROM evidence_audits x WHERE campaign_id=?),0) b",
        (campaign_id,)*16,
    ).fetchone()["b"]
    blob = conn.execute(
        "WITH source_refs AS ("
        " SELECT result_artifact h FROM jobs WHERE campaign_id=? AND result_artifact IS NOT NULL"
        " UNION SELECT input_artifact FROM measurements WHERE campaign_id=?"
        " UNION SELECT curves_artifact FROM measurements WHERE campaign_id=? AND curves_artifact IS NOT NULL"
        " UNION SELECT input_artifact FROM analysis_queue WHERE campaign_id=?"
        " UNION SELECT artifact_hash FROM evidence_audits WHERE campaign_id=?"
        " UNION SELECT based_on_report_artifact FROM campaigns WHERE campaign_id=? AND based_on_report_artifact IS NOT NULL"
        "), refs AS ("
        " SELECT h FROM source_refs"
        " UNION SELECT ar.compact_artifact FROM source_refs r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.compact_artifact IS NOT NULL"
        " UNION SELECT ar.checkpoint_artifact FROM source_refs r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.checkpoint_artifact IS NOT NULL"
        " UNION SELECT ar.record_artifact FROM source_refs r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.record_artifact IS NOT NULL"
        "), outside_source AS ("
        " SELECT result_artifact h FROM jobs WHERE campaign_id<>? AND result_artifact IS NOT NULL"
        " UNION SELECT input_artifact FROM measurements WHERE campaign_id<>?"
        " UNION SELECT curves_artifact FROM measurements WHERE campaign_id<>? AND curves_artifact IS NOT NULL"
        " UNION SELECT input_artifact FROM analysis_queue WHERE campaign_id<>?"
        " UNION SELECT artifact_hash FROM evidence_audits WHERE campaign_id<>?"
        " UNION SELECT based_on_report_artifact FROM campaigns WHERE campaign_id<>? AND based_on_report_artifact IS NOT NULL"
        "), outside_refs AS ("
        " SELECT h FROM outside_source"
        " UNION SELECT ar.compact_artifact FROM outside_source r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.compact_artifact IS NOT NULL"
        " UNION SELECT ar.checkpoint_artifact FROM outside_source r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.checkpoint_artifact IS NOT NULL"
        " UNION SELECT ar.record_artifact FROM outside_source r JOIN artifact_retention ar ON ar.artifact_hash=r.h WHERE ar.record_artifact IS NOT NULL"
        ") SELECT COUNT(*) c,"
        "COALESCE(SUM(CASE WHEN COALESCE(ar.body_state,'present')='present' THEN a.size_bytes ELSE 0 END),0) bytes,"
        "COALESCE(SUM(CASE WHEN o.h IS NULL AND COALESCE(ar.body_state,'present')='present' THEN a.size_bytes ELSE 0 END),0) exclusive,"
        "COALESCE(SUM(a.size_bytes),0) logical_bytes,"
        "SUM(CASE WHEN ar.body_state='evicted' THEN 1 ELSE 0 END) evicted_bodies "
        "FROM refs r JOIN artifacts a ON a.artifact_hash=r.h "
        "LEFT JOIN artifact_retention ar ON ar.artifact_hash=a.artifact_hash "
        "LEFT JOIN outside_refs o ON o.h=r.h",
        (campaign_id,)*12,
    ).fetchone()
    return {"campaign_id": campaign_id, "exists": True, "archived": False,
            "db_logical_bytes": int(db or 0), "blob_bytes": int(blob["bytes"] or 0),
            "exclusive_blob_bytes": int(blob["exclusive"] or 0),
            "blob_logical_bytes": int(blob["logical_bytes"] or 0),
            "evicted_blob_bodies": int(blob["evicted_bodies"] or 0),
            "blob_count": int(blob["c"] or 0)}
