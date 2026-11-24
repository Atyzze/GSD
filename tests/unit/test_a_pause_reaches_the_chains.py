from __future__ import annotations

import subprocess
import sys
import time

from graph_scale_dynamics.artifact_store.resume_state import STOP_FILE_NAME, stop_file_for
from graph_scale_dynamics.services.worker import main as worker

WATCHER = """
import sys, time
from pathlib import Path
stop = Path(sys.argv[1])
end = time.monotonic() + 60
while time.monotonic() < end:
    if stop.exists():
        raise SystemExit(75)
    time.sleep(0.05)
raise SystemExit(1)
"""


def test_the_worker_writes_the_stop_file_the_child_watches(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    job_file = staging / "job.json"
    job_file.write_text("{}")
    watched = stop_file_for(job_file)
    assert watched == staging / STOP_FILE_NAME
    child = subprocess.Popen([sys.executable, "-c", WATCHER, str(watched)], start_new_session=True,
                             stderr=subprocess.PIPE)
    monkeypatch.setattr(worker, "CURRENT_CHILD", child)
    started = time.monotonic()
    try:
        worker.stop_current_child(staging, grace=20.0)
        code = child.wait(timeout=5)
        assert code == 75, f"the child did not see the stop request ({code}): {child.stderr.read().decode()[-600:]}"
        assert time.monotonic() - started < 10, "the stop waited out the grace instead of being seen"
    finally:
        if child.poll() is None:
            child.kill()
