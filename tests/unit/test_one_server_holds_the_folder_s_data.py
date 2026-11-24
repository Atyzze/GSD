from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.operations import server_lock
from graph_scale_dynamics.services import db_watchdog
from tests.support import fake_postgres

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "postgres_instance.py"


def _tool(monkeypatch, root: Path):
    spec = importlib.util.spec_from_file_location("gsd_postgres_instance_lock", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    postgres = root / "instance" / "postgres"
    (postgres / "data").mkdir(parents=True)
    (postgres / "data" / "PG_VERSION").write_text("17\n")
    for name, value in (("ROOT", root), ("ENV_FILE", root / ".env.postgres"), ("PGDATA", postgres / "data"),
                        ("PGSOCKET", postgres / "socket"), ("PGSUPERVISOR_PID", postgres / "supervisor.pid"),
                        ("PLACEMENT_RECORD", postgres / "placement.json")):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "_assert_local_paths", lambda: None)
    monkeypatch.setattr(module, "_postgres_volatile_root", lambda: root)
    monkeypatch.setattr(module, "_project_env", lambda values: dict(os.environ))
    monkeypatch.setattr(module, "_pg_bin", lambda name: Path(name))
    for name in ("_wait_ready", "_ensure_database", "_warn_on_stale_runtime_placement"):
        monkeypatch.setattr(module, name, lambda *a, **k: None)
    monkeypatch.setattr(module, "_ensure_tmpfs_temp_tablespace", lambda values: root)
    module.ENV_FILE.write_text(module.render_env(name="gsd-lock", password="p"))
    module.ENV_FILE.chmod(0o600)
    return module


def _started(monkeypatch, module) -> list:
    started, real = [], subprocess.Popen

    def popen(*args, **kwargs):
        started.append(real(*args, **kwargs))
        return started[-1]
    monkeypatch.setattr(module, "subprocess", SimpleNamespace(**{**vars(subprocess), "Popen": popen}))
    return started


def test_a_second_start_is_refused_while_the_first_server_holds_the_lock(monkeypatch, tmp_path, capsys):
    root = tmp_path / "folder"
    module = _tool(monkeypatch, root)
    note = tmp_path / "postmaster.note"
    monkeypatch.setattr(module, "_namespace_argv",
                        lambda command, server: fake_postgres.supervisor_argv(module.PGDATA, note))
    started = _started(monkeypatch, module)
    lock = root / "instance" / "postgres" / server_lock.LOCK_NAME
    try:
        module._start_server({})
        assert fake_postgres.heard(note, "ready")
        supervisor = started[0].pid
        assert server_lock.held(lock) and server_lock.holder(lock) == supervisor, (
            "the starter has closed its descriptor: the server alone holds the lock")
        assert server_lock.holds(supervisor, lock) and module.PGSUPERVISOR_PID.read_text().strip() == str(supervisor)
        assert server_lock.read_record(lock)["log"] == str(root / "postgres.log")

        module.PGSUPERVISOR_PID.unlink()
        module._start_server({})
        assert len(started) == 1, "a second server was started on a data folder whose server still runs"
        assert server_lock.take(lock, seconds=0.2) is None, "a second starter cannot take the lock"

        capsys.readouterr()
        assert module.runtime_command("status", []) == 0
        said = capsys.readouterr().out
        assert said.startswith("running") and f"pid={supervisor}" in said, said
        assert module.runtime_command("stop", []) == 0
        assert fake_postgres.heard(note, "stop"), "stop signalled the postmaster"
        assert server_lock.held(lock) is False, "the lock went with the server"
        started[0].wait(timeout=10)
        assert module.runtime_command("status", []) == 1
    finally:
        for process in started:
            fake_postgres.end(process)


def test_a_start_whose_lock_another_process_took_first_is_refused(monkeypatch, tmp_path):
    root = tmp_path / "folder"
    module = _tool(monkeypatch, root)
    lock = root / "instance" / "postgres" / server_lock.LOCK_NAME
    monkeypatch.setattr(module, "_server_running", lambda: False)
    started = _started(monkeypatch, module)
    holder = server_lock.take(lock)
    try:
        with pytest.raises(RuntimeError, match="held by another process"):
            module._start_server({})
        assert started == []
    finally:
        os.close(holder)


def test_the_lock_lives_in_the_namespaced_server_that_reads_itself_as_pid_1(monkeypatch, tmp_path):
    root = tmp_path / "folder"
    module = _tool(monkeypatch, root)
    server = tmp_path / "postgres"
    sleeper = ("import os, signal, sys, time; signal.signal(signal.SIGTERM, lambda *a: sys.exit(0)); "
               f"open(\"{server}.saying\", \"w\").write(\"pid %d\" % os.getpid()); "
               f"os.replace(\"{server}.saying\", \"{server}.said\"); time.sleep(600)")
    server.write_text(f"#!/bin/sh\nexec {sys.executable} -c '{sleeper}' postgres \"$@\"\n")
    server.chmod(0o755)
    monkeypatch.setattr(module, "_pg_bin", lambda name: server)
    started = _started(monkeypatch, module)
    lock = root / "instance" / "postgres" / server_lock.LOCK_NAME
    try:
        module._start_server({})
        said = Path(f"{server}.said")
        deadline = time.monotonic() + 10
        while not said.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert said.read_text().split() == ["pid", "1"], "the server runs as PID 1 of its own namespace"
        assert server_lock.held(lock) and server_lock.holder(lock) == started[0].pid
        assert module._stop_server(timeout=15) == 0
        assert server_lock.held(lock) is False
    finally:
        for process in started:
            fake_postgres.end(process)


def test_the_watchdog_reads_the_server_lock_and_names_the_real_log(tmp_path):
    postgres = tmp_path / "instance" / "postgres"
    lock = postgres / server_lock.LOCK_NAME
    note = tmp_path / "postmaster.note"

    def away():
        raise OSError("connection refused")

    def alarm() -> str:
        said: list[str] = []
        dog = db_watchdog.Watchdog(socket_dir=postgres / "socket", postgres_dir=postgres, connect=away,
                                   helper=None, owns_instance=False, log=said.append)
        dog.tick(0.0)
        return said[0]

    assert "never started under a server lock" in alarm()
    server = fake_postgres.start(lock, postgres / "data", note, log=str(tmp_path / "runtime" / "postgres.log"))
    try:
        line = alarm()
        assert f"server running (supervisor pid {server.pid})" in line and "DEAD" not in line
        assert str(tmp_path / "runtime" / "postgres.log") in line and "postgres_instance.py logs" in line
    finally:
        fake_postgres.end(server, lock)
    line = alarm()
    assert "server STOPPED" in line and str(tmp_path / "runtime" / "postgres.log") in line
    assert "data/log" not in line


def test_status_and_stop_name_a_server_whose_record_was_lost(monkeypatch, tmp_path, capsys):
    root = tmp_path / "folder"
    module = _tool(monkeypatch, root)
    lock = root / "instance" / "postgres" / server_lock.LOCK_NAME
    note = tmp_path / "postmaster.note"
    server = fake_postgres.start(lock, module.PGDATA, note)
    try:
        lock.write_text("{}")
        assert module._running_supervisor() == server.pid, "found by what it holds, not by a record"
        assert module._stop_server(timeout=15) == 0 and fake_postgres.heard(note, "stop")
    finally:
        fake_postgres.end(server)
