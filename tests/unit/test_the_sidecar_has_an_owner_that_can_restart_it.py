from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import power_sidecar

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not power_sidecar.operator_config_path(), reason="no HOME to seed a config from")
def test_a_btop_that_dies_is_replaced_by_the_publisher(tmp_path):
    import shutil

    if not shutil.which("btop"):
        pytest.skip("btop is not installed here")
    pid = power_sidecar.ensure_publisher(tmp_path, log=lambda *a, **k: None)
    if pid is None:
        pytest.skip("the publisher did not start on this host")
    try:
        first = power_sidecar.read_published(tmp_path)
        assert first["published"] is True
        drawn_by = time.monotonic() + 60.0
        while not first.get("frame_at") and time.monotonic() < drawn_by:
            time.sleep(0.5)
            first = power_sidecar.read_published(tmp_path)
        if not first.get("frame_at"):
            pytest.skip("btop drew no frame within a minute here, so it is retried after the backoff by design")
        btop_pid = first.get("btop_pid")
        assert btop_pid, "the publisher reported no btop"

        os.kill(int(btop_pid), signal.SIGKILL)
        deadline = time.monotonic() + 30.0
        replaced = None
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = power_sidecar.read_published(tmp_path)
            if now.get("btop_pid") and int(now["btop_pid"]) != int(btop_pid):
                replaced = now
                break
        assert replaced is not None, (
            "the publisher did not replace a btop that was killed. 495 could not do this at "
            "all, which is the reason this build exists.")
        assert replaced.get("restarts", 0) >= 1
    finally:
        power_sidecar.stop_publisher(tmp_path)
