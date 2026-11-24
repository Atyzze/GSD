from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from graph_scale_dynamics.operations import server_lock

POSTMASTER = """
import signal, sys, time
note = sys.argv[-1]
def say(word):
    with open(note, "a") as handle:
        handle.write(word + "\\n")
def stop(*_):
    say("stop")
    sys.exit(0)
signal.signal(signal.SIGHUP, lambda *_: say("reload"))
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
say("ready")
while True:
    time.sleep(0.05)
"""

SUPERVISOR = """
import signal, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", *sys.argv[1:]], close_fds=False)
def gone(*_):
    child.terminate()
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, gone)
sys.exit(child.wait())
"""


def supervisor_argv(pgdata: Path, note: Path) -> list[str]:
    return [sys.executable, "-c", SUPERVISOR, POSTMASTER, "postgres", "-D", str(pgdata), str(note)]


def heard(note: Path, word: str, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if note.is_file() and word in note.read_text().split():
            return True
        time.sleep(0.02)
    return False


def start(lock: Path, pgdata: Path, note: Path, **record) -> subprocess.Popen:
    fd = server_lock.take(lock)
    assert fd is not None, f"{lock} is already held"
    try:
        process = subprocess.Popen(supervisor_argv(pgdata, note), pass_fds=(fd,), start_new_session=True,
                                   stdin=subprocess.DEVNULL)
        server_lock.write_record(fd, {"pid": process.pid, **record})
    finally:
        os.close(fd)
    assert heard(note, "ready"), "the fake postmaster did not start"
    return process


def end(process: subprocess.Popen, lock: Path | None = None) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + 10
    while lock is not None and server_lock.held(lock) and time.monotonic() < deadline:
        time.sleep(0.02)
