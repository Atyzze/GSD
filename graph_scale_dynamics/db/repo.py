from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path

from graph_scale_dynamics.db.connection import DatabaseOperationalError, connect_database, resolve_target
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.db.repo_shared import (
    ATTEMPT_CLASS_FLEET_PAUSED, ATTEMPT_CLASS_FLEET_SHUTDOWN, ATTEMPT_CLASS_LEASE_LOST,
    ATTEMPT_CLASS_MEMORY_HARD_STOP, ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED, FENCE_OUTRANKS,
    FENCE_PAUSED_CLASS, TERMINAL_STATES, _probe_seconds_columns, _service_role, _validated_search_seed,
    analyzer_identity, candidate_may_run_job, heartbeat_interval_seconds, retryable_db_error,
)
from graph_scale_dynamics.db.repo_analysis import AnalysisStore
from graph_scale_dynamics.db.repo_campaigns import CampaignStore
from graph_scale_dynamics.db.repo_candidates import CandidateStore
from graph_scale_dynamics.db.repo_jobs import JobStore
from graph_scale_dynamics.db.repo_records import RecordStore

__all__ = [
    "ATTEMPT_CLASS_FLEET_PAUSED",
    "ATTEMPT_CLASS_FLEET_SHUTDOWN",
    "ATTEMPT_CLASS_LEASE_LOST",
    "ATTEMPT_CLASS_MEMORY_HARD_STOP",
    "ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED",
    "FENCE_OUTRANKS",
    "FENCE_PAUSED_CLASS",
    "ROOT",
    "Repo",
    "SCHEMA_FILE",
    "SchemaLedgerMismatch",
    "TERMINAL_STATES",
    "_probe_seconds_columns",
    "_validated_search_seed",
    "analyzer_identity",
    "candidate_may_run_job",
    "connect",
    "heartbeat_interval_seconds",
    "init_db",
    "retryable_db_error",
    "schema_checksum",
    "utc_now",
]

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "resources" / "schema" / "schema.sql"


def connect(db_target: str | Path):
    return connect_database(db_target)


class SchemaLedgerMismatch(RuntimeError):
    pass


def schema_checksum() -> str:
    return hashlib.sha256(SCHEMA_FILE.read_bytes()).hexdigest()


def init_db(db_target: str | Path) -> None:
    resolved = resolve_target(db_target)
    conn = connect(resolved)
    migration_lock = "gsd:schema-migrations"
    migration_lock_held = False
    try:
        conn.execute("SELECT pg_advisory_lock(hashtext(?))", (migration_lock,))
        migration_lock_held = True
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_utc TEXT NOT NULL)"
        )
        body = SCHEMA_FILE.read_text(encoding="utf-8")
        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
        ledger = {
            str(row["version"]): str(row["checksum"])
            for row in conn.execute("SELECT version,checksum FROM schema_migrations").fetchall()
        }
        if ledger == {SCHEMA_FILE.name: checksum}:
            return
        if ledger:
            foreign = sorted(v for v in ledger if v != SCHEMA_FILE.name)
            if foreign:
                detail = (
                    f"the ledger lists {len(foreign)} migration script(s) the shipped schema does not "
                    f"know ({foreign[0]} .. {foreign[-1]})"
                )
            else:
                detail = (
                    f"{SCHEMA_FILE.name} was applied at checksum "
                    f"{ledger[SCHEMA_FILE.name][:12]} but the shipped file is {checksum[:12]}"
                )
            raise SchemaLedgerMismatch(
                f"schema ledger does not match the shipped schema: {detail}. "
                "There is no in-place upgrade. Archive what you need "
                "(`main.py campaign archive`), stop the runtime, remove `instance/` "
                "`var/` and `.env.postgres`, and run `main.py init` on a fresh database."
            )
        conn.execute("BEGIN")
        try:
            conn.executescript(body)
            conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_utc) VALUES(?,?,?)",
                (SCHEMA_FILE.name, checksum, utc_now()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.rollback_if_open()
            raise
    finally:
        try:
            if migration_lock_held:
                conn.execute("SELECT pg_advisory_unlock(hashtext(?))", (migration_lock,))
        finally:
            conn.close()


class Repo(CampaignStore, CandidateStore, JobStore, AnalysisStore, RecordStore):
    def __init__(self, db_path: str | Path):
        self.db_target = resolve_target(db_path)
        self.conn = connect(self.db_target)
        self.backend = self.conn.backend
        self._closed = False
        self._heartbeat_interval_seconds = heartbeat_interval_seconds()
        self._next_heartbeat_at = time.monotonic() + random.uniform(0.0, min(2.0, self._heartbeat_interval_seconds))
        self._scheduler_publish_interval_seconds = max(ticks(1), float(os.environ.get("GSD_SCHEDULER_PUBLISH_SECONDS", str(ticks(1)))))
        self._next_scheduler_publish_at = 0.0
        self._last_scheduler_critical_signature: tuple[bool, int, int] | None = None
        self._runtime_imports_digests: dict[str, str] = {}
        self._child_import_unions: dict[str, set[str]] = {}

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.conn.close()
        finally:
            self._closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> "Repo":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def commit_durably(self) -> None:
        self.conn.execute("SET LOCAL synchronous_commit = on")
        self.conn.execute("COMMIT")

    def begin_transaction(self, attempts: int = 8) -> None:
        if self.conn.in_transaction:
            return
        last: DatabaseOperationalError | None = None
        for attempt in range(max(1, attempts)):
            try:
                self.conn.execute("BEGIN")
                return
            except DatabaseOperationalError as exc:
                self.conn.rollback_if_open()
                if not retryable_db_error(exc):
                    raise
                last = exc
                time.sleep(min(1.0, 0.05 * (2 ** attempt)))
        raise DatabaseOperationalError(
            f"database remained busy after {max(1, attempts)} attempts: {last}",
            transient=True,
        )


    def _next_graph_ordinal(self, campaign_id: str) -> int:
        row = self.conn.execute(
            "UPDATE campaign_graph_counter SET next_ordinal = next_ordinal + 1 "
            "WHERE campaign_id=? RETURNING next_ordinal - 1 AS ordinal",
            (str(campaign_id),),
        ).fetchone()
        if row is not None:
            return int(row["ordinal"])
        self.conn.execute(
            "INSERT INTO campaign_graph_counter(campaign_id,next_ordinal) VALUES(?,2) "
            "ON CONFLICT (campaign_id) DO NOTHING",
            (str(campaign_id),),
        )
        row = self.conn.execute(
            "SELECT next_ordinal - 1 AS ordinal FROM campaign_graph_counter WHERE campaign_id=?",
            (str(campaign_id),),
        ).fetchone()
        return int(row["ordinal"]) if row else 1

    def _write(self, sql: str, args=(), attempts: int = 12) -> bool:
        if self.conn.in_transaction:
            cursor = self.conn.execute(sql, args)
            return cursor.rowcount > 0
        last: DatabaseOperationalError | None = None
        for attempt in range(max(1, attempts)):
            try:
                cursor = self.conn.execute(sql, args)
                return cursor.rowcount > 0
            except DatabaseOperationalError as exc:
                self.conn.rollback_if_open()
                if not retryable_db_error(exc) or exc.outcome_unknown:
                    raise
                last = exc
                base = min(1.5, 0.025 * (2 ** attempt))
                time.sleep(base * (0.75 + 0.5 * random.random()))
        raise DatabaseOperationalError(
            f"write kept failing because database is busy: {sql[:60]} ({last})",
            transient=True,
        )

    def emit(self, topic: str, payload: dict) -> None:
        self._write(
            "INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
            (topic, json.dumps(payload), utc_now()),
        )

    def insert_proposal_assessment(self, campaign_id: str, candidate_id: str,
                                   version: str, source: str, mode: str,
                                   assessment: dict) -> bool:
        if mode not in {"off", "shadow", "active"}:
            raise ValueError(
                f"invalid proposal assessment mode {mode!r}; expected off, shadow, or active"
            )
        return self._write(
            "INSERT INTO proposal_assessments(campaign_id,candidate_id,version,source,mode,"
            "family_id,score,would_admit,assessment_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (campaign_id, candidate_id, version, source, mode,
             assessment["family_id"], float(assessment.get("score") or 0.0),
             int(bool(assessment.get("would_admit"))), json.dumps(assessment), utc_now()),
        )

    def insert_proposal_exposure(self, campaign_id: str, exposure: dict) -> bool:
        return self._write(
            "INSERT INTO proposal_exposures(campaign_id,event_id,version,pool_id,pool_index,"
            "source,lineage_parent,selected,candidate_id,dependence_unit_id,dependence_unit_label,"
            "coordinates_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (campaign_id, exposure["event_id"], exposure["version"], exposure["pool_id"],
             int(exposure["pool_index"]), exposure["source"], exposure.get("lineage_parent"),
             int(bool(exposure.get("selected"))), exposure.get("candidate_id"),
             exposure["dependence_unit_id"], exposure["dependence_unit_label"],
             json.dumps(exposure["coordinates"]), utc_now()),
        )

    def proposal_exposures(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM proposal_exposures WHERE campaign_id=? ORDER BY created_utc,pool_id,pool_index",
            (campaign_id,),
        ).fetchall()
        return [dict(row) | {"selected": bool(row["selected"]),
                             "coordinates": json.loads(row["coordinates_json"])} for row in rows]

    def heartbeat(self, service: str, detail: dict | None = None, *, paced: bool = False) -> bool:
        now = time.monotonic()
        if now < self._next_heartbeat_at and not paced:
            return False
        self._next_heartbeat_at = now + self._heartbeat_interval_seconds
        try:
            self.conn.execute(
                "INSERT INTO service_heartbeats(service,pid,sampled_utc,detail_json) VALUES(?,?,?,?) "
                "ON CONFLICT(service) DO UPDATE SET pid=excluded.pid,sampled_utc=excluded.sampled_utc,"
                "detail_json=excluded.detail_json",
                (service, os.getpid(), utc_now(), json.dumps(detail or {})),
            )
            self.publish_runtime_imports(service)
            return True
        except DatabaseOperationalError as exc:
            if not retryable_db_error(exc):
                raise
            return False

    def publish_runtime_imports(self, service: str, names=None) -> bool:
        from graph_scale_dynamics.observability.evidence_sources import (
            RUNTIME_IMPORTS_PREFIX, runtime_import_record,
        )
        service = _service_role(service)
        if names is not None:
            union = self._child_import_unions.setdefault(str(service), set())
            union.update(str(n) for n in names)
            record = runtime_import_record(service, sorted(union))
            digest_key = f"child:{service}"
        else:
            record = runtime_import_record(service)
            digest_key = "self"
        if record["digest"] == self._runtime_imports_digests.get(digest_key):
            return False
        try:
            self.set_flag(RUNTIME_IMPORTS_PREFIX + str(service), json.dumps(record, sort_keys=True))
        except DatabaseOperationalError as exc:
            if not retryable_db_error(exc):
                raise
            return False
        self._runtime_imports_digests[digest_key] = record["digest"]
        return True

    def wait_for_work(self, *args, **kw) -> bool:
        return self.conn.wait_for_work(*args, **kw)

    def database_activity(self) -> dict:
        rows = self.conn.execute(
            "SELECT COALESCE(NULLIF(application_name,''),'unlabeled') application_name,"
            "state,COALESCE(wait_event_type,'CPU') wait_type,"
            "COALESCE(wait_event,'running') wait_event,COUNT(*) count "
            "FROM pg_stat_activity WHERE datname=current_database() "
            "GROUP BY 1,2,3,4 ORDER BY COUNT(*) DESC,application_name"
        ).fetchall()
        limit = int(self.conn.execute(
            "SELECT current_setting('max_connections')::INTEGER n"
        ).fetchone()["n"])
        groups = [dict(row) for row in rows]
        return {
            "connections": sum(int(row["count"]) for row in rows),
            "active": sum(int(row["count"]) for row in rows if row["state"] == "active"),
            "idle": sum(int(row["count"]) for row in rows if row["state"] == "idle"),
            "limit": limit,
            "groups": groups,
        }

    @staticmethod
    def _advisory_key(name: str) -> int:
        return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)

    def acquire_service_lock(self, name: str) -> bool:
        row = self.conn.execute("SELECT pg_try_advisory_lock(?) AS acquired",
                                (self._advisory_key(name),)).fetchone()
        if row["acquired"]:
            self.conn.keep_session_lock(self._advisory_key(name), name)
        return bool(row["acquired"])

    def service_lock_holder(self, name: str) -> dict | None:
        key = self._advisory_key(name) & 0xFFFFFFFFFFFFFFFF
        row = self.conn.execute(
            "SELECT a.pid, a.backend_start, a.state, a.application_name "
            "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
            "WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1 "
            "AND l.classid = ? AND l.objid = ? AND l.database = "
            "(SELECT oid FROM pg_database WHERE datname = current_database())",
            (key >> 32, key & 0xFFFFFFFF),
        ).fetchone()
        return dict(row) if row else None

    def terminate_service_lock_holder(self, name: str) -> int | None:
        holder = self.service_lock_holder(name)
        if not holder:
            return None
        self.conn.execute("SELECT pg_terminate_backend(?)", (int(holder["pid"]),))
        return int(holder["pid"])

    def release_service_lock(self, name: str) -> None:
        self.conn.forget_session_lock(self._advisory_key(name))
        self.release_advisory_lock(name)

    def acquire_advisory_lock(self, name: str) -> None:
        self.conn.execute("SELECT pg_advisory_lock(?)", (self._advisory_key(name),))
        hold = getattr(self.conn, "hold_lock", None)
        if hold is not None:
            hold(self._advisory_key(name), name)

    def wait_for_advisory_lock(self, name: str, *, poll_seconds: float = 0.5) -> None:
        while not self.conn.execute("SELECT pg_try_advisory_lock(?) AS acquired",
                                    (self._advisory_key(name),)).fetchone()["acquired"]:
            time.sleep(poll_seconds)
        hold = getattr(self.conn, "hold_lock", None)
        if hold is not None:
            hold(self._advisory_key(name), name)

    def release_advisory_lock(self, name: str) -> None:
        drop = getattr(self.conn, "drop_lock", None)
        if drop is not None:
            drop(self._advisory_key(name))
        self.conn.execute("SELECT pg_advisory_unlock(?)", (self._advisory_key(name),))

    def acquire_blocking_lock(self, name: str) -> None:
        self.acquire_advisory_lock(name)

    def lock_candidate(self, campaign_id: str, candidate_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM campaign_candidates WHERE campaign_id=? AND candidate_id=? FOR UPDATE",
            (campaign_id, candidate_id),
        ).fetchone()
        return row is not None
