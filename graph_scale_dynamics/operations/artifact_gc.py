from __future__ import annotations

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.operations.maintenance import exclusive_maintenance

_UNREFERENCED = """
NOT EXISTS (SELECT 1 FROM jobs j WHERE j.result_artifact=a.artifact_hash)
AND NOT EXISTS (
  SELECT 1 FROM measurements m
  WHERE m.input_artifact=a.artifact_hash OR m.curves_artifact=a.artifact_hash
)
AND NOT EXISTS (SELECT 1 FROM analysis_queue q WHERE q.input_artifact=a.artifact_hash)
AND NOT EXISTS (SELECT 1 FROM artifact_producers p WHERE p.artifact_hash=a.artifact_hash)
AND NOT EXISTS (SELECT 1 FROM evidence_audits e WHERE e.artifact_hash=a.artifact_hash)
AND NOT EXISTS (SELECT 1 FROM campaigns c WHERE c.based_on_report_artifact=a.artifact_hash)
AND NOT EXISTS (
  SELECT 1 FROM campaign_archive_runs r
  WHERE (r.compact_json::jsonb)->>'chain_record_artifact'=a.artifact_hash
)
"""
UNTRACKED_GRACE_SECONDS = 3600.0


def _settled(stat, now: float) -> bool:
    return now - float(stat.st_mtime) >= UNTRACKED_GRACE_SECONDS


def _quiescence(repo: Repo) -> dict:
    leased_jobs = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE status='leased'"
    ).fetchone()["c"])
    leased_analysis = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM analysis_queue WHERE status='leased'"
    ).fetchone()["c"])
    leased_rebuilds = int(repo.conn.execute(
        "SELECT COUNT(*) c FROM candidate_evidence_rebuilds WHERE status='leased'"
    ).fetchone()["c"])
    return {
        "paused": repo.get_flag("paused", "0") == "1",
        "leased_jobs": leased_jobs,
        "leased_analysis": leased_analysis,
        "leased_rebuilds": leased_rebuilds,
    }


def _database_garbage(repo: Repo) -> tuple[dict, list[dict]]:
    summary = dict(repo.conn.execute(
        f"SELECT COUNT(*) count,COALESCE(SUM(a.size_bytes),0) bytes "
        f"FROM artifacts a WHERE {_UNREFERENCED}"
    ).fetchone())
    examples = [dict(row) for row in repo.conn.execute(
        f"SELECT a.artifact_hash,a.size_bytes,a.created_utc FROM artifacts a "
        f"WHERE {_UNREFERENCED} ORDER BY a.created_utc,a.artifact_hash LIMIT 20"
    ).fetchall()]
    return {"count": int(summary["count"]), "bytes": int(summary["bytes"])}, examples


def _untracked_blobs(repo: Repo, store: BlobStore) -> tuple[dict, list[dict]]:
    import time
    registered = {row["artifact_hash"] for row in repo.conn.execute(
        "SELECT artifact_hash FROM artifacts"
    ).fetchall()}
    now = time.time()
    count = 0
    size = 0
    examples: list[dict] = []
    for digest in store.iter_digests():
        if digest in registered:
            continue
        try:
            stat = store.stat(digest)
        except OSError:
            continue
        if not _settled(stat, now):
            continue
        blob_size = int(stat.st_size)
        count += 1
        size += blob_size
        if len(examples) < 20:
            examples.append({"artifact_hash": digest, "size_bytes": blob_size})
    return {"count": count, "bytes": size}, examples


def _collect_artifacts_locked(repo: Repo, store: BlobStore, *, apply: bool = False) -> dict:
    quiescence = _quiescence(repo)
    database, database_examples = _database_garbage(repo)
    untracked, untracked_examples = _untracked_blobs(repo, store)
    report = {
        "mode": "apply" if apply else "dry-run",
        "quiescence": quiescence,
        "unreferenced_artifact_rows": database,
        "untracked_blob_files": untracked,
        "stale_temporary_files": len(store.stale_temporaries()),
        "reclaimable_bytes_upper_bound": int(database["bytes"] + untracked["bytes"]),
        "examples": {
            "unreferenced_artifact_rows": database_examples,
            "untracked_blob_files": untracked_examples,
        },
    }
    if not apply:
        return report
    if not quiescence["paused"] or any(
        quiescence[key] for key in ("leased_jobs", "leased_analysis", "leased_rebuilds")
    ):
        raise RuntimeError(
            "refusing artifact GC while publishers may be live: run `python main.py pause` "
            "and wait for leases to drain before applying GC "
            f"(state={quiescence})"
        )

    repo.begin_transaction(attempts=12)
    try:
        deleted_rows = repo.conn.execute(
            f"DELETE FROM artifacts a WHERE {_UNREFERENCED} "
            "RETURNING a.artifact_hash,a.size_bytes"
        ).fetchall()
        repo.commit_durably()
    except Exception:
        repo.conn.rollback_if_open()
        raise

    removed_files = 0
    missing_files = 0
    file_errors: list[dict] = []
    deleted_bytes = 0
    for row in deleted_rows:
        digest = row["artifact_hash"]
        deleted_bytes += int(row["size_bytes"] or 0)
        try:
            if store.delete(digest):
                removed_files += 1
            else:
                missing_files += 1
        except OSError as exc:
            file_errors.append({"artifact_hash": digest, "error": str(exc)})

    registered_after = {row["artifact_hash"] for row in repo.conn.execute(
        "SELECT artifact_hash FROM artifacts"
    ).fetchall()}
    removed_untracked = 0
    untracked_bytes = 0
    import time
    now = time.time()
    for digest in list(store.iter_digests()):
        if digest in registered_after:
            continue
        try:
            stat = store.stat(digest)
            if not _settled(stat, now):
                continue
            size = int(stat.st_size)
            if store.delete(digest):
                removed_untracked += 1
                untracked_bytes += size
        except OSError as exc:
            if len(file_errors) < 100:
                file_errors.append({"artifact_hash": digest, "error": str(exc)})

    removed_temporaries = 0
    for path in store.stale_temporaries():
        try:
            path.unlink()
            removed_temporaries += 1
        except OSError as exc:
            if len(file_errors) < 100:
                file_errors.append({"path": str(path), "error": str(exc)})
    report["applied"] = {
        "artifact_rows_deleted": len(deleted_rows),
        "stale_temporary_files_deleted": removed_temporaries,
        "artifact_row_bytes": deleted_bytes,
        "referenced_blob_files_deleted": removed_files,
        "referenced_blob_files_already_missing": missing_files,
        "untracked_blob_files_deleted": removed_untracked,
        "untracked_blob_bytes": untracked_bytes,
        "filesystem_errors": file_errors[:100],
    }
    return report


def collect_artifacts(repo: Repo, store: BlobStore, *, apply: bool = False) -> dict:
    if not apply:
        return _collect_artifacts_locked(repo, store, apply=False)
    with exclusive_maintenance(repo):
        return _collect_artifacts_locked(repo, store, apply=True)
