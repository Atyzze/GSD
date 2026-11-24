from __future__ import annotations

import json
import time
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.repo import Repo, TERMINAL_STATES
from graph_scale_dynamics.domain.model import utc_now


def _raw_rows(repo: Repo, *, limit: int | None = None, after: str | None = None) -> list[dict]:
    clauses = [
        "j.kind='simulate'", "j.status='done'", "j.result_artifact IS NOT NULL",
        "ar.storage_class='raw_simulation'", "ar.body_state='present'",
        "EXISTS (SELECT 1 FROM analysis_queue q WHERE q.campaign_id=j.campaign_id "
        "AND q.input_artifact=j.result_artifact AND q.status='done' AND EXISTS ("
        "SELECT 1 FROM measurements m WHERE m.campaign_id=q.campaign_id "
        "AND m.input_artifact=q.input_artifact AND m.analysis_version=q.analysis_version))",
    ]
    args: list = []
    if after is not None:
        clauses.append("j.result_artifact > ?")
        args.append(str(after))
    order = "j.result_artifact" if after is not None else "a.size_bytes DESC,j.created_utc,j.job_id"
    sql = (
        "SELECT j.job_id,j.campaign_id,j.candidate_id,j.n,j.seed,j.replicate,j.spec_json,"
        "j.result_artifact artifact_hash,a.size_bytes,ar.encoding,ar.compact_artifact,"
        "ar.checkpoint_artifact,cc.state candidate_state "
        "FROM jobs j JOIN artifacts a ON a.artifact_hash=j.result_artifact "
        "JOIN artifact_retention ar ON ar.artifact_hash=j.result_artifact "
        "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id AND cc.candidate_id=j.candidate_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY {order}"
    )
    if limit is not None and int(limit) > 0:
        sql += " LIMIT ?"
        args.append(int(limit))
    return [dict(row) for row in repo.conn.execute(sql, tuple(args)).fetchall()]


def retention_summary(repo: Repo, campaign_id: str | None = None) -> dict:
    where = ""
    args: tuple = ()
    if campaign_id is not None:
        where = (
            "WHERE EXISTS (SELECT 1 FROM jobs j WHERE j.campaign_id=? AND "
            "(j.result_artifact=ar.artifact_hash OR j.result_artifact=ar.source_artifact))"
        )
        args = (str(campaign_id),)
    rows = repo.conn.execute(
        "SELECT ar.storage_class,ar.body_state,COUNT(*) count,"
        "COALESCE(SUM(CASE WHEN ar.body_state='present' THEN a.size_bytes ELSE 0 END),0) present_bytes,"
        "COALESCE(SUM(CASE WHEN ar.body_state='transient' THEN a.size_bytes ELSE 0 END),0) transient_bytes,"
        "COALESCE(SUM(a.size_bytes),0) logical_bytes "
        "FROM artifact_retention ar JOIN artifacts a ON a.artifact_hash=ar.artifact_hash "
        f"{where} GROUP BY ar.storage_class,ar.body_state ORDER BY ar.storage_class,ar.body_state",
        args,
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("count", "present_bytes", "transient_bytes", "logical_bytes"):
            item[key] = int(item.get(key) or 0)
        result.append(item)
    return {"campaign_id": campaign_id, "classes": result}


def _mark_evicted(repo: Repo, artifact_hash: str, *, reason: str) -> bool:
    row = repo.conn.execute(
        "SELECT body_state,detail_json FROM artifact_retention WHERE artifact_hash=? FOR UPDATE",
        (artifact_hash,),
    ).fetchone()
    if row is None:
        return False
    if str(row["body_state"]) == "evicted":
        return True
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        detail = {}
    detail.update({"eviction_reason": reason, "body_verified_before_eviction": True})
    now = utc_now()
    changed = repo.conn.execute(
        "UPDATE artifact_retention SET body_state='evicted',evicted_utc=?,detail_json=?,updated_utc=? "
        "WHERE artifact_hash=? AND body_state IN ('present','transient')",
        (now, json.dumps(detail, sort_keys=True), now, artifact_hash),
    ).rowcount
    return bool(changed)


def evict_analyzed_raw_body(repo: Repo, store: BlobStore, artifact_hash: str) -> dict:
    row = repo.conn.execute(
        "SELECT ar.*,a.size_bytes FROM artifact_retention ar JOIN artifacts a "
        "ON a.artifact_hash=ar.artifact_hash WHERE ar.artifact_hash=?",
        (artifact_hash,),
    ).fetchone()
    if row is None or str(row["storage_class"]) != "raw_simulation":
        return {"artifact": artifact_hash, "evicted": False, "reason": "no_raw_retention_record"}
    if not row["compact_artifact"]:
        return {"artifact": artifact_hash, "evicted": False, "reason": "compact_evidence_missing"}
    state_row = repo.conn.execute(
        "SELECT cc.state FROM jobs j JOIN campaign_candidates cc "
        "ON cc.campaign_id=j.campaign_id AND cc.candidate_id=j.candidate_id "
        "WHERE j.result_artifact=? ORDER BY j.created_utc DESC LIMIT 1",
        (artifact_hash,),
    ).fetchone()
    candidate_terminal = bool(state_row and str(state_row["state"]) in TERMINAL_STATES)
    if not row["checkpoint_artifact"] and not candidate_terminal:
        return {"artifact": artifact_hash, "evicted": False,
                "reason": "active_candidate_checkpoint_missing"}
    done = repo.conn.execute(
        "SELECT 1 FROM analysis_queue q WHERE q.input_artifact=? AND q.status='done' "
        "AND EXISTS (SELECT 1 FROM measurements m WHERE m.campaign_id=q.campaign_id "
        "AND m.input_artifact=q.input_artifact AND m.analysis_version=q.analysis_version) LIMIT 1",
        (artifact_hash,),
    ).fetchone()
    if done is None:
        return {"artifact": artifact_hash, "evicted": False, "reason": "analysis_not_durable"}
    compact = str(row["compact_artifact"])
    if not store.verify_durable(compact):
        return {"artifact": artifact_hash, "evicted": False,
                "reason": "compact_companion_verification_failed", "companion": compact}
    if row["checkpoint_artifact"]:
        checkpoint = str(row["checkpoint_artifact"])
        state = repo.conn.execute(
            "SELECT body_state FROM artifact_retention WHERE artifact_hash=?", (checkpoint,)
        ).fetchone()
        evicted_checkpoint = state is not None and str(state["body_state"]) == "evicted"
        if not evicted_checkpoint and not store.verify(checkpoint):
            return {"artifact": artifact_hash, "evicted": False,
                    "reason": "checkpoint_companion_verification_failed",
                    "companion": checkpoint}
    repo.begin_transaction(attempts=12)
    try:
        _mark_evicted(repo, artifact_hash, reason="analysis_complete")
        repo.commit_durably()
    except Exception:
        repo.conn.rollback_if_open()
        raise
    transient_removed = store.delete_transient(artifact_hash)
    durable_removed = store.delete(artifact_hash)
    removed = bool(transient_removed or durable_removed)
    return {
        "artifact": artifact_hash, "evicted": True, "file_removed": removed,
        "transient_removed": bool(transient_removed),
        "durable_removed": bool(durable_removed),
        "bytes_released": int(row["size_bytes"] or 0) if removed else 0,
        "released_tier": ("tmpfs" if transient_removed and not durable_removed else
                          "durable" if durable_removed and not transient_removed else
                          "mixed" if removed else "none"),
    }


def _checkpoint_eviction_candidates(repo: Repo, limit: int = 32) -> list[dict]:
    marks = ",".join("?" for _ in TERMINAL_STATES)
    sql = (
        "SELECT DISTINCT cp.artifact_hash,a.size_bytes FROM artifact_retention cp "
        "JOIN artifacts a ON a.artifact_hash=cp.artifact_hash "
        "JOIN artifact_retention src ON src.checkpoint_artifact=cp.artifact_hash "
        "JOIN jobs j ON j.result_artifact=src.artifact_hash "
        "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id AND cc.candidate_id=j.candidate_id "
        "WHERE cp.storage_class='resume_checkpoint' AND cp.body_state IN ('present','transient') AND ("
        f"cc.state IN ({marks}) OR EXISTS ("
        "SELECT 1 FROM jobs newer WHERE newer.campaign_id=j.campaign_id "
        "AND newer.candidate_id=j.candidate_id AND newer.n=j.n AND newer.seed=j.seed "
        "AND newer.status='done' AND newer.result_artifact IS NOT NULL "
        "AND newer.exec_proposal_locality=j.exec_proposal_locality "
        "AND newer.exec_sampler_audit=j.exec_sampler_audit "
        "AND newer.exec_sweeps_multiplier > j.exec_sweeps_multiplier"
        ")) AND NOT EXISTS (SELECT 1 FROM jobs live WHERE live.status IN ('queued','leased') "
        "AND live.exec_resume_artifact=cp.artifact_hash) "
        "ORDER BY a.size_bytes DESC LIMIT ?"
    )
    return [dict(row) for row in repo.conn.execute(sql, (*TERMINAL_STATES, int(limit))).fetchall()]


def evict_stale_checkpoints(repo: Repo, store: BlobStore, *, limit: int = 32) -> dict:
    rows = _checkpoint_eviction_candidates(repo, limit=limit)
    released = 0
    evicted = 0
    for row in rows:
        digest = str(row["artifact_hash"])
        repo.begin_transaction(attempts=12)
        try:
            _mark_evicted(repo, digest, reason="terminal_or_superseded_checkpoint")
            repo.commit_durably()
        except Exception:
            repo.conn.rollback_if_open()
            raise
        transient_removed = store.delete_transient(digest)
        durable_removed = store.delete(digest)
        if transient_removed or durable_removed:
            released += int(row["size_bytes"] or 0)
        evicted += 1
    return {"checkpoint_bodies_evicted": evicted, "bytes_released": released}


def _next_window(cursor: dict | None, name: str, keys: list[str], limit: int) -> None:
    if cursor is not None:
        cursor[name] = keys[-1] if len(keys) >= max(1, int(limit)) else ""


def cleanup_evicted_files(repo: Repo, store: BlobStore, *, limit: int = 64,
                          cursor: dict | None = None) -> dict:
    after = str((cursor or {}).get("lingering") or "")
    rows = repo.conn.execute(
        "SELECT ar.artifact_hash,a.size_bytes FROM artifact_retention ar JOIN artifacts a "
        "ON a.artifact_hash=ar.artifact_hash WHERE ar.body_state='evicted' AND ar.artifact_hash > ? "
        "ORDER BY ar.artifact_hash LIMIT ?", (after, int(limit))
    ).fetchall()
    _next_window(cursor, "lingering", [str(row["artifact_hash"]) for row in rows], limit)
    removed = 0
    released = 0
    for row in rows:
        digest = str(row["artifact_hash"])
        try:
            transient_removed = store.delete_transient(digest)
            durable_removed = store.delete(digest)
            if transient_removed or durable_removed:
                removed += 1
                released += int(row["size_bytes"] or 0)
        except OSError:
            continue
    return {"evicted_files_cleaned": removed, "bytes_released": released}


def cleanup_transient_files(repo: Repo, store: BlobStore, *, limit: int = 64,
                            orphan_grace_seconds: int = 3600, cursor: dict | None = None) -> dict:
    removed = 0
    released = 0
    checked = 0
    after = str((cursor or {}).get("orphans") or "")
    window = [d for d in sorted(store.iter_transient_digests() or ()) if d > after][:max(0, int(limit))]
    _next_window(cursor, "orphans", window, limit)
    for digest in window:
        checked += 1
        row = repo.conn.execute(
            "SELECT body_state FROM artifact_retention WHERE artifact_hash=?", (digest,)
        ).fetchone()
        if row is not None and str(row["body_state"]) == "transient":
            continue
        try:
            stat = store.stat(digest)
            size = int(stat.st_size)
        except OSError:
            stat = None
            size = 0
        if row is None and stat is not None:
            age = max(0.0, time.time() - float(stat.st_mtime))
            if age < max(60, int(orphan_grace_seconds)):
                continue
        if store.delete_transient(digest):
            removed += 1
            released += size
    return {"checked": checked, "removed": removed, "bytes_released": released}


def _evict_completed_transient_rows(repo: Repo, store: BlobStore, *, limit: int = 16,
                                    cursor: dict | None = None) -> dict:
    after = str((cursor or {}).get("transient") or "")
    rows = repo.conn.execute(
        "SELECT ar.artifact_hash FROM artifact_retention ar "
        "WHERE ar.storage_class='raw_simulation' AND ar.body_state='transient' "
        "AND EXISTS (SELECT 1 FROM analysis_queue q WHERE q.input_artifact=ar.artifact_hash "
        "AND q.status='done' AND EXISTS (SELECT 1 FROM measurements m "
        "WHERE m.campaign_id=q.campaign_id AND m.input_artifact=q.input_artifact "
        "AND m.analysis_version=q.analysis_version)) AND ar.artifact_hash > ? "
        "ORDER BY ar.artifact_hash LIMIT ?",
        (after, max(0, int(limit))),
    ).fetchall()
    _next_window(cursor, "transient", [str(row["artifact_hash"]) for row in rows], limit)
    evicted = 0
    released = 0
    refused: dict[str, int] = {}
    for row in rows:
        result = evict_analyzed_raw_body(repo, store, str(row["artifact_hash"]))
        if result.get("evicted"):
            evicted += 1
            released += int(result.get("bytes_released") or 0)
        else:
            reason = str(result.get("reason") or "unknown")
            refused[reason] = refused.get(reason, 0) + 1
    return {"evicted": evicted, "bytes_released": released, "refused": refused}


def online_retention_tick(repo: Repo, store: BlobStore, *, raw_limit: int = 8,
                          checkpoint_limit: int = 16, cursor: dict | None = None,
                          checkpoints: bool = True) -> dict:
    after = None if cursor is None else str(cursor.get("raw") or "")
    rows = _raw_rows(repo, limit=raw_limit, after=after)
    _next_window(cursor, "raw", [str(row["artifact_hash"]) for row in rows], raw_limit)
    rows = [row for row in rows if row.get("compact_artifact") and row.get("checkpoint_artifact")]
    raw_evicted = 0
    raw_bytes = 0
    raw_refused: dict[str, int] = {}
    for row in rows:
        result = evict_analyzed_raw_body(repo, store, str(row["artifact_hash"]))
        if result.get("evicted"):
            raw_evicted += 1
            raw_bytes += int(result.get("bytes_released") or 0)
        else:
            reason = str(result.get("reason") or "unknown")
            raw_refused[reason] = raw_refused.get(reason, 0) + 1
    transient = _evict_completed_transient_rows(repo, store, limit=max(raw_limit, 16), cursor=cursor)
    if checkpoints:
        started = time.monotonic()
        checkpoints = evict_stale_checkpoints(repo, store, limit=checkpoint_limit)
        checkpoints["seconds"] = round(time.monotonic() - started, 3)
    else:
        checkpoints = {"skipped": True}
    lingering = cleanup_evicted_files(repo, store, limit=max(raw_limit, checkpoint_limit), cursor=cursor)
    transient_orphans = cleanup_transient_files(repo, store, limit=max(raw_limit, checkpoint_limit, 32),
                                                cursor=cursor)
    return {
        "raw_bodies_evicted": raw_evicted,
        "raw_bytes_released": raw_bytes,
        "raw_refused": raw_refused,
        "transient_completed_cleanup": transient,
        "checkpoint_cleanup": checkpoints,
        "lingering_cleanup": lingering,
        "transient_orphan_cleanup": transient_orphans,
    }
