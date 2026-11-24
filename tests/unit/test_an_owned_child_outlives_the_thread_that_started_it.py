from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations import process_ownership as P  # noqa: E402

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the parent-death signal is Linux's")

CHILD = ("import sys, time; sys.path.insert(0, sys.argv[1]);"
         "from graph_scale_dynamics.operations.process_ownership import die_with_owner;"
         "print(die_with_owner(), flush=True); time.sleep(30)")


def _start_on_a_short_thread(spawn) -> subprocess.Popen:
    out: dict = {}

    def run() -> None:
        out["p"] = spawn([sys.executable, "-c", CHILD, str(ROOT)], env=P.owned_env(), stdout=subprocess.PIPE,
                         text=True, start_new_session=True)
        out["armed"] = out["p"].stdout.readline().strip()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=20)
    assert out.get("armed") == "armed", out
    return out["p"]


def _alive_after(process: subprocess.Popen, seconds: float = 1.5) -> bool:
    time.sleep(seconds)
    return process.poll() is None


def test_a_child_started_from_a_short_thread_outlives_it():
    process = _start_on_a_short_thread(P.popen_owned)
    try:
        assert _alive_after(process), "the child went with the thread that asked for it"
    finally:
        process.kill()
        process.wait(timeout=5)


def test_the_kernel_follows_the_thread_which_is_why():
    process = _start_on_a_short_thread(subprocess.Popen)
    try:
        assert not _alive_after(process), "a plain Popen from a short thread survived; re-read popen_owned"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_every_owned_child_a_thread_can_start_goes_through_it():
    for path in ("graph_scale_dynamics/observability/membw_dashboard.py",
                 "graph_scale_dynamics/operations/quiet_report.py",
                 "graph_scale_dynamics/operations/power_sidecar.py"):
        text = (ROOT / path).read_text()
        assert "popen_owned(" in text, path
        at = text.index("owned_env(")
        assert "subprocess.Popen(" not in text[text.rindex("\n\n\n", 0, at):text.index("\n\n\n", at)], path
