from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def test_an_archived_control_campaign_is_given_no_laws():
    from graph_scale_dynamics.operations import standing_controls as SC

    class Repo:
        def all_campaigns(self):
            return [{"campaign_id": "9", "status": "archived", "spec": {"name": SC.NAME}}]

        def candidates(self, campaign_id):
            raise AssertionError("an archived campaign was given its laws again")

    out = SC.ensure_control_campaign(Repo(), {"campaign_name": SC.NAME, "laws": []}, contract="c", reason="r",
                                     search_seed=1, say=lambda *_: None)
    assert out["archived"] == "9" and out["created"] is None


def test_the_gc_leaves_an_untracked_blob_younger_than_an_hour(tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.operations import artifact_gc as GC
    store = BlobStore(tmp_path)
    young, old = store.put_bytes(b"young")[0], store.put_bytes(b"old")[0]
    os.utime(store._path(old), (time.time() - 7200, time.time() - 7200))

    class Rows:
        def fetchall(self):
            return []

    repo = SimpleNamespace(conn=SimpleNamespace(execute=lambda *a: Rows()))
    found, examples = GC._untracked_blobs(repo, store)
    assert found["count"] == 1 and [e["artifact_hash"] for e in examples] == [old]
    assert young != old


def test_a_backup_carries_the_folder_s_state_and_puts_it_back(tmp_path):
    from graph_scale_dynamics.operations import backup as B
    var = tmp_path / "var"
    for name, text in (("study.json", "{}"), ("controls/made.json", "{}"), ("salt/carried.json", "{}"),
                       ("log/supervisor.log", "x")):
        (var / name).parent.mkdir(parents=True, exist_ok=True)
        (var / name).write_text(text)
    kept = sorted(p.relative_to(var).as_posix() for p in B._var_files(var))
    assert kept == ["controls/made.json", "salt/carried.json", "study.json"]
    backup = tmp_path / "backup"
    rows = []
    for name in kept:
        (backup / B.VAR_ROOT / name).parent.mkdir(parents=True, exist_ok=True)
        (backup / B.VAR_ROOT / name).write_text("{}")
        rows.append({"path": name, "sha256": B._sha256(backup / B.VAR_ROOT / name), "size_bytes": 2})
    manifest = {"var_state": {"root": B.VAR_ROOT, "files": rows}}
    other = tmp_path / "restored"
    assert sorted(B.restore_var_state(backup, manifest, other)) == kept
    with pytest.raises(FileExistsError):
        B.restore_var_state(backup, manifest, other)
    sys.path.insert(0, str(ROOT))
    import main as M
    assert "restore" in M.build_parser()._subparsers._group_actions[0].choices


def test_a_clone_is_not_its_parent_s_study():
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import standing_controls as SC
    from graph_scale_dynamics.operations.study import quadrant_label, quadrant_specs
    label, quadrant = quadrant_specs(json.loads(json.dumps(SURVEY)))[0]
    parent = dict(quadrant, study_design={"study": "256", "campaign": 0}, name=SC.NAME, controls_criterion="x")
    spec = control.derive_spec(parent, "started from campaign 1")["spec"]
    assert quadrant_label(spec) is None and "study_design" not in spec and "controls_criterion" not in spec
    assert spec["name"] != SC.NAME and label in spec["description"]


def test_a_refused_run_leaves_the_running_fleet_s_publisher(monkeypatch):
    from graph_scale_dynamics.operations import power_sidecar as P
    killed = []
    monkeypatch.setattr(P, "publisher_pid", lambda root: 4242)
    monkeypatch.setattr(P.os, "kill", lambda pid, sig: killed.append(pid))
    assert P.stop_publisher(ROOT, started=None) is False and not killed
    assert P.stop_publisher(ROOT, started=4242) is True and killed == [4242]


def test_a_spill_with_no_room_leaves_nothing_behind(tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import scratch_relief as S
    source = tmp_path / "ram" / "job.json.gz"
    source.parent.mkdir()
    source.write_bytes(b"x" * 100)
    import shutil as real
    store = SimpleNamespace(root=tmp_path / "disk")
    monkeypatch.setattr(real, "disk_usage", lambda path: SimpleNamespace(free=10, total=10, used=0))
    with pytest.raises(OSError, match="no room"):
        S._spill_state(store, {"path": str(source), "size": 100})
    assert source.exists() and not list((tmp_path / "disk").rglob("*.spill"))

    monkeypatch.setattr(real, "disk_usage", lambda path: SimpleNamespace(free=1 << 40, total=1 << 40, used=0))

    def broken(src, dst):
        Path(dst).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(real, "copyfile", broken)
    with pytest.raises(OSError, match="disk full"):
        S._spill_state(store, {"path": str(source), "size": 100})
    assert not list((tmp_path / "disk").rglob("*.spill"))


def _record(path: Path) -> None:
    from graph_scale_dynamics.operations.folder_guard import process_start_ticks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started_utc": "now",
                                "start_ticks": process_start_ticks(os.getpid())}))


def test_a_fleet_under_another_var_is_seen_by_reset(tmp_path):
    from graph_scale_dynamics.operations.folder_guard import FLEET_PID_FILE, SERVE_PID_FILE, live_in_folder
    assert live_in_folder(tmp_path) is None
    _record(tmp_path / "elsewhere" / FLEET_PID_FILE)
    assert "fleet is running" in live_in_folder(tmp_path)
    assert live_in_folder(tmp_path, SERVE_PID_FILE) is None
    _record(tmp_path / "var" / SERVE_PID_FILE)
    assert "being served" in live_in_folder(tmp_path, SERVE_PID_FILE)


def test_run_refuses_while_serve_is_live(monkeypatch):
    sys.path.insert(0, str(ROOT))
    import main as M
    from graph_scale_dynamics.operations import leftovers
    monkeypatch.setattr(M, "_refuse_without_default_engine", lambda: None)
    monkeypatch.setattr(leftovers, "at_start", lambda root: None)
    monkeypatch.setattr(M, "live_in_folder", lambda root, *names: "this folder's dashboard is being served")
    monkeypatch.setattr(M.power_sidecar, "ensure_publisher",
                        lambda root: (_ for _ in ()).throw(AssertionError("run went on")))
    assert M.cmd_run(SimpleNamespace()) == 2


def test_the_delivery_and_the_journal_s_removal_are_not_interrupted(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import package_release as PR
    seen = []
    monkeypatch.setattr(PR, "archive", lambda number, output: tmp_path / "partial")
    monkeypatch.setattr(PR, "verify_archive", lambda *a, **k: None)
    monkeypatch.setattr(PR, "publish_archive",
                        lambda partial, output: seen.append(signal.SIGTERM in signal.pthread_sigmask(signal.SIG_BLOCK, [])))
    held: list = []
    PR.package_and_publish(1, tmp_path / "out", held=held)
    try:
        assert seen == [True]
    finally:
        for mask in held:
            PR.release_signals(mask)
    assert signal.SIGTERM not in signal.pthread_sigmask(signal.SIG_BLOCK, [])


def test_a_folder_is_not_a_folder_whose_name_begins_with_it(tmp_path):
    sys.path.insert(0, str(ROOT))
    from tools import postgres_instance as PI
    here = tmp_path / "main"
    here.mkdir()
    assert PI._names_folder(f"unshare --root {here}/instance x", here)
    assert PI._names_folder(f"unshare {here}", here)
    assert not PI._names_folder(f"unshare {here}2/instance x", here)


def test_every_server_start_takes_the_bootstrap_lock(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from contextlib import contextmanager
    from tools import postgres_instance as PI
    held = []

    @contextmanager
    def lock():
        held.append(True)
        yield

    monkeypatch.setattr(PI, "bootstrap_lock", lock)
    monkeypatch.setattr(PI, "runtime_command", lambda name, extra: held.append(name) or 0)
    monkeypatch.setattr(PI, "reset_credentials", lambda: held.append("rekey") or 0)
    assert PI.main(["up"]) == 0 and PI.main(["reset-credentials"]) == 0
    assert held == [True, "up", True, "rekey"]


def test_the_runtime_s_notice_names_its_packages_and_their_source():
    notice = (ROOT / "runtime/THIRD_PARTY_NOTICES.md").read_text()
    assert "Build 80" not in notice and "2.41-5" in notice and "2.41-12+deb13u3" in notice
    assert "snapshot.debian.org/package/util-linux/2.41-5/" in notice
    assert "snapshot.debian.org/package/glibc/" in notice and "on request" in notice
