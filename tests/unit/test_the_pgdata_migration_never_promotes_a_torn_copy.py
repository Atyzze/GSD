from __future__ import annotations

import contextlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.gsd_pgdata_cow as COW


def _cluster(tmp_path: Path) -> Path:
    pgdata = tmp_path / "instance" / "postgres"
    (pgdata / "base").mkdir(parents=True)
    (pgdata / "PG_VERSION").write_text("17\n")
    (pgdata / "base" / "1").write_bytes(b"x" * 1024)
    return pgdata


def _host(monkeypatch, tmp_path: Path, busy: list):
    pgdata = _cluster(tmp_path)
    held = []

    @contextlib.contextmanager
    def lock():
        held.append("taken")
        yield
        held.append("released")

    copies = []

    def run(argv, check=False):
        copies.append(argv)
        assert held == ["taken"], "the copy runs under the bootstrap lock"
        shutil.copytree(argv[-2].rstrip("."), argv[-1], dirs_exist_ok=True)
        return SimpleNamespace(returncode=0)

    answers = iter(busy)
    monkeypatch.setattr(COW, "_pgdata", lambda: pgdata)
    monkeypatch.setattr(COW, "inspect_cow_placement", lambda _p: {"copy_on_write_filesystem": True, "nodatacow": False})
    monkeypatch.setattr(COW, "_set_nodatacow", lambda _p: True)
    monkeypatch.setattr(COW, "_lock", lock)
    monkeypatch.setattr(COW, "_why_busy", lambda _p: next(answers))
    monkeypatch.setattr(COW.subprocess, "run", run)
    return pgdata, held, copies


def test_an_idle_cluster_is_migrated_under_the_lock(tmp_path, monkeypatch):
    pgdata, held, copies = _host(monkeypatch, tmp_path, [None, None])
    assert COW.command_migrate(assume_yes=True) == 0
    assert held == ["taken", "released"] and len(copies) == 1
    assert (pgdata / "base" / "1").is_file() and (pgdata.with_name("postgres.cow-retired") / "PG_VERSION").is_file()


def test_a_busy_cluster_is_never_copied(tmp_path, monkeypatch, capsys):
    pgdata, held, copies = _host(monkeypatch, tmp_path, ["this folder's fleet is running (supervisor pid 7)"])
    assert COW.command_migrate(assume_yes=True) == 2
    assert copies == [] and held == ["taken", "released"]
    assert "fleet is running" in capsys.readouterr().out
    assert not pgdata.with_name("postgres.nocow-staging").exists()


def test_a_server_that_starts_during_the_copy_stops_the_promotion(tmp_path, monkeypatch, capsys):
    pgdata, held, copies = _host(monkeypatch, tmp_path, [None, "the managed PostgreSQL server is running"])
    assert COW.command_migrate(assume_yes=True) == 2
    assert len(copies) == 1 and held == ["taken", "released"]
    assert not pgdata.with_name("postgres.nocow-staging").exists(), "the torn copy is removed"
    assert not pgdata.with_name("postgres.cow-retired").exists() and (pgdata / "PG_VERSION").is_file(), (
        "the original stays where it was")
    assert "started during it" in capsys.readouterr().out


def test_what_counts_as_busy(tmp_path, monkeypatch):
    pgdata = _cluster(tmp_path)
    monkeypatch.setattr(COW, "_server_running", lambda: False)
    monkeypatch.setattr(COW, "ROOT", tmp_path)
    (tmp_path / "var").mkdir()
    assert COW._why_busy(pgdata) is None
    (pgdata / "postmaster.pid").write_text("1\n")
    assert "postmaster.pid" in COW._why_busy(pgdata)
    (pgdata / "postmaster.pid").unlink()
    monkeypatch.setattr(COW, "_server_running", lambda: True)
    assert "server is running" in COW._why_busy(pgdata)
