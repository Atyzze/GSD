from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from graph_scale_dynamics.operations.startup_reaper import fleet_children_running, stop_fleet_children

BUSY = "import time\nend = time.time() + 60\nwhile time.time() < end: pass"


def _child(root: Path, n: str) -> subprocess.Popen:
    env = dict(os.environ, GSD_CHILD_KIND="simulation", GSD_CHILD_N=n, GSD_PROJECT_ROOT=str(root))
    return subprocess.Popen([sys.executable, "-c", BUSY], env=env, start_new_session=True)


def test_every_child_of_this_folder_is_killed_and_named(tmp_path):
    ours, theirs = tmp_path / "folder", tmp_path / "another-folder"
    ours.mkdir()
    theirs.mkdir()
    mine, other = _child(ours, "262144"), _child(theirs, "64")
    try:
        deadline = time.monotonic() + 5
        while not fleet_children_running(ours) and time.monotonic() < deadline:
            time.sleep(0.05)
        said = []
        killed = stop_fleet_children(ours, log=said.append)
        assert [int(c["pid"]) for c in killed] == [mine.pid]
        assert mine.wait(timeout=5) == -9, "the child was killed"
        assert other.poll() is None, "another folder's child is not touched"
        assert said and "N=262144" in said[0] and str(mine.pid) in said[0], said
        assert not fleet_children_running(ours)
    finally:
        for proc in (mine, other):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def _calibration(root: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k not in ("GSD_CHILD_KIND", "GSD_PROJECT_ROOT", "PYTHONPATH")}
    return subprocess.Popen([sys.executable, "-c", BUSY, str(root / "tools" / "probe_calibration.py"), "--margins"],
                            env=env, cwd=root, start_new_session=True)


def test_a_calibration_run_the_operator_started_survives_the_fleet(tmp_path):
    ours = tmp_path / "folder"
    ours.mkdir()
    run = _calibration(ours)
    orphan = _child(ours, "4096")
    try:
        deadline = time.monotonic() + 5
        while not fleet_children_running(ours) and time.monotonic() < deadline:
            time.sleep(0.05)
        killed = stop_fleet_children(ours, log=lambda *_: None)
        assert [int(c["pid"]) for c in killed] == [orphan.pid], "only the fleet's own child"
        assert run.poll() is None, "the operator's calibration run is untouched"
        from graph_scale_dynamics.operations.startup_reaper import reap_orphan_children
        assert reap_orphan_children(ours, dry_run=True)["orphans"] == [], "a start leaves it running too"
    finally:
        for proc in (run, orphan):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_a_child_whose_folder_cannot_be_read_is_not_this_folders(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("GSD_PROJECT_ROOT", "PYTHONPATH")}
    env["GSD_CHILD_KIND"] = "simulation"
    stray = subprocess.Popen([sys.executable, "-c", BUSY], env=env, start_new_session=True)
    try:
        time.sleep(0.3)
        assert all(int(c["pid"]) != stray.pid for c in stop_fleet_children(tmp_path, log=lambda *_: None))
        assert stray.poll() is None
    finally:
        stray.kill()
        stray.wait(timeout=5)
