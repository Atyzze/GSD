from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import power_sidecar

ROOT = Path(__file__).resolve().parents[2]
needs_btop = pytest.mark.skipif(shutil.which("btop") is None, reason="btop is not installed")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def _wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


@needs_btop
@pytest.mark.skipif(not power_sidecar.operator_config_path(), reason="no HOME to seed a config from")
def test_the_publishers_btop_dies_when_the_publisher_is_killed(tmp_path):
    pid = power_sidecar.ensure_publisher(tmp_path, log=lambda *a, **k: None)
    if pid is None:
        pytest.skip("the publisher did not start on this host")
    btop_pid = power_sidecar.read_published(tmp_path).get("btop_pid")
    try:
        assert btop_pid, "the publisher reported no btop"
        os.kill(int(pid), signal.SIGKILL)
        assert _wait_gone(int(btop_pid), 5.0), (
            f"btop {btop_pid} outlived its publisher; an orphaned sidecar spins at a full core")
    finally:
        for victim in (pid, btop_pid):
            if victim and _alive(int(victim)):
                os.kill(int(victim), signal.SIGKILL)


@needs_btop
@pytest.mark.skipif(not power_sidecar.operator_config_path(), reason="no HOME to seed a config from")
def test_an_orphaned_sidecar_btop_is_reaped_and_the_operators_is_not(tmp_path):
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from graph_scale_dynamics.operations import power_sidecar
        handle = power_sidecar.start(None, started_by="api")
        print(handle.pid, flush=True)
        # exits without stop(): the btop is orphaned
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    orphan = int(out.stdout.strip().splitlines()[-1])
    own = subprocess.Popen(["btop", "--version"], stdout=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline, killed = time.monotonic() + 10.0, []
        while time.monotonic() < deadline and orphan not in killed:
            killed += power_sidecar.reap_orphaned_sidecars()
            if orphan not in killed:
                time.sleep(0.1)
        assert orphan in killed and _wait_gone(orphan, 5.0)
        assert own.pid not in killed
    finally:
        own.wait(timeout=5)
        if _alive(orphan):
            os.kill(orphan, signal.SIGKILL)
