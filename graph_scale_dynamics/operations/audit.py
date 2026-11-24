from __future__ import annotations

from collections import Counter
from pathlib import Path

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, utc_now


SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


def _finding(severity: str, code: str, message: str, **detail) -> dict:
    return {"severity": severity, "code": code, "message": message, "detail": detail}


def _rows(conn, sql: str, args=()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def artifact_reference_detail(conn, digest: str) -> dict:
    row = conn.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM jobs WHERE result_artifact=?) jobs_result,"
        "(SELECT COUNT(*) FROM measurements WHERE input_artifact=?) measurement_input,"
        "(SELECT COUNT(*) FROM measurements WHERE curves_artifact=?) measurement_curves,"
        "(SELECT COUNT(*) FROM analysis_queue WHERE input_artifact=?) analysis_input,"
        "(SELECT COUNT(*) FROM evidence_audits WHERE artifact_hash=?) evidence_audits",
        (digest, digest, digest, digest, digest),
    ).fetchone()
    roles = [str(item["role"]) for item in conn.execute(
        "SELECT DISTINCT role FROM artifact_producers WHERE artifact_hash=? ORDER BY role",
        (digest,),
    ).fetchall()]
    refs = {key: int(row[key] or 0) for key in (
        "jobs_result", "measurement_input", "measurement_curves",
        "analysis_input", "evidence_audits",
    )}
    derived_only = (
        refs["measurement_curves"] > 0
        and refs["jobs_result"] == 0
        and refs["measurement_input"] == 0
        and refs["analysis_input"] == 0
        and refs["evidence_audits"] == 0
        and set(roles).issubset({"analysis"})
    )
    return {"references": refs, "producer_roles": roles,
            "repairable_missing_derived_curve": derived_only}


def repair_missing_derived_blobs(repo, blobs_root: str | Path) -> dict:
    store = BlobStore(blobs_root)
    rows = [dict(row) for row in repo.conn.execute(
        "SELECT a.artifact_hash,a.size_bytes,COALESCE(ar.body_state,'present') body_state "
        "FROM artifacts a LEFT JOIN artifact_retention ar ON ar.artifact_hash=a.artifact_hash "
        "ORDER BY a.created_utc,a.artifact_hash"
    ).fetchall()]
    repaired: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        digest = row["artifact_hash"]
        if row.get("body_state") == "evicted":
            continue
        try:
            store.stat(digest)
            continue
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            skipped.append({"artifact": digest, "reason": f"unreadable: {exc}"})
            continue
        detail = artifact_reference_detail(repo.conn, digest)
        if not detail["repairable_missing_derived_curve"]:
            skipped.append({"artifact": digest, "reason": "not derived-curve-only", **detail})
            continue
        repo.begin_transaction(attempts=12)
        try:
            changed = repo.conn.execute(
                "UPDATE measurements SET curves_artifact=NULL WHERE curves_artifact=?",
                (digest,),
            ).rowcount
            repo.conn.execute(
                "DELETE FROM artifact_producers WHERE artifact_hash=? AND role='analysis'",
                (digest,),
            )
            deleted = repo.conn.execute(
                "DELETE FROM artifacts WHERE artifact_hash=?", (digest,)
            ).rowcount
            repo.conn.execute("COMMIT")
        except Exception:
            repo.conn.rollback_if_open()
            raise
        repaired.append({"artifact": digest, "size_bytes": int(row["size_bytes"] or 0),
                         "measurement_curve_references_cleared": int(changed),
                         "artifact_rows_deleted": int(deleted)})
    return {"repaired": repaired, "skipped_missing": skipped,
            "repaired_count": len(repaired), "skipped_count": len(skipped)}


def audit_state(conn, blobs_root: str | Path, *, verify_hashes: bool = True,
                include_orphans: bool = True, max_detail: int = 100,
                statement_timeout_ms: int | None = None) -> dict:
    if statement_timeout_ms is not None:
        conn.execute("SELECT set_config('statement_timeout', ?, false)",
                     (f"{max(0, int(statement_timeout_ms))}ms",))
    store = BlobStore(blobs_root)
    findings: list[dict] = []
    artifact_rows = _rows(
        conn, "SELECT a.artifact_hash,a.size_bytes,a.media_type,"
        "COALESCE(ar.body_state,'present') body_state,ar.storage_class,ar.compact_artifact,"
        "ar.checkpoint_artifact FROM artifacts a LEFT JOIN artifact_retention ar "
        "ON ar.artifact_hash=a.artifact_hash"
    )
    database_artifacts = {row["artifact_hash"]: row for row in artifact_rows}

    for digest, row in database_artifacts.items():
        if row.get("body_state") == "evicted":
            continue
        try:
            stat = store.stat(digest)
        except FileNotFoundError:
            ref_detail = artifact_reference_detail(conn, digest)
            if row.get("body_state") == "transient":
                findings.append(_finding(
                    "warning", "artifact.transient_body_missing",
                    "tmpfs-only artifact body is absent; raw inputs replay producers and missing continuation checkpoints trigger an explicit clean rung restart",
                    artifact=digest, expected_size=int(row["size_bytes"]), **ref_detail,
                ))
            else:
                findings.append(_finding(
                    "error", "artifact.missing_blob", "database artifact has no blob file",
                    artifact=digest, expected_size=int(row["size_bytes"]), **ref_detail,
                ))
            continue
        except (OSError, ValueError) as exc:
            findings.append(_finding(
                "error", "artifact.unreadable", "artifact path could not be inspected",
                artifact=digest, error=f"{type(exc).__name__}: {exc}",
            ))
            continue
        if stat.st_size != int(row["size_bytes"]):
            findings.append(_finding(
                "error", "artifact.size_mismatch", "blob size differs from database metadata",
                artifact=digest, expected_size=int(row["size_bytes"]), actual_size=stat.st_size,
            ))
        if verify_hashes and not store.verify(digest):
            findings.append(_finding(
                "error", "artifact.digest_mismatch", "blob content does not match its digest",
                artifact=digest,
            ))

    if include_orphans:
        for digest in store.iter_digests():
            if digest not in database_artifacts:
                findings.append(_finding(
                    "warning", "artifact.orphan_blob",
                    "blob exists without an authoritative database artifact row",
                    artifact=digest,
                ))

    checks: list[tuple[str, str, str, str, tuple]] = [
        (
            "error", "job.done_without_artifact",
            "completed simulation job has no valid artifact row",
            "SELECT job_id,campaign_id,candidate_id,result_artifact FROM jobs "
            "WHERE kind='simulate' AND status='done' AND "
            "(result_artifact IS NULL OR NOT EXISTS(SELECT 1 FROM artifacts a "
            "WHERE a.artifact_hash=jobs.result_artifact))",
            (),
        ),
        (
            "error", "analysis.done_without_measurement",
            "completed analysis queue item has no matching measurement",
            "SELECT campaign_id,candidate_id,input_artifact,analysis_version FROM analysis_queue q "
            "WHERE status='done' AND NOT EXISTS(SELECT 1 FROM measurements m "
            "WHERE m.campaign_id=q.campaign_id AND m.input_artifact=q.input_artifact "
            "AND m.analysis_version=q.analysis_version)",
            (),
        ),
        (
            "error", "queue.inactive_campaign_work",
            "queued or leased work belongs to a non-active campaign",
            "SELECT j.campaign_id,j.candidate_id,j.job_id,j.status,'simulation' work_type "
            "FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "WHERE j.status IN ('queued','leased') AND c.status<>'active' "
            "UNION ALL SELECT q.campaign_id,q.candidate_id,q.input_artifact,q.status,'analysis' "
            "FROM analysis_queue q JOIN campaigns c ON c.campaign_id=q.campaign_id "
            "WHERE q.status IN ('queued','leased') AND c.status<>'active'",
            (),
        ),
        (
            "error", "lease.expired",
            "work lease is expired and awaiting reclamation",
            "SELECT campaign_id,candidate_id,job_id reference,status,'simulation' work_type,"
            "lease_expires_utc FROM jobs WHERE status='leased' AND lease_expires_utc<? "
            "UNION ALL SELECT campaign_id,candidate_id,input_artifact,status,'analysis',"
            "lease_expires_utc FROM analysis_queue WHERE status='leased' AND lease_expires_utc<?",
            (utc_now(), utc_now()),
        ),
        (
            "error", "artifact.producer_missing",
            "artifact row has no explicit producer relationship",
            "WITH referenced AS ("
            "  SELECT result_artifact AS artifact_hash FROM jobs "
            "    WHERE result_artifact IS NOT NULL"
            "  UNION SELECT input_artifact FROM measurements"
            "  UNION SELECT curves_artifact FROM measurements "
            "    WHERE curves_artifact IS NOT NULL"
            "  UNION SELECT input_artifact FROM analysis_queue"
            ") SELECT a.artifact_hash,a.producer_job FROM artifacts a "
            "JOIN referenced r ON r.artifact_hash=a.artifact_hash "
            "LEFT JOIN artifact_producers p ON p.artifact_hash=a.artifact_hash "
            "WHERE p.artifact_hash IS NULL",
            (),
        ),
        (
            "error", "artifact.evicted_raw_without_compact",
            "evicted raw simulation identity has no retained compact evidence body",
            "SELECT src.artifact_hash,src.compact_artifact FROM artifact_retention src "
            "LEFT JOIN artifact_retention compact ON compact.artifact_hash=src.compact_artifact "
            "WHERE src.storage_class='raw_simulation' AND src.body_state='evicted' AND "
            "(src.compact_artifact IS NULL OR compact.artifact_hash IS NULL OR compact.body_state<>'present')",
            (),
        ),
        (
            "error", "artifact.evicted_raw_without_analysis",
            "live job references an evicted raw body without durable authoritative analysis",
            "SELECT j.campaign_id,j.candidate_id,j.job_id,j.result_artifact FROM jobs j "
            "JOIN artifact_retention ar ON ar.artifact_hash=j.result_artifact "
            "WHERE ar.storage_class='raw_simulation' AND ar.body_state='evicted' AND NOT EXISTS ("
            "SELECT 1 FROM analysis_queue q WHERE q.campaign_id=j.campaign_id "
            "AND q.input_artifact=j.result_artifact AND q.status='done' AND EXISTS ("
            "SELECT 1 FROM measurements m WHERE m.campaign_id=q.campaign_id "
            "AND m.input_artifact=q.input_artifact AND m.analysis_version=q.analysis_version))",
            (),
        ),
        (
            "error", "cursor.ahead_of_log",
            "service cursor points beyond the durable event log",
            "SELECT service,last_event_id FROM service_cursors WHERE last_event_id>"
            "COALESCE((SELECT MAX(event_id) FROM events),0)",
            (),
        ),
        (
            "warning", "event.repeated_failure",
            "event consumer has repeatedly failed the same durable event",
            "SELECT service,event_id,attempts,last_error,updated_utc FROM event_failures "
            "WHERE attempts>=3",
            (),
        ),
    ]
    detail_cap = max(1, int(max_detail)) + 1
    for severity, code, message, sql, args in checks:
        for row in _rows(conn, f"SELECT * FROM ({sql}) audit_check LIMIT {detail_cap}", args):
            findings.append(_finding(severity, code, message, **row))

    terminal = tuple(sorted(TERMINAL_CANDIDATE_STATES))
    marks = ",".join("?" for _ in terminal)
    terminal_work = _rows(
        conn,
        "SELECT cc.campaign_id,cc.candidate_id,cc.state,j.job_id reference,j.status,"
        "'simulation' work_type FROM campaign_candidates cc JOIN jobs j "
        "ON j.campaign_id=cc.campaign_id AND j.candidate_id=cc.candidate_id "
        f"WHERE cc.state IN ({marks}) AND j.status IN ('queued','leased') "
        "UNION ALL SELECT cc.campaign_id,cc.candidate_id,cc.state,q.input_artifact,q.status,"
        "'analysis' FROM campaign_candidates cc JOIN analysis_queue q "
        "ON q.campaign_id=cc.campaign_id AND q.candidate_id=cc.candidate_id "
        f"WHERE cc.state IN ({marks}) AND q.status IN ('queued','leased')",
        (*terminal, *terminal),
    )
    for row in terminal_work:
        findings.append(_finding(
            "error", "queue.terminal_candidate_work",
            "terminal candidate still owns queued or leased work", **row,
        ))

    counts = Counter(item["severity"] for item in findings)
    by_code = Counter(item["code"] for item in findings)
    truncated = len(findings) > max_detail
    return {
        "ok": counts["error"] == 0,
        "checked_utc": utc_now(),
        "verify_hashes": bool(verify_hashes),
        "database_artifacts": len(database_artifacts),
        "evicted_artifact_bodies": sum(1 for row in database_artifacts.values()
                                      if row.get("body_state") == "evicted"),
        "blob_files": sum(1 for _ in store.iter_digests()),
        "counts": {key: int(counts.get(key, 0)) for key in ("error", "warning", "info")},
        "by_code": dict(sorted(by_code.items())),
        "findings": findings[:max_detail],
        "findings_truncated": truncated,
    }


def report_exit_code(report: dict, fail_on: str = "error") -> int:
    if fail_on not in SEVERITY_ORDER:
        raise ValueError(f"unknown audit severity threshold: {fail_on}")
    counts = report.get("counts") or {}
    threshold = SEVERITY_ORDER[fail_on]
    for severity, rank in SEVERITY_ORDER.items():
        if rank >= threshold and int(counts.get(severity, 0)) > 0:
            return 2
    return 0
