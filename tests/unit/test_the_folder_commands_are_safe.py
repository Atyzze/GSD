from __future__ import annotations

import importlib.util
import inspect
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from graph_scale_dynamics.operations import folder_guard as G

REPO = Path(__file__).resolve().parents[1].parent


def _sleeper(*words: str, cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", *words],
                            cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def _fleet_pid(var: Path, pid: int, host: str | None = None, start_ticks: int | None = -1) -> None:
    var.mkdir(parents=True, exist_ok=True)
    record = {"pid": pid, "host": host or socket.gethostname(), "started_utc": "2026-10-20T00:00:00Z"}
    if start_ticks is not None:
        record["start_ticks"] = G.process_start_ticks(pid) if start_ticks == -1 else start_ticks
    (var / main.FLEET_PID_FILE).write_text(json.dumps(record))


def _folder(tmp_path: Path) -> Path:
    root = tmp_path / "255" / "main"
    (root / "instance" / "postgres").mkdir(parents=True)
    (root / "instance" / "postgres" / "PG_VERSION").write_text("16\n")
    (root / "var" / "blobs").mkdir(parents=True)
    (root / ".env.postgres").write_text("POSTGRES_USER=rr\n")
    return root


def test_a_live_fleet_is_read_from_its_pid_file_and_a_reused_pid_is_not(tmp_path):
    var = tmp_path / "var"
    fleet = _sleeper("main.py", "run")
    other = _sleeper("not-a-fleet")
    try:
        time.sleep(0.2)
        assert G.live_fleet(var) is None, "no pid file, no fleet"
        _fleet_pid(var, fleet.pid)
        assert "is running" in (G.live_fleet(var) or "")
        _fleet_pid(var, other.pid, start_ticks=G.process_start_ticks(fleet.pid) - 1)
        assert G.live_fleet(var) is None, "a pid reused by a process that started at another time is not a fleet"
        _fleet_pid(var, other.pid)
        assert "is running" in (G.live_fleet(var) or ""), "a fleet launched other than as main.py is still a fleet"
        _fleet_pid(var, other.pid, start_ticks=None)
        assert "is running" in (G.live_fleet(var) or ""), "a record with no start time is live while its pid is"
        _fleet_pid(var, fleet.pid, host="another-host")
        assert "cannot be checked" in (G.live_fleet(var) or ""), "another host's fleet is not taken for gone"
    finally:
        for process in (fleet, other):
            process.kill()
            process.wait(timeout=5)
    _fleet_pid(var, fleet.pid)
    assert G.live_fleet(var) is None, "a supervisor that exited is not a fleet"


def _guard_the_real_tree() -> None:
    for command in (main.cmd_reset, main.cmd_serve, main._serve):
        assert "__file__" not in inspect.getsource(command), f"{command.__name__} must find its folder by ROOT"


def _reset(monkeypatch, root: Path, *, typed: str | None = None, yes: bool = False) -> int:
    _guard_the_real_tree()
    monkeypatch.setattr(main, "ROOT", root)
    if typed is not None:
        monkeypatch.setattr("builtins.input", lambda _prompt: typed)
    return main.cmd_reset(SimpleNamespace(var="var", yes=yes))


def test_reset_asks_for_the_study_the_folder_recorded_never_the_folder_s_name(tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import study_record as R
    root = _folder(tmp_path)
    assert R.reset_phrase(root / "var") == "reset this folder", "a folder with no record"
    R.write(root / "var", study="256", kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lambda *_: None)
    assert _reset(monkeypatch, root, typed="255/main") == 1, "the folder's name confirms nothing"
    assert (root / "instance").exists() and (root / ".env.postgres").exists()
    assert _reset(monkeypatch, root, typed="reset study 256") == 0
    assert not (root / "instance").exists() and not (root / "var").exists()
    assert not (root / ".env.postgres").exists()


def test_reset_refuses_while_the_fleet_runs(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    fleet = _sleeper("main.py", "run")
    try:
        time.sleep(0.2)
        _fleet_pid(root / "var", fleet.pid)
        assert _reset(monkeypatch, root, yes=True) == 2
        assert (root / "instance" / "postgres" / "PG_VERSION").exists() and (root / ".env.postgres").exists()
    finally:
        fleet.kill()
        fleet.wait(timeout=5)


def test_reset_refuses_while_serve_runs_and_not_after_it_is_gone(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    assert not str(root.resolve()).startswith(str(REPO.resolve())), "this test does not run on the build tree"
    serve = _sleeper("main.py", "serve")
    try:
        time.sleep(0.2)
        record = G.record_this_process(root / "var" / G.SERVE_PID_FILE, port=8765)
        record = json.loads(record)
        record.update(pid=serve.pid, start_ticks=G.process_start_ticks(serve.pid))
        (root / "var" / G.SERVE_PID_FILE).write_text(json.dumps(record))
        assert "being served" in (G.live_serve(root / "var") or "")
        assert _reset(monkeypatch, root, yes=True) == 2
        assert (root / "instance" / "postgres" / "PG_VERSION").exists() and (root / ".env.postgres").exists()
    finally:
        serve.kill()
        serve.wait(timeout=5)
    assert G.live_serve(root / "var") is None, "a serve that exited holds nothing"
    assert _reset(monkeypatch, root, yes=True) == 0


def test_serve_records_itself_while_it_runs_and_removes_only_its_own_record(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    var = root / "var"
    assert not str(root.resolve()).startswith(str(REPO.resolve())), "this test does not run on the build tree"
    _guard_the_real_tree()
    from graph_scale_dynamics.services import calibration_gate
    seen: list[str | None] = []

    def calibration_reads_the_record(*_a, **_k):
        seen.append(G.live_serve(var))
        raise calibration_gate.CalibrationGateError("stop here")

    monkeypatch.setattr(main, "ROOT", root)
    monkeypatch.setattr(main, "postgres_running", lambda _root: True)
    monkeypatch.setattr(calibration_gate, "ensure_probe_calibration", calibration_reads_the_record)
    monkeypatch.setattr(main, "paths", lambda _args: ("db", var / "blobs", var))
    monkeypatch.setattr(main, "init_db", lambda _db: None)
    assert main.cmd_serve(SimpleNamespace(port=8765, var="var")) == 3
    assert seen and "being served" in (seen[0] or ""), "serve was not on record while it ran"
    assert not (var / G.SERVE_PID_FILE).exists(), "serve left its record behind"


def test_reset_deletes_nothing_when_the_server_will_not_stop(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    (root / "tools").mkdir()
    (root / "tools" / "postgres_instance.py").write_text("import sys\nprint('server did not stop')\nsys.exit(1)\n")
    assert _reset(monkeypatch, root, yes=True) == 3
    assert (root / "instance" / "postgres" / "PG_VERSION").exists() and (root / ".env.postgres").exists()


def test_reset_checks_every_target_before_deleting_any(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    (tmp_path / "255" / "elsewhere").mkdir()
    _guard_the_real_tree()
    monkeypatch.setattr(main, "ROOT", root)
    with pytest.raises(SystemExit, match="outside the project root"):
        main.cmd_reset(SimpleNamespace(var="../elsewhere", yes=True))
    assert (root / "instance").exists() and (root / ".env.postgres").exists(), "something went before the refusal"


def test_reset_refuses_a_state_directory_that_is_part_of_the_tree(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    for name in ("docs", "tools"):
        (root / name / "inner").mkdir(parents=True)
    _guard_the_real_tree()
    monkeypatch.setattr(main, "ROOT", root)
    for var in ("docs", "tools/inner", "graph_scale_dynamics"):
        with pytest.raises(SystemExit, match="part of the tree"):
            main.cmd_reset(SimpleNamespace(var=var, yes=True))
    assert (root / "docs").exists() and (root / "instance").exists() and (root / ".env.postgres").exists()
    assert main.shipped_part(root / "var") is None and main.shipped_part(root / "var2") is None


def test_serve_refuses_while_the_fleet_runs_and_touches_nothing(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    var = root / "var"
    fleet = _sleeper("main.py", "run")
    touched: list[str] = []
    _guard_the_real_tree()
    from graph_scale_dynamics.services import calibration_gate

    def no_calibration(*_a, **_k):
        raise AssertionError("serve reached the calibration gate with a fleet live")

    monkeypatch.setattr(main, "ROOT", root)
    monkeypatch.setattr(calibration_gate, "ensure_probe_calibration", no_calibration)
    monkeypatch.setattr(main, "paths", lambda _args: ("db", var / "blobs", var))
    monkeypatch.setattr(main, "init_db", lambda _db: touched.append("init_db"))
    monkeypatch.setattr(main, "_stop_folder_postgres", lambda **_k: touched.append("stop postgres"))
    monkeypatch.setattr(main, "_write_internal_api_capability", lambda _v: touched.append("capability"))
    try:
        time.sleep(0.2)
        _fleet_pid(var, fleet.pid)
        assert main.cmd_serve(SimpleNamespace(port=8765, var="var")) == 2
        assert touched == [], touched
    finally:
        fleet.kill()
        fleet.wait(timeout=5)


def test_a_capability_file_is_removed_only_while_it_holds_what_its_writer_wrote(tmp_path):
    path = tmp_path / "dashboard-admin"
    path.write_text("mine\n")
    G.unlink_if_ours(path, "theirs\n")
    assert path.exists(), "a capability file another process rewrote is left for it"
    G.unlink_if_ours(path, "mine\n")
    assert not path.exists()


def _instance_tool(root: Path):
    spec = importlib.util.spec_from_file_location("gsd_pg_instance_rename", REPO / "tools" / "postgres_instance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module


def test_the_server_check_survives_a_folder_rename(tmp_path):
    before = tmp_path / "252" / "main"
    before.mkdir(parents=True)
    wrapper = _sleeper("unshare", "--user", "--pid", "--fork", "postgres", "-D", str(before / "instance"), cwd=before)
    try:
        time.sleep(0.2)
        tool = _instance_tool(before)
        assert tool._pid_alive(wrapper.pid)
        after = tmp_path / "252 (cooling, 18 Oct)" / "main"
        (tmp_path / "252").rename(after.parent)
        tool = _instance_tool(after)
        assert tool._pid_alive(wrapper.pid), "a live server read as stopped after its folder was renamed"
        elsewhere = tmp_path / "253" / "main"
        elsewhere.mkdir(parents=True)
        assert not _instance_tool(elsewhere)._pid_alive(wrapper.pid), "another folder's server is not this one's"
    finally:
        wrapper.kill()
        wrapper.wait(timeout=5)


def test_a_folder_without_credentials_and_with_no_server_stops_as_not_running(tmp_path, capsys):
    root = _folder(tmp_path)
    (root / ".env.postgres").unlink()
    tool = _instance_tool(root)
    tool.ENV_FILE = root / ".env.postgres"
    tool.PGSUPERVISOR_PID = root / "instance" / "postgres" / "supervisor.pid"
    tool._assert_local_paths = lambda: None
    assert tool.runtime_command("stop", []) == 0
    assert "not running" in capsys.readouterr().out
    assert tool.runtime_command("status", []) == 2, "anything else still asks for the credentials"


_WRAPPER = """
import signal, subprocess, sys, time
pgdata, log = sys.argv[1], sys.argv[2]
def note(word):
    with open(log, "a") as f:
        f.write(word + "\\n")
def gone(*_):
    note("wrapper")
    sys.exit(0)
signal.signal(signal.SIGTERM, gone)
child = subprocess.Popen([sys.executable, "-c", sys.argv[3], "postgres", "-D", pgdata, log], cwd=pgdata)
child.wait()
"""
_POSTMASTER = """
import signal, sys, time
def down(*_):
    with open(sys.argv[-1], "a") as f:
        f.write("postmaster\\n")
    sys.exit(0)
signal.signal(signal.SIGTERM, down)
open(sys.argv[-1] + ".ready", "w").close()
time.sleep(600)
"""


def test_stop_after_a_rename_signals_the_postmaster_not_the_wrapper(tmp_path):
    before = tmp_path / "252" / "main"
    pgdata = before / "instance" / "postgres" / "data"
    pgdata.mkdir(parents=True)
    assert not str(before.resolve()).startswith(str(REPO.resolve())), "this test does not run on the build tree"
    log = tmp_path / "signalled.log"
    wrapper = subprocess.Popen([sys.executable, "-c", _WRAPPER + "\n# unshare --user --pid --fork",
                                str(pgdata), str(log), _POSTMASTER],
                               cwd=str(before), start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not Path(f"{log}.ready").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        postmaster = _children(wrapper.pid)[0]
        after = tmp_path / "252 (cooling, 18 Oct)" / "main"
        (tmp_path / "252").rename(after.parent)
        tool = _instance_tool(after)
        tool.PGDATA = after / "instance" / "postgres" / "data"
        tool.PGSUPERVISOR_PID = after / "instance" / "postgres" / "supervisor.pid"
        tool.PGSUPERVISOR_PID.write_text(f"{wrapper.pid}\n")
        assert tool._postgres_postmaster_child(wrapper.pid) == postmaster, "the postmaster was not found by its folder"
        assert tool._stop_server(timeout=10) == 0
        wrapper.wait(timeout=10)
        assert log.read_text().split() == ["postmaster"], "the wrapper was signalled, not the postmaster"
        assert not os.path.exists(f"/proc/{postmaster}"), "the postmaster outlived stop"
    finally:
        for pid in _children(wrapper.pid):
            os.kill(pid, 9)
        wrapper.kill()
        wrapper.wait(timeout=5)


def _children(pid: int) -> list[int]:
    try:
        return [int(t) for t in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
    except OSError:
        return []


def test_sweep_refuses_while_the_fleet_runs(tmp_path, monkeypatch):
    root = _folder(tmp_path)
    fleet = _sleeper("main.py", "run")
    ended = []
    from graph_scale_dynamics.operations import startup_reaper
    monkeypatch.setattr(startup_reaper, "reap_orphan_children", lambda *a, **k: ended.append(a) or {})
    try:
        time.sleep(0.2)
        _fleet_pid(root / "var", fleet.pid)
        _guard_the_real_tree()
        monkeypatch.setattr(main, "ROOT", root)
        assert main.cmd_sweep(SimpleNamespace(var="var", no_children=False, dry_run=False)) == 2
        assert ended == [], "nothing is ended while the fleet runs"
    finally:
        fleet.kill()
        fleet.wait(timeout=5)
