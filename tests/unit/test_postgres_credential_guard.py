from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "postgres_instance.py"


def _load(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("gsd_postgres_instance_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path, raising=False)
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env.postgres", raising=False)
    monkeypatch.setattr(module, "PGDATA", tmp_path / "instance" / "postgres" / "data", raising=False)
    monkeypatch.setattr(module, "PGSOCKET", tmp_path / "instance" / "postgres" / "socket", raising=False)
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path / "instance" / "container-runtime", raising=False)
    monkeypatch.setattr(module, "LOG_ROOT", tmp_path / "var" / "log", raising=False)
    monkeypatch.setattr(module, "TMP_ROOT", tmp_path / "var" / "tmp", raising=False)
    monkeypatch.setattr(module, "_assert_local_paths", lambda: None, raising=False)
    return module


def _make_cluster(tmp_path: Path) -> Path:
    pgdata = tmp_path / "instance" / "postgres" / "data"
    pgdata.mkdir(parents=True)
    (pgdata / "PG_VERSION").write_text("17\n", encoding="utf-8")
    return pgdata


def test_a_cluster_without_its_credentials_is_not_a_clean_start(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    _make_cluster(tmp_path)
    assert not module.ENV_FILE.exists()

    rc = module.init_config()

    assert rc == 3, "init_config treated a live cluster with no credentials as a clean start"
    assert not module.ENV_FILE.exists(), (
        "a fresh password was written over a cluster that still holds the old one; "
        "the old password existed only in the file that went missing, so this is "
        "not recoverable by restoring anything"
    )


def test_the_refusal_names_a_recovery_that_keeps_the_data(monkeypatch, capsys, tmp_path):
    module = _load(monkeypatch, tmp_path)
    _make_cluster(tmp_path)
    module.init_config()
    out = capsys.readouterr().out

    assert "reset-credentials" in out, "the refusal does not name the recovery command"
    assert "DESTROYS" in out, "the destructive option is not marked as destructive"
    assert out.index("reset-credentials") < out.index("DESTROYS"), (
        "the destructive option is offered before the one that keeps the campaign"
    )


def test_reset_credentials_is_a_real_command(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    assert hasattr(module, "reset_credentials"), "the recovery the guard names does not exist"
    with pytest.raises(SystemExit) as excinfo:
        module.main(["--help"])
    assert excinfo.value.code == 0


def test_reset_credentials_refuses_when_there_is_no_cluster(monkeypatch, capsys, tmp_path):
    module = _load(monkeypatch, tmp_path)
    rc = module.reset_credentials()
    assert rc == 2
    assert "init" in capsys.readouterr().out


def test_an_existing_credentials_file_is_still_refused(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    module.ENV_FILE.write_text("INSTANCE_NAME=x\nPOSTGRES_PASSWORD=y\n", encoding="utf-8")
    assert module.init_config() == 2


def test_trust_is_never_the_configured_policy(monkeypatch, tmp_path):
    module = _load(monkeypatch, tmp_path)
    assert set(module.HBA_POLICIES) == {"scram", "trust"}
    assert "scram-sha-256" in module.HBA_POLICIES["scram"]
    assert "trust" in module.HBA_POLICIES["trust"]
    defaults = {name: inspect.signature(f).parameters["hba_policy"].default for name, f in vars(module).items()
                if inspect.isfunction(f) and "hba_policy" in inspect.signature(f).parameters}
    assert len(defaults) >= 3 and set(defaults.values()) == {"scram"}, defaults


def _rekeyable(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace
    module = _load(monkeypatch, tmp_path)
    _make_cluster(tmp_path)
    (tmp_path / "instance" / "postgres" / "socket").mkdir(parents=True)
    module.ENV_FILE.write_text(module.render_env(name="gsd-x", password="old", user="rr"), encoding="utf-8")
    module.ENV_FILE.chmod(0o600)
    ran = []
    monkeypatch.setattr(module, "_stop_server", lambda: ran.append("stop"))
    monkeypatch.setattr(module, "_ensure_cluster", lambda values, **kw: ran.append("hba"))
    monkeypatch.setattr(module, "_start_server", lambda values: ran.append("start"))
    monkeypatch.setattr(module, "_postgres_volatile_root", lambda: tmp_path)
    monkeypatch.setattr(module, "_run_pg", lambda values, tool, args, **kw: ran.append(tool) or SimpleNamespace(
        returncode=0, stdout=""))
    return module, ran


def test_re_keying_replaces_the_credentials_file_it_finds(monkeypatch, tmp_path):
    module, ran = _rekeyable(monkeypatch, tmp_path)
    monkeypatch.setattr("graph_scale_dynamics.operations.folder_guard.live_in_folder", lambda root: None)
    assert module.reset_credentials() == 0
    values = module.read_env()
    assert values["POSTGRES_PASSWORD"] != "old" and values["POSTGRES_USER"] == "rr"
    assert (module.ENV_FILE.stat().st_mode & 0o777) == 0o600 and ran[0] == "stop"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".") and p != module.ENV_FILE], "no temporary left"


def test_re_keying_refuses_while_a_fleet_runs_in_the_folder(monkeypatch, tmp_path, capsys):
    module, ran = _rekeyable(monkeypatch, tmp_path)
    monkeypatch.setattr("graph_scale_dynamics.operations.folder_guard.live_in_folder",
                        lambda root: "var/fleet.pid names pid 4242, running")
    assert module.reset_credentials() == 2 and ran == []
    assert "main.py run or serve" in capsys.readouterr().out
    assert module.read_env()["POSTGRES_PASSWORD"] == "old"


def test_a_failed_re_key_leaves_no_server_reading_trust(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from graph_scale_dynamics.operations import server_lock
    from tests.support import fake_postgres
    module, ran = _rekeyable(monkeypatch, tmp_path)
    monkeypatch.setattr("graph_scale_dynamics.operations.folder_guard.live_in_folder", lambda root: None)
    hba = module.PGDATA / "pg_hba.conf"
    monkeypatch.setattr(module, "_ensure_cluster", lambda values, **kw: hba.write_text(module.HBA_POLICIES["trust"]))
    monkeypatch.setattr(module, "_run_pg", lambda values, tool, args, **kw: SimpleNamespace(
        returncode=1, stdout="ALTER ROLE failed"))
    note = tmp_path / "postmaster.note"
    server = fake_postgres.start(tmp_path / "instance" / "postgres" / server_lock.LOCK_NAME, module.PGDATA, note)
    try:
        with pytest.raises(RuntimeError, match="ALTER ROLE failed"):
            module.reset_credentials()
        assert hba.read_text() == module.HBA_POLICIES["scram"]
        assert fake_postgres.heard(note, "reload"), "the server kept reading trust: pg_hba.conf was never reloaded"
        assert module.read_env()["POSTGRES_PASSWORD"] == "old"
    finally:
        fake_postgres.end(server)


def test_the_credentials_reach_the_disk_before_their_name_and_the_name_after(monkeypatch, tmp_path):
    import os
    module = _load(monkeypatch, tmp_path)
    events: list[tuple[str, str]] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)

    def replace(source, target):
        events.append(("rename", str(target)))
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "fsync", fsync)
    monkeypatch.setattr(module.os, "replace", replace)
    env, folder = str(module.ENV_FILE.resolve()), str(tmp_path.resolve())
    assert module.init_config() == 0
    assert events.index(("fsync", env)) < events.index(("fsync", folder)), events
    events.clear()
    module._write_env({"INSTANCE_NAME": "gsd-x", "POSTGRES_PASSWORD": "new"})
    renamed = events.index(("rename", str(module.ENV_FILE)))
    written = [i for i, (kind, path) in enumerate(events) if kind == "fsync" and Path(path).name.startswith(
        f".{module.ENV_FILE.name}.")]
    assert written and written[0] < renamed, f"the new file was not on disk before it took the name: {events}"
    assert ("fsync", folder) in events[renamed + 1:], f"the rename itself was never made durable: {events}"
    assert module.read_env()["POSTGRES_PASSWORD"] == "new"
