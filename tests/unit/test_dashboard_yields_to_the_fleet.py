from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from graph_scale_dynamics.operations.subprocesses import yield_this_thread

ROOT = Path(__file__).resolve().parents[2]


def test_a_background_thread_yields_without_slowing_the_threads_that_answer_the_page():
    seen = {}

    def rebuild():
        yield_this_thread()
        seen["rebuild"] = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())

    before = os.getpriority(os.PRIO_PROCESS, 0)
    thread = threading.Thread(target=rebuild)
    thread.start()
    thread.join()
    assert seen["rebuild"] > before, "the rebuild thread did not lower its priority"
    assert os.getpriority(os.PRIO_PROCESS, 0) == before, "the request threads were slowed too"


def test_both_rebuild_children_yield_before_they_do_anything():
    probe = subprocess.run(
        [sys.executable, "-c",
         "import os,sys; sys.path.insert(0, %r); "
         "from graph_scale_dynamics.operations.subprocesses import yield_to_the_fleet; "
         "print(yield_to_the_fleet())" % str(ROOT)],
        capture_output=True, text=True, timeout=30)
    assert int(probe.stdout.strip()) >= 10
