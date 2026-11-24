from __future__ import annotations

from pathlib import Path

import pytest

from graph_scale_dynamics.db.connection import connect_database
from graph_scale_dynamics.db.repo import SCHEMA_FILE, Repo, SchemaLedgerMismatch, init_db, schema_checksum
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_folder_schema_connection_is_unix_socket_and_uses_requested_search_path(
    isolated_postgres_schema,
):
    conn = connect_database(isolated_postgres_schema.reference)
    try:
        row = conn.execute(
            "SELECT inet_server_addr() AS tcp_addr, current_schema() AS schema"
        ).fetchone()
        assert row["tcp_addr"] is None
        assert row["schema"] == isolated_postgres_schema.schema
    finally:
        conn.close()


def test_two_test_schemas_are_data_isolated(postgres_schema_factory):
    left = postgres_schema_factory()
    right = postgres_schema_factory()
    init_db(left.dsn)
    init_db(right.dsn)

    spec = {"mode": "bounded", "ladder": [16]}
    with Repo(left.dsn) as repo:
        repo.insert_campaign("camp-isolated", spec, content_hash(spec))
        assert repo.campaign("camp-isolated") is not None
    with Repo(right.dsn) as repo:
        assert repo.campaign("camp-isolated") is None


def test_migrations_are_idempotent_in_fresh_schema(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        first = repo.conn.execute("SELECT version,checksum FROM schema_migrations").fetchall()
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        second = repo.conn.execute("SELECT version,checksum FROM schema_migrations").fetchall()

    assert [(row["version"], row["checksum"]) for row in first] == [
        (SCHEMA_FILE.name, schema_checksum())
    ]
    assert [(row["version"], row["checksum"]) for row in first] == [
        (row["version"], row["checksum"]) for row in second
    ]


def test_schema_reference_never_contains_database_credentials(isolated_postgres_schema):
    assert isolated_postgres_schema.reference.startswith("folder-schema:gsd_test_")
    assert "postgresql://" not in isolated_postgres_schema.reference
    assert "password" not in isolated_postgres_schema.reference.lower()
    assert "@" not in isolated_postgres_schema.reference


def test_schema_cleanup_does_not_touch_neighbor_schema(folder_postgres_base, postgres_schema_factory):
    first = postgres_schema_factory()
    second = postgres_schema_factory()
    init_db(first.dsn)
    init_db(second.dsn)

    admin = connect_database(folder_postgres_base)
    try:
        admin.execute(f"DROP SCHEMA {first.schema} CASCADE")
    finally:
        admin.close()

    with Repo(second.dsn) as repo:
        assert repo.conn.execute("SELECT COUNT(*) c FROM schema_migrations").fetchone()["c"] > 0


def test_a_ledger_older_than_the_schema_is_refused_not_migrated(postgres_schema_factory):
    fresh = postgres_schema_factory()
    admin = connect_database(fresh.dsn)
    try:
        admin.execute(
            "CREATE TABLE schema_migrations("
            "version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_utc TEXT NOT NULL)")
        admin.execute(
            "INSERT INTO schema_migrations VALUES('001_init.sql','deadbeef','2026-01-01T00:00:00Z')")
        admin.execute(
            "INSERT INTO schema_migrations VALUES('039_report_cycles.sql','deadbeef','2026-01-01T00:00:00Z')")
    finally:
        admin.close()
    with pytest.raises(SchemaLedgerMismatch, match="migration script.*the shipped schema does not"):
        init_db(fresh.dsn)


def test_an_edited_schema_file_is_refused(postgres_schema_factory):
    fresh = postgres_schema_factory()
    init_db(fresh.dsn)
    admin = connect_database(fresh.dsn)
    try:
        admin.execute("UPDATE schema_migrations SET checksum=repeat('0',64)")
    finally:
        admin.close()
    with pytest.raises(SchemaLedgerMismatch, match="shipped file"):
        init_db(fresh.dsn)


def test_performance_window_is_clamped_to_the_work_actually_done(postgres_schema_factory):
    import json
    from graph_scale_dynamics.observability.evidence_sources import performance_payload
    fresh = postgres_schema_factory()
    init_db(fresh.dsn)
    with Repo(fresh.dsn) as repo:
        campaign = repo.create_campaign(
            json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text()),
            search_seed=1)
        cid = campaign["campaign_id"]
        empty = performance_payload(repo, cid, window_hours=24.0)
        assert empty["window_hours"] == 24.0 and empty["work_span_hours"] is None
        assert empty["effective_window_hours"] == 24.0
        from graph_scale_dynamics.domain.model import CandidateState
        repo.insert_candidate("cand", cid, {"init": "empty", "terms": [], "dynamics": {"kind": "equilibrium"}},
                              "equilibrium", 1, CandidateState.PROPOSED.value)
        import datetime as _dt
        _base = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=3)
        _stamps = tuple((_base + _dt.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
                        for m in (0, 90))
        for i, stamp in enumerate(_stamps):
            job_id = f"job-{i}"
            repo.conn.execute(
                "INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,spec_json,created_utc,updated_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (job_id, cid, "cand", "simulate", "base", 64, i, "{}", stamp, stamp))
            repo.conn.execute(
                "INSERT INTO attempts(attempt_id,job_id,number,started_utc,finished_utc,exit_code,wall_seconds) "
                "VALUES(?,?,?,?,?,?,?)", (f"att-{i}", job_id, 1, stamp, stamp, 0, 1.0))
        payload = performance_payload(repo, cid, window_hours=24.0)
    assert payload["work_span_hours"] == 1.5
    assert payload["effective_window_hours"] == 1.5
    assert payload["simulation"]["completed_per_hour_window"] == round(2 / 1.5, 3)
