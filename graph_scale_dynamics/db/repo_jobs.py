from __future__ import annotations

import json
import random
import time

from graph_scale_dynamics.artifact_store.chain_record import RECORD_CONTRACT
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.domain.model import (
    ATTEMPT_CLASS_MEMORY_RUNAWAY, ATTEMPT_CLASS_WORKER_VANISHED, INTERRUPTED_ATTEMPT_CLASSES, TERMINAL_CANDIDATE_STATES,
    utc_now, vanished_wait_seconds,
)
from graph_scale_dynamics.observability.faults import hit as fault_hit
from graph_scale_dynamics.db.repo_shared import (
    ATTEMPT_CLASS_MEMORY_HARD_STOP, FENCE_OUTRANKS, TERMINAL_STATES, _validated_persisted_seed,
    candidate_may_run_job, retryable_db_error, runnable_candidate_sql,
)


RUNAWAY_REQUEUE_SECONDS = 30


class JobStore:
    def insert_job(self, **f) -> bool:
        now = utc_now()
        seed = _validated_persisted_seed(f["seed"])
        if f["kind"] == "simulate":
            if self.conn.execute(
                "SELECT 1 FROM jobs WHERE job_id=?", (f["job_id"],)
            ).fetchone() is not None:
                return False
            ordinal = self._next_graph_ordinal(f["campaign_id"])
            return self._write(
                "INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,replicate,"
                "graph_ordinal,spec_json,priority,sealed,requested_by,created_utc,updated_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (job_id) DO NOTHING",
                (f["job_id"], f["campaign_id"], f["candidate_id"], f["kind"], f["stage"],
                 f["n"], seed, f.get("replicate", 0), ordinal, json.dumps(f["spec"]),
                 f.get("priority", 100), int(f.get("sealed", False)), f.get("requested_by"),
                 now, now),
            )
        return self._write(
            "INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,replicate,"
            "spec_json,priority,sealed,requested_by,created_utc,updated_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (f["job_id"], f["campaign_id"], f["candidate_id"], f["kind"], f["stage"], f["n"], seed,
             f.get("replicate", 0), json.dumps(f["spec"]), f.get("priority", 100),
             int(f.get("sealed", False)), f.get("requested_by"), now, now),
        )

    def claim_job(self, owner: str, kinds: tuple[str, ...], lease_seconds: int = 60,
                  max_n: int | None = None, campaigns: tuple[str, ...] | None = None,
                  order: str = "priority", min_n: int | None = None, job_id: str | None = None) -> dict | None:
        marks = ",".join("?" for _ in kinds)
        now = utc_now()
        clauses = ["j.status='queued'", f"j.kind IN ({marks})", "c.status='active'",
                   "c.workers_target IS DISTINCT FROM 0",
                   runnable_candidate_sql("cc.state"),
                   "(j.next_attempt_utc IS NULL OR j.next_attempt_utc<=?)"]
        params: list = list(kinds) + list(TERMINAL_STATES) + [now]
        if max_n is not None:
            clauses.append("j.n <= ?")
            params.append(max_n)
        if min_n is not None:
            clauses.append("j.n >= ?")
            params.append(min_n)
        if job_id is not None:
            clauses.append("j.job_id=?")
            params.append(str(job_id))
        if campaigns is not None:
            if not campaigns:
                return None
            campaign_marks = ",".join("?" for _ in campaigns)
            clauses.append(f"j.campaign_id IN ({campaign_marks})")
            params.extend(campaigns)
        from graph_scale_dynamics.db.decision_store import QUEUE_RANK_STEP
        ordering = (
            "RANDOM()" if order == "random" else
            "j.priority,RANDOM()" if order == "priority_random" else
            "j.n DESC,j.priority,j.created_utc,j.job_id" if order == "deepest" else
            f"j.priority / {QUEUE_RANK_STEP},j.created_utc,j.job_id" if order == "oldest" else
            "j.priority,j.created_utc,j.job_id"
        )
        expires_utc = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + lease_seconds)
        )
        sql = (
            "WITH picked AS (SELECT j.job_id FROM jobs j "
            "JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY {ordering} "
            "LIMIT 1 FOR UPDATE OF j SKIP LOCKED) "
            "UPDATE jobs claimed SET status='leased',lease_owner=?,lease_expires_utc=?,"
            "memory_reservation_bytes=0,next_attempt_utc=NULL,"
            "attempts=claimed.attempts+1,lease_generation=claimed.lease_generation+1,"
            "updated_utc=? FROM picked "
            "WHERE claimed.job_id=picked.job_id AND claimed.status='queued' "
            "RETURNING claimed.*"
        )
        for attempt in range(8):
            try:
                row = self.conn.execute(
                    sql, tuple(params) + (owner, expires_utc, utc_now())
                ).fetchone()
                if row is None:
                    return None
                return dict(row) | {
                    "spec": json.loads(row["spec_json"]),
                    "attempt_number": int(row["attempts"]),
                }
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc) or exc.outcome_unknown:
                    raise
                time.sleep((0.04 * (attempt + 1)) * (0.75 + random.random() * 0.5))
        return None

    def renew_lease(self, job_id: str, owner: str, lease_generation: int,
                    lease_seconds: int = 60) -> bool:
        expires_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + lease_seconds))
        return self._write(
            "UPDATE jobs SET lease_expires_utc=? WHERE job_id=? AND lease_owner=? "
            "AND lease_generation=? AND status='leased'",
            (expires_utc, job_id, owner, int(lease_generation)),
        )

    def settle_memory_reservation(self, job_id: str, owner: str, lease_generation: int,
                                  reservation_bytes: int) -> bool:
        return self._write(
            "UPDATE jobs SET memory_reservation_bytes=? WHERE job_id=? "
            "AND lease_owner=? AND lease_generation=? AND status='leased'",
            (max(1, int(reservation_bytes)), job_id, owner, int(lease_generation)),
        )

    def finish_job(self, job_id: str, owner: str, lease_generation: int, status: str,
                   result_artifact: str | None = None, error: str | None = None, *, spent: bool = True,
                   defer_seconds: float | None = None) -> bool:
        next_attempt = None
        if defer_seconds is not None and float(defer_seconds) > 0:
            next_attempt = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + float(defer_seconds)))
        return self._write(
            "UPDATE jobs SET status=?,result_artifact=?,error=?,lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
            "attempts=CASE WHEN ? THEN attempts ELSE GREATEST(0,attempts-1) END,next_attempt_utc=?,"
            "updated_utc=? WHERE job_id=? AND status='leased' AND lease_owner=? "
            "AND lease_generation=?",
            (status, result_artifact, error, bool(spent), next_attempt, utc_now(), job_id, owner,
             int(lease_generation)),
        )

    def stop_job_at_resource_boundary(self, *, job_id: str, owner: str,
                                      lease_generation: int, attempt_id: str,
                                      peak_rss_bytes: int, wall_seconds: float,
                                      hard_limit_bytes: int, error: str,
                                      resource: dict | None = None, requeue: bool = False) -> bool:
        resource = dict(resource or {})
        resource["memory_hard_limit_bytes"] = int(hard_limit_bytes)
        resource["resource_boundary"] = "memory_runaway" if requeue else "memory_hard_cap"
        self.begin_transaction(attempts=12)
        try:
            held = self.conn.execute(
                "SELECT campaign_id,candidate_id FROM jobs WHERE job_id=? "
                "AND status='leased' AND lease_owner=? AND lease_generation=? FOR UPDATE",
                (job_id, owner, int(lease_generation)),
            ).fetchone()
            if held is None:
                self.conn.rollback_if_open()
                return False
            now = utc_now()
            again = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + RUNAWAY_REQUEUE_SECONDS))
            changed = self.conn.execute(
                "UPDATE jobs SET status=?,result_artifact=NULL,error=?,next_attempt_utc=?,"
                "attempts=CASE WHEN ? THEN GREATEST(0,attempts-1) ELSE attempts END,"
                "lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,updated_utc=? WHERE job_id=? "
                "AND status='leased' AND lease_owner=? AND lease_generation=?",
                ("queued" if requeue else "failed", error[:4000], again if requeue else None, bool(requeue), now,
                 job_id, owner, int(lease_generation)),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return False
            self.conn.execute(
                "UPDATE attempts SET finished_utc=?,exit_code=-9,peak_rss_bytes=?,"
                "wall_seconds=?,error=?,user_cpu_seconds=?,system_cpu_seconds=?,"
                "peak_uss_bytes=?,peak_pss_bytes=?,peak_vms_bytes=?,peak_edge_count=?,"
                "final_edge_count=?,final_mean_degree=?,artifact_bytes=?,resource_json=?,"
                "error_class=? "
                "WHERE attempt_id=? AND job_id=? AND finished_utc IS NULL",
                (now, max(0, int(peak_rss_bytes)), max(0.0, float(wall_seconds)),
                 error[:4000], resource.get("user_cpu_seconds"),
                 resource.get("system_cpu_seconds"), resource.get("peak_uss_bytes"),
                 resource.get("peak_pss_bytes"), resource.get("peak_vms_bytes"),
                 resource.get("peak_edge_count"), resource.get("final_edge_count"),
                 resource.get("final_mean_degree"), resource.get("artifact_bytes"),
                 json.dumps(resource), ATTEMPT_CLASS_MEMORY_RUNAWAY if requeue else ATTEMPT_CLASS_MEMORY_HARD_STOP,
                 attempt_id, job_id),
            )
            if requeue:
                self.conn.execute("COMMIT")
                return True
            self.conn.execute(
                "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                ("analysis_ready", json.dumps({
                    "campaign_id": held["campaign_id"],
                    "candidate_id": held["candidate_id"],
                    "resource_hard_stop": True,
                    "phase": "simulation",
                    "job_id": job_id,
                    "observed_peak_rss_bytes": int(peak_rss_bytes),
                    "hard_limit_bytes": int(hard_limit_bytes),
                }), now),
            )
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.rollback_if_open()
            raise

    def commit_job_result(self, *, job_id: str, owner: str, lease_generation: int,
                          digest: str, size: int, media_type: str, meta: dict,
                          analysis_version: str, attempt: dict | None = None,
                          retention: dict | None = None) -> bool:
        self.begin_transaction(attempts=12)
        try:
            held = self.conn.execute(
                "SELECT * FROM jobs WHERE job_id=? AND status='leased' AND lease_owner=? "
                "AND lease_generation=? FOR UPDATE",
                (job_id, owner, int(lease_generation)),
            ).fetchone()
            if held is None:
                self.conn.rollback_if_open()
                return False
            now = utc_now()
            self.conn.execute(
                "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,"
                "meta_json,created_utc) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (digest, size, media_type, job_id, json.dumps(meta), now),
            )
            self.conn.execute(
                "INSERT INTO artifact_producers(artifact_hash,job_id,role,created_utc) "
                "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                (digest, job_id, "simulation", now),
            )
            if retention is not None:
                companion_hashes: dict[str, str | None] = {"compact": None, "checkpoint": None,
                                                           "record": None}
                for key, storage_class, schema in (
                    ("compact", "compact_simulation", "compact-simulation-evidence-v2"),
                    ("checkpoint", "resume_checkpoint", "simulation-resume-checkpoint-v1"),
                    ("record", "chain_record", RECORD_CONTRACT),
                ):
                    companion = retention.get(key)
                    if not companion:
                        continue
                    companion_digest = str(companion["digest"])
                    companion_size = int(companion["size"])
                    companion_hashes[key] = companion_digest
                    self.conn.execute(
                        "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,"
                        "meta_json,created_utc) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                        (companion_digest, companion_size,
                         "application/x-xz" if key == "record" else "application/json", job_id,
                         json.dumps({"schema": schema, "source_artifact": digest,
                                     "storage_encoding": companion.get("encoding", "gzip")}), now),
                    )
                    self.conn.execute(
                        "INSERT INTO artifact_producers(artifact_hash,job_id,role,created_utc) "
                        "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                        (companion_digest, job_id, "simulation", now),
                    )
                    companion_body_state = str(companion.get("body_state") or "present")
                    if companion_body_state not in {"present", "transient"}:
                        raise ValueError(
                            f"unsupported {storage_class} artifact body state: {companion_body_state}"
                        )
                    companion_detail = json.dumps(companion.get("detail") or {}, sort_keys=True)
                    self.conn.execute(
                        "INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,"
                        "encoding,source_artifact,detail_json,created_utc,updated_utc) "
                        "VALUES(?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(artifact_hash) DO UPDATE SET storage_class=excluded.storage_class,"
                        "body_state=excluded.body_state,encoding=excluded.encoding,"
                        "source_artifact=excluded.source_artifact,detail_json=excluded.detail_json,"
                        "evicted_utc=NULL,updated_utc=excluded.updated_utc",
                        (companion_digest, storage_class, companion_body_state,
                         companion.get("encoding", "gzip"), digest, companion_detail, now, now),
                    )
                raw_body_state = str(retention.get("body_state") or "present")
                if raw_body_state not in {"present", "transient"}:
                    raise ValueError(f"unsupported raw artifact body state: {raw_body_state}")
                raw_detail = json.dumps(retention.get("detail") or {}, sort_keys=True)
                self.conn.execute(
                    "INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,encoding,"
                    "compact_artifact,checkpoint_artifact,record_artifact,detail_json,created_utc,updated_utc) "
                    "VALUES(?,'raw_simulation',?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(artifact_hash) DO UPDATE SET storage_class='raw_simulation',"
                    "body_state=excluded.body_state,encoding=excluded.encoding,"
                    "compact_artifact=COALESCE(excluded.compact_artifact,artifact_retention.compact_artifact),"
                    "checkpoint_artifact=COALESCE(excluded.checkpoint_artifact,artifact_retention.checkpoint_artifact),"
                    "record_artifact=COALESCE(excluded.record_artifact,artifact_retention.record_artifact),"
                    "detail_json=excluded.detail_json,evicted_utc=NULL,updated_utc=excluded.updated_utc",
                    (digest, raw_body_state, retention.get("encoding", "gzip"),
                     companion_hashes["compact"], companion_hashes["checkpoint"], companion_hashes["record"],
                     raw_detail, now, now),
                )
            fault_hit("simulation.after_artifact_before_job")
            changed = self.conn.execute(
                "UPDATE jobs SET status='done',result_artifact=?,error=NULL,lease_owner=NULL,"
                "lease_expires_utc=NULL,memory_reservation_bytes=0,updated_utc=? WHERE job_id=? AND status='leased' "
                "AND lease_owner=? AND lease_generation=?",
                (digest, now, job_id, owner, int(lease_generation)),
            )
            if changed.rowcount != 1:
                self.conn.rollback_if_open()
                return False
            fault_hit("simulation.after_job_before_analysis")
            if attempt is not None:
                changed_attempt = self.conn.execute(
                    "UPDATE attempts SET finished_utc=?,exit_code=?,peak_rss_bytes=?,"
                    "wall_seconds=?,error=?,user_cpu_seconds=?,system_cpu_seconds=?,"
                    "peak_uss_bytes=?,peak_pss_bytes=?,peak_vms_bytes=?,peak_edge_count=?,"
                    "final_edge_count=?,final_mean_degree=?,artifact_bytes=?,resource_json=? "
                    "WHERE attempt_id=? AND job_id=? AND finished_utc IS NULL",
                    (now, int(attempt.get("exit_code", 0)),
                     int(attempt.get("peak_rss_bytes") or 0),
                     float(attempt.get("wall_seconds") or 0.0), attempt.get("error"),
                     attempt.get("user_cpu_seconds"), attempt.get("system_cpu_seconds"),
                     attempt.get("peak_uss_bytes"), attempt.get("peak_pss_bytes"),
                     attempt.get("peak_vms_bytes"), attempt.get("peak_edge_count"),
                     attempt.get("final_edge_count"), attempt.get("final_mean_degree"),
                     int(attempt.get("artifact_bytes") or size),
                     json.dumps(attempt.get("resource") or {}),
                     attempt["attempt_id"], job_id),
                )
                if changed_attempt.rowcount != 1:
                    self.conn.rollback_if_open()
                    return False
            self.conn.execute(
                "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,"
                "candidate_id,n,seed,producer_job,priority,status,created_utc,updated_utc) "
                "VALUES(?,?,?,?,?,?,?,?, 'queued',?,?) "
                "ON CONFLICT(campaign_id,input_artifact,analysis_version) DO UPDATE SET "
                "candidate_id=excluded.candidate_id,n=excluded.n,seed=excluded.seed,"
                "producer_job=excluded.producer_job,priority=LEAST(analysis_queue.priority,excluded.priority),"
                "status=CASE WHEN analysis_queue.status='failed' "
                "AND COALESCE(analysis_queue.error,'') LIKE 'TRANSIENT_RAW_LOST:%' THEN 'queued' "
                "WHEN analysis_queue.status IN ('done','failed','cancelled') "
                "THEN analysis_queue.status ELSE 'queued' END,"
                "attempts=CASE WHEN analysis_queue.status='failed' "
                "AND COALESCE(analysis_queue.error,'') LIKE 'TRANSIENT_RAW_LOST:%' THEN 0 "
                "ELSE analysis_queue.attempts END,"
                
                "lease_owner=NULL,claim_token=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
                "next_attempt_utc=CASE WHEN analysis_queue.status='queued' "
                "THEN analysis_queue.next_attempt_utc ELSE NULL END,"
                "error=CASE WHEN analysis_queue.status='failed' "
                "AND COALESCE(analysis_queue.error,'') LIKE 'TRANSIENT_RAW_LOST:%' "
                "THEN NULL ELSE analysis_queue.error END,"
                "updated_utc=excluded.updated_utc",
                (held["campaign_id"], digest, analysis_version, held["candidate_id"],
                 int(held["n"]), int(held["seed"]), job_id, int(held["priority"]), now, now),
            )
            fault_hit("simulation.after_analysis_enqueue_before_commit")
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.rollback_if_open()
            raise

    def requeue_cancelled_job(self, job_id: str, priority: int) -> bool:
        return self._write(
            "UPDATE jobs SET status='queued',attempts=0,lease_owner=NULL,lease_expires_utc=NULL,"
            "memory_reservation_bytes=0,next_attempt_utc=NULL,error=NULL,priority=?,updated_utc=? "
            "WHERE job_id=? AND status='cancelled'",
            (int(priority), utc_now(), str(job_id)),
        )

    def release_job(self, job_id: str, owner: str, lease_generation: int,
                    defer_seconds: int | None = None) -> bool:
        now = utc_now()
        next_attempt = None
        if defer_seconds is not None and int(defer_seconds) > 0:
            next_attempt = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(defer_seconds))
            )
        return self._write(
            "UPDATE jobs SET status=CASE WHEN EXISTS (SELECT 1 FROM campaigns c "
            "JOIN campaign_candidates cc ON cc.campaign_id=jobs.campaign_id "
            "AND cc.candidate_id=jobs.candidate_id "
            "WHERE c.campaign_id=jobs.campaign_id AND c.status='active' "
            "AND " + runnable_candidate_sql("cc.state") + ") THEN 'queued' ELSE 'cancelled' END,"
            "lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
            "next_attempt_utc=CASE WHEN EXISTS (SELECT 1 FROM campaigns c "
            "JOIN campaign_candidates cc ON cc.campaign_id=jobs.campaign_id "
            "AND cc.candidate_id=jobs.candidate_id WHERE c.campaign_id=jobs.campaign_id "
            "AND c.status='active' "
            "AND " + runnable_candidate_sql("cc.state") + ") THEN ? ELSE NULL END,"
            "attempts=GREATEST(0,attempts-1),updated_utc=? "
            "WHERE job_id=? AND lease_owner=? AND lease_generation=? AND status='leased'",
            (*TERMINAL_STATES, *TERMINAL_STATES, next_attempt, now,
             job_id, owner, int(lease_generation)),
        )

    def leased_count(self, *, min_n: int | None = None, max_n: int | None = None) -> int:
        terminal_marks = ",".join("?" for _ in TERMINAL_STATES)
        clauses, params = ["j.status='leased'", "j.kind='simulate'", "c.status='active'",
                           f"cc.state NOT IN ({terminal_marks})"], list(TERMINAL_STATES)
        if min_n is not None:
            clauses.append("j.n >= ?")
            params.append(min_n)
        if max_n is not None:
            clauses.append("j.n <= ?")
            params.append(max_n)
        return self.conn.execute(
            f"SELECT COUNT(*) c FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
            f"WHERE {' AND '.join(clauses)}", params
        ).fetchone()["c"]

    def analysis_leased_count(self, *, min_n: int | None = None, max_n: int | None = None) -> int:
        clauses, params = ["status='leased'", "lease_expires_utc>=?"], [utc_now()]
        if min_n is not None:
            clauses.append("n >= ?")
            params.append(int(min_n))
        if max_n is not None:
            clauses.append("n <= ?")
            params.append(int(max_n))
        return int(self.conn.execute(
            f"SELECT COUNT(*) c FROM analysis_queue WHERE {' AND '.join(clauses)}", params).fetchone()["c"])

    PREEMPT_CAMPAIGN_MISSING = "preempted_campaign_missing"
    PREEMPT_CAMPAIGN_INACTIVE = "preempted_campaign_inactive"
    PREEMPT_CANDIDATE_TERMINAL = "preempted_candidate_terminal"
    PREEMPT_WORKER_CAP = "preempted_worker_cap"

    def preempt_reason(self, job: dict) -> str | None:
        row = self.conn.execute(
            "SELECT c.status,c.workers_target,cc.state FROM campaigns c "
            "JOIN campaign_candidates cc ON cc.campaign_id=c.campaign_id "
            "WHERE c.campaign_id=? AND cc.candidate_id=?",
            (job["campaign_id"], job["candidate_id"]),
        ).fetchone()
        if not row:
            return self.PREEMPT_CAMPAIGN_MISSING
        if row["status"] != "active":
            return self.PREEMPT_CAMPAIGN_INACTIVE
        if not candidate_may_run_job(str(row["state"])):
            return self.PREEMPT_CANDIDATE_TERMINAL
        if row["workers_target"] is None:
            return None
        leased = self.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE campaign_id=? AND status='leased'", (job["campaign_id"],)
        ).fetchone()["c"]
        overage = leased - int(row["workers_target"])
        from graph_scale_dynamics.db.share_floor import share_waiting
        if overage <= 0 or not share_waiting(self.conn, job["campaign_id"]):
            return None
        newer = self.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE campaign_id=? AND status='leased' AND "
            "(created_utc>? OR (created_utc=? AND job_id>?))",
            (job["campaign_id"], job["created_utc"], job["created_utc"], job["job_id"]),
        ).fetchone()["c"]
        return self.PREEMPT_WORKER_CAP if newer < overage else None

    def reclaim_expired(self, batch_size: int = 200) -> int:
        now = utc_now()
        batch_size = max(1, min(5000, int(batch_size)))
        vanished_events: list[dict] = []
        changed_count = 0
        self.begin_transaction(attempts=12)
        try:
            expired = self.conn.execute(
                "SELECT job_id,campaign_id,candidate_id,n,lease_owner,lease_generation,lease_expires_utc,"
                "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=jobs.job_id AND a.error_class=?) AS vanished "
                "FROM jobs WHERE status='leased' AND lease_expires_utc<? "
                "ORDER BY lease_expires_utc,job_id LIMIT ? FOR UPDATE SKIP LOCKED",
                (ATTEMPT_CLASS_WORKER_VANISHED, now, batch_size),
            ).fetchall()
            for row in expired:
                times = int(row["vanished"] or 0) + 1
                wait = vanished_wait_seconds(times)
                changed = self.conn.execute(
                    "UPDATE jobs SET status='queued',lease_owner=NULL,lease_expires_utc=NULL,memory_reservation_bytes=0,"
                    "next_attempt_utc=?,updated_utc=? WHERE job_id=? AND status='leased' "
                    "AND lease_owner IS NOT DISTINCT FROM ?::text "
                    "AND lease_generation=? AND lease_expires_utc=? AND lease_expires_utc<?",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + wait)), utc_now(),
                     row["job_id"], row["lease_owner"], int(row["lease_generation"]), row["lease_expires_utc"], now),
                )
                if changed.rowcount != 1:
                    continue
                changed_count += 1
                self.conn.execute(
                    "UPDATE attempts SET finished_utc=?,exit_code=COALESCE(exit_code,-1),error=?,error_class=? "
                    "WHERE job_id=? AND finished_utc IS NULL",
                    (utc_now(), f"its worker stopped renewing its lease (the {times}. time for this seed); the seed "
                     f"runs again in {wait:.0f} s from its saved state, and the law is not charged for it",
                     ATTEMPT_CLASS_WORKER_VANISHED, row["job_id"]))
                vanished_events.append({"job_id": row["job_id"], "campaign_id": row["campaign_id"],
                                        "candidate_id": row["candidate_id"], "n": row["n"], "times": times,
                                        "wait_seconds": wait, "worker": row["lease_owner"]})
            expired_analysis = self.conn.execute(
                "SELECT q.campaign_id,q.input_artifact,q.analysis_version,q.candidate_id,"
                "q.producer_job,q.attempts,q.max_attempts,q.lease_owner,q.claim_token,"
                "q.lease_expires_utc,c.status campaign_status,cc.state candidate_state "
                "FROM analysis_queue q JOIN campaigns c ON c.campaign_id=q.campaign_id "
                "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id "
                "AND cc.candidate_id=q.candidate_id WHERE q.status='leased' "
                "AND q.lease_expires_utc<? ORDER BY q.lease_expires_utc,q.input_artifact "
                "LIMIT ? FOR UPDATE OF q SKIP LOCKED",
                (now, batch_size),
            ).fetchall()
            for row in expired_analysis:
                eligible = (row["campaign_status"] == "active" and
                            row["candidate_state"] not in TERMINAL_CANDIDATE_STATES)
                retry = eligible and int(row["attempts"]) < int(row["max_attempts"])
                status = "queued" if retry else ("failed" if eligible else "cancelled")
                next_attempt = None
                if retry:
                    delay = min(300, 5 * (2 ** max(0, int(row["attempts"]) - 1)))
                    next_attempt = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + delay)
                    )
                changed = self.conn.execute(
                    "UPDATE analysis_queue SET status=?,lease_owner=NULL,claim_token=NULL,"
                    "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=?,error='analysis lease expired',"
                    "error_class='lease_expired',updated_utc=? WHERE campaign_id=? "
                    "AND input_artifact=? AND analysis_version=? AND status='leased' "
                    "AND lease_owner IS NOT DISTINCT FROM ?::text "
                    "AND claim_token IS NOT DISTINCT FROM ?::text "
                    "AND lease_expires_utc=? AND lease_expires_utc<?",
                    (status, next_attempt, utc_now(), row["campaign_id"],
                     row["input_artifact"], row["analysis_version"], row["lease_owner"],
                     row["claim_token"], row["lease_expires_utc"], now),
                )
                if changed.rowcount != 1:
                    continue
                changed_count += 1
                if status == "failed":
                    self.conn.execute(
                        "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                        ("analysis_failed", json.dumps({
                            "job_id": row["producer_job"],
                            "campaign_id": row["campaign_id"],
                            "candidate_id": row["candidate_id"],
                            "artifact": row["input_artifact"],
                            "retry": False, "status": "failed",
                            "error": "analysis lease expired repeatedly",
                            "error_class": "lease_expired",
                            "attempts": int(row["attempts"]),
                            "max_attempts": int(row["max_attempts"]),
                        }), utc_now()),
                    )
            expired_rebuilds = self.conn.execute(
                "SELECT campaign_id,candidate_id,analysis_version,attempts,max_attempts,"
                "lease_owner,claim_token,lease_expires_utc FROM candidate_evidence_rebuilds "
                "WHERE status='leased' AND lease_expires_utc<? "
                "ORDER BY lease_expires_utc,campaign_id,candidate_id LIMIT ? "
                "FOR UPDATE SKIP LOCKED",
                (now, batch_size),
            ).fetchall()
            for row in expired_rebuilds:
                retry = int(row["attempts"]) < int(row["max_attempts"])
                status = "queued" if retry else "failed"
                next_attempt = None
                if retry:
                    delay = min(300, 2 ** max(0, int(row["attempts"]) - 1))
                    next_attempt = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + delay)
                    )
                changed = self.conn.execute(
                    "UPDATE candidate_evidence_rebuilds SET status=?,lease_owner=NULL,"
                    "claim_token=NULL,lease_expires_utc=NULL,next_attempt_utc=?,"
                    "error='evidence rebuild lease expired',updated_utc=? "
                    "WHERE campaign_id=? AND candidate_id=? AND analysis_version=? "
                    "AND status='leased' AND lease_owner IS NOT DISTINCT FROM ?::text "
                    "AND claim_token IS NOT DISTINCT FROM ?::text "
                    "AND lease_expires_utc=? AND lease_expires_utc<?",
                    (status, next_attempt, utc_now(), row["campaign_id"], row["candidate_id"],
                     row["analysis_version"], row["lease_owner"], row["claim_token"],
                     row["lease_expires_utc"], now),
                )
                if changed.rowcount == 1:
                    changed_count += 1
                    if not retry:
                        self.conn.execute(
                            "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                            ("analysis_failed", json.dumps({
                                "campaign_id": row["campaign_id"],
                                "candidate_id": row["candidate_id"],
                                "analysis_version": row["analysis_version"],
                                "stage": "evidence_rebuild", "retry": False,
                                "error": "evidence rebuild lease expired repeatedly",
                            }), utc_now()),
                        )
            for payload in vanished_events:
                self.conn.execute(
                    "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                    ("worker_vanished", json.dumps(payload), utc_now()),
                )
            self.conn.execute("COMMIT")
            return changed_count
        except Exception:
            self.conn.rollback_if_open()
            raise

    def record_attempt(self, attempt_id: str, job_id: str, number: int, worker: str) -> None:
        from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
        self._write(
            "INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,build_number,runtime_fingerprint,"
            "memory_reservation_bytes) VALUES(?,?,?,?,?,?,?,"
            "(SELECT memory_reservation_bytes FROM jobs WHERE job_id=?)) ON CONFLICT DO NOTHING",
            (attempt_id, job_id, number, worker, utc_now(), int(BUILD_NUMBER), runtime_fingerprint(), job_id),
        )

    def close_attempt(self, attempt_id: str, exit_code: int, peak_rss: int, wall: float,
                      error: str | None, resource: dict | None = None,
                      error_class: str | None = None) -> None:
        resource = dict(resource or {})
        if error is not None and not error_class:
            error_class = "unknown"
        kept = ",".join(f"'{name}'" for name in INTERRUPTED_ATTEMPT_CLASSES)
        self._write(
            "UPDATE attempts SET finished_utc=?,exit_code=?,peak_rss_bytes=?,wall_seconds=?,error=?,"
            "user_cpu_seconds=?,system_cpu_seconds=?,peak_uss_bytes=?,peak_pss_bytes=?,"
            "peak_vms_bytes=?,peak_edge_count=?,final_edge_count=?,final_mean_degree=?,"
            "artifact_bytes=?,resource_json=?,"
            f"error_class=CASE WHEN ? AND finished_utc IS NOT NULL AND error_class IN ({kept}) THEN error_class "
            "ELSE ? END WHERE attempt_id=?",
            (utc_now(), exit_code, peak_rss, wall, error,
             resource.get("user_cpu_seconds"), resource.get("system_cpu_seconds"),
             resource.get("peak_uss_bytes"), resource.get("peak_pss_bytes"),
             resource.get("peak_vms_bytes"), resource.get("peak_edge_count"),
             resource.get("final_edge_count"), resource.get("final_mean_degree"),
             resource.get("artifact_bytes"), json.dumps(resource),
             error_class is None or error_class in FENCE_OUTRANKS, error_class, attempt_id),
        )

    def job_failure_classes(self, job_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT error_class FROM attempts WHERE job_id=? AND finished_utc IS NOT NULL "
            "AND error IS NOT NULL ORDER BY started_utc, number", (job_id,),
        ).fetchall()
        return [str(row["error_class"] or "unknown") for row in rows]
