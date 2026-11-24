from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.doubles import RollbackCapable

import graph_scale_dynamics.db.connection as connection_module
from graph_scale_dynamics.services.executor.main import _role
from graph_scale_dynamics.db.connection import (
    postgres_schema_dsn,
    postgres_sql,
    resolve_target,
    service_database_reference,
    split_sql_script,
)
from graph_scale_dynamics.db.repo import SCHEMA_FILE
from graph_scale_dynamics.scheduling.allocation import compute_allocation

ROOT = Path(__file__).resolve().parents[2]


def _write_folder_env(path: Path, root: Path, *, legacy: bool = False) -> None:
    socket = root / "instance" / "postgres" / "socket"
    prefix = "GSD_" if legacy else ""
    path.write_text(
        f"{prefix}INSTANCE_NAME=gsd-test\n"
        f"{prefix}POSTGRES_USER=rr\n"
        f"{prefix}POSTGRES_DB=graph_scale_dynamics\n"
        f"{prefix}POSTGRES_PASSWORD=a-safe_password\n"
        f"{prefix}POSTGRES_SOCKET={socket}\n"
    )
    path.chmod(0o600)


def test_runtime_rejects_nonpostgres_target():
    with pytest.raises(ValueError, match="PostgreSQL-only"):
        resolve_target("var/db.sqlite")


def test_missing_folder_config_bootstraps_local_instance(monkeypatch, tmp_path):
    local_env = tmp_path / ".env.postgres"
    monkeypatch.setattr(connection_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", local_env)
    calls = []

    def fake_ensure():
        calls.append(True)
        _write_folder_env(local_env, tmp_path)

    monkeypatch.setattr(connection_module, "_ensure_folder_postgres", fake_ensure)
    target = resolve_target(None)
    assert calls == [True]
    assert target.startswith("postgresql://rr:a-safe_password@/graph_scale_dynamics?")
    assert "host=%2F" in target


def test_managed_folder_config_is_ensured_before_use(monkeypatch, tmp_path):
    local_env = tmp_path / ".env.postgres"
    _write_folder_env(local_env, tmp_path)
    monkeypatch.setattr(connection_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", local_env)
    calls = []
    monkeypatch.setattr(connection_module, "_ensure_folder_postgres", lambda: calls.append(True))
    assert "graph_scale_dynamics" in resolve_target(None)
    assert calls == [True]


def test_read_only_resolution_does_not_bootstrap(monkeypatch, tmp_path):
    local_env = tmp_path / ".env.postgres"
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", local_env)
    monkeypatch.setattr(
        connection_module, "_ensure_folder_postgres",
        lambda: (_ for _ in ()).throw(AssertionError("must remain read-only")),
    )
    with pytest.raises(ValueError, match="first runtime command will create/start"):
        resolve_target(None, auto_provision=False)


def test_compact_folder_env_reconstructs_unix_socket_database_url(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.postgres"
    _write_folder_env(env_file, tmp_path)
    monkeypatch.setattr(connection_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", env_file)
    monkeypatch.setattr(connection_module, "_ensure_folder_postgres", lambda: None)
    target = resolve_target(None)
    assert target.startswith("postgresql://rr:a-safe_password@/graph_scale_dynamics?")
    assert "host=%2F" in target


def test_legacy_folder_env_requires_instance_helper_upgrade(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.postgres"
    _write_folder_env(env_file, tmp_path, legacy=True)
    monkeypatch.setattr(connection_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", env_file)
    with pytest.raises(ValueError, match="postgres_instance.py ensure"):
        resolve_target(None, auto_provision=False)


def test_folder_env_requires_managed_identity(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.postgres"
    env_file.write_text("POSTGRES_PASSWORD=secret\n")
    env_file.chmod(0o600)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", env_file)
    with pytest.raises(ValueError, match="not a current managed PostgreSQL config"):
        resolve_target(None, auto_provision=False)


def test_folder_env_file_must_not_be_group_or_world_readable(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.postgres"
    env_file.write_text("INSTANCE_NAME=gsd-test\nPOSTGRES_PASSWORD=secret\n")
    env_file.chmod(0o644)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", env_file)
    with pytest.raises(ValueError, match="chmod 600"):
        resolve_target(None, auto_provision=False)


def test_explicit_recovery_url_and_generic_env_are_supported(monkeypatch):
    dsn = "postgresql://rr:secret@localhost/rr"
    assert resolve_target(dsn) == dsn
    monkeypatch.setenv("GSD_TEST_DATABASE", dsn)
    assert resolve_target("env:GSD_TEST_DATABASE") == dsn


def test_folder_schema_reference_uses_local_identity_without_exposing_credentials(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.postgres"
    socket = tmp_path / "instance" / "postgres" / "socket"
    env_file.write_text(
        "INSTANCE_NAME=gsd-test\nPOSTGRES_USER=rr\nPOSTGRES_PASSWORD=secret\n"
        f"POSTGRES_DB=graph_scale_dynamics\nPOSTGRES_SOCKET={socket}\n"
    )
    env_file.chmod(0o600)
    monkeypatch.setattr(connection_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(connection_module, "LOCAL_POSTGRES_ENV", env_file)
    dsn = resolve_target("folder-schema:gsd_test_abc", auto_provision=False)
    assert "search_path%3Dgsd_test_abc" in dsn
    assert service_database_reference(dsn) == "folder-schema:gsd_test_abc"
    assert "secret" not in service_database_reference(dsn)


def test_schema_dsn_isolated_and_validated():
    dsn = postgres_schema_dsn("postgresql://rr:p@localhost/rr?sslmode=disable", "gsd_test_123")
    assert "search_path%3Dgsd_test_123" in dsn
    assert "sslmode=disable" in dsn
    with pytest.raises(ValueError):
        postgres_schema_dsn("postgresql://rr:p@localhost/rr", "bad;drop schema public")


def test_repository_sql_translation_is_only_parameter_translation():
    assert postgres_sql("BEGIN") == "BEGIN"
    assert postgres_sql("SELECT '?' AS literal, ? AS value") == (
        "SELECT '?' AS literal, %s AS value"
    )
    native = "INSERT INTO t(a) VALUES(?) ON CONFLICT DO NOTHING"
    assert postgres_sql(native) == (
        "INSERT INTO t(a) VALUES(%s) ON CONFLICT DO NOTHING"
    )


def test_migration_splitter_handles_plpgsql_dollar_quotes():
    schema = SCHEMA_FILE.read_text()
    statements = split_sql_script(schema)
    assert len(statements) >= 150
    assert any("CREATE FUNCTION gsd_track_latest_engine_decision" in s for s in statements)
    assert not any("gsd_notify_work" in s for s in statements)
    assert all(s.strip() for s in statements)


def test_unified_executor_role_assignment():
    snapshot = {"analysis_slots": 3, "simulation_slots": 5, "paused": False}
    assert [_role(snapshot, slot) for slot in range(9)] == [
        "analysis", "analysis", "analysis",
        "simulation", "simulation", "simulation", "simulation", "simulation",
        None,
    ]
    snapshot["paused"] = True
    assert _role(snapshot, 0) is None


def test_all_backlog_can_use_every_executor_slot():
    allocation = compute_allocation(
        total_slots=32,
        max_analyzers=32,
        analysis_backlog=4206,
        queued_simulations=0,
        leased_simulations=0,
    )
    assert allocation["analysis_slots"] == 32
    assert allocation["simulation_slots"] == 0


def test_runtime_modules_do_not_import_sqlite():
    for root in (ROOT / "graph_scale_dynamics" / "services", ROOT / "graph_scale_dynamics"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text())
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            assert "sqlite3" not in imports, path


def test_release_packager_excludes_local_credentials():
    from tools import package_release as packager
    root = packager.ROOT
    for name in (".env.postgres", "instance/postgres/base.dump", "var/backups/pre-reset.dump",
                 "calibration/probe_calibration.json"):
        assert packager.include_in_release(root / name) is False, name
    for name in ("README.md", "tools/postgres_instance.py", "calibration/seed_table.json"):
        assert packager.include_in_release(root / name) is True, name


def test_migration_ledger_records_checksum(monkeypatch, tmp_path):
    import graph_scale_dynamics.db.repo as repo_module

    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE example(id INTEGER);")

    class Cursor:
        def __init__(self, row=None, rowcount=0, rows=None):
            self._row = row
            self._rows = rows or []
            self.rowcount = rowcount

        def fetchone(self):
            return self._row

        def fetchall(self):
            return self._rows

    class FakeConnection(RollbackCapable):
        def __init__(self):
            self.in_transaction = False
            self.scripts = []
            self.inserted = []
            self.calls = []
            self.closed = False

        def execute(self, sql, args=()):
            self.calls.append((sql, tuple(args)))
            if sql == "BEGIN":
                self.in_transaction = True
            elif sql == "COMMIT":
                self.in_transaction = False
            elif sql == "ROLLBACK":
                self.in_transaction = False
            elif sql.startswith("SELECT version,checksum"):
                return Cursor(rows=[])
            elif sql.startswith("INSERT INTO schema_migrations"):
                self.inserted.append(tuple(args))
            return Cursor(rowcount=1)

        def executescript(self, body):
            self.scripts.append(body)

        def close(self):
            self.closed = True

    fake = FakeConnection()
    monkeypatch.setattr(repo_module, "SCHEMA_FILE", schema_file)
    monkeypatch.setattr(repo_module, "connect", lambda target: fake)
    repo_module.init_db("postgresql://rr:p@localhost/rr")
    assert fake.scripts == ["CREATE TABLE example(id INTEGER);"]
    assert fake.inserted[0][0] == "schema.sql"
    assert len(fake.inserted[0][1]) == 64
    assert fake.calls[0][0].startswith("SELECT pg_advisory_lock")
    assert fake.calls[-1][0].startswith("SELECT pg_advisory_unlock")
    assert fake.closed


def test_qmark_translation_ignores_comments_and_dollar_quoted_bodies():
    sql = "SELECT 1 -- literal ?\n, ? AS value /* another ? */; DO $$ BEGIN RAISE NOTICE '?'; END $$"
    translated = postgres_sql(sql)
    assert "-- literal ?" in translated
    assert "/* another ? */" in translated
    assert "NOTICE '?'" in translated
    assert ", %s AS value" in translated
    assert translated.count("%s") == 1


def test_migration_splitter_ignores_semicolons_inside_comments():
    header = SCHEMA_FILE.read_text()
    statements = split_sql_script(header)
    assert "-- GSD authoritative schema." in statements[0]
    assert statements[0].rstrip().endswith("$$")

    synthetic = """-- comment; still comment\nSELECT 1; /* block; nested /* x; */ ok */ SELECT 2;"""
    assert split_sql_script(synthetic) == [
        "-- comment; still comment\nSELECT 1",
        "/* block; nested /* x; */ ok */ SELECT 2",
    ]


def test_maintenance_waits_past_the_lock_timeout_and_a_claim_does_not(monkeypatch):
    from graph_scale_dynamics.db.repo import Repo

    class Conn:
        def __init__(self):
            self.asked, self.held = 0, []

        def execute(self, sql, params=()):
            assert "pg_try_advisory_lock" in sql, sql
            self.asked += 1
            free = self.asked >= 3
            return type("Row", (), {"fetchone": lambda _self: {"acquired": free}})()

        def hold_lock(self, key, name):
            self.held.append(name)

    repo = Repo.__new__(Repo)
    repo.conn = Conn()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    repo.wait_for_advisory_lock("gsd:maintenance")
    assert repo.conn.asked == 3 and repo.conn.held == ["gsd:maintenance"]
