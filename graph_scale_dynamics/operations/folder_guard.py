from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

FLEET_PID_FILE = "fleet.pid.json"
SERVE_PID_FILE = "serve.pid.json"


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_start_ticks(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
    except OSError:
        return None
    try:
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (ValueError, IndexError):
        return None


def live_fleet(var: Path) -> str | None:
    return _live_record(Path(var) / FLEET_PID_FILE, "this folder's fleet is running (supervisor pid {pid}, "
                        "started {started})")


def live_serve(var: Path) -> str | None:
    return _live_record(Path(var) / SERVE_PID_FILE, "this folder's dashboard is being served (`main.py serve`, "
                        "pid {pid}, started {started})")


def live_in_folder(root: Path, *names: str) -> str | None:
    root, names = Path(root), names or (FLEET_PID_FILE, SERVE_PID_FILE)
    skip = {"instance", ".git", "blobs", "build", "wheel", "node_modules", "__pycache__", ".venv", "graph_scale_dynamics",
            "tests", "docs", "tools", "engine_rs"}
    for directory, children, files in os.walk(Path(root)):
        depth = len(Path(directory).relative_to(root).parts)
        children[:] = [] if depth >= 3 else [c for c in children if c not in skip]
        for name in names:
            if name in files:
                reading = (live_fleet if name == FLEET_PID_FILE else live_serve)(Path(directory))
                if reading:
                    return reading
    return None


def _live_record(path: Path, running: str) -> str | None:
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    pid = int(record.get("pid") or 0)
    if str(record.get("host")) != socket.gethostname():
        return (f"{path} names pid {pid} on host {record.get('host')!r}, which cannot be checked from "
                f"{socket.gethostname()!r}; stop it there, or delete that file if nothing runs")
    if not pid or not _alive(pid):
        return None
    recorded = record.get("start_ticks")
    if recorded is not None and process_start_ticks(pid) not in (None, int(recorded)):
        return None
    return running.format(pid=pid, started=record.get("started_utc"))


def record_this_process(path: Path, **extra) -> str | None:
    text = json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                       "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "start_ticks": process_start_ticks(os.getpid()), **extra})
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
    except OSError:
        return None
    return text


@contextmanager
def on_record(path: Path):
    text = record_this_process(path)
    try:
        yield text
    finally:
        unlink_if_ours(path, text)


def reap_orphaned_fleet_lock(repo, var: Path, lock_name: str) -> bool:
    holder = repo.service_lock_holder(lock_name)
    if holder is None:
        return bool(repo.acquire_service_lock(lock_name))
    try:
        record = json.loads((Path(var) / FLEET_PID_FILE).read_text())
    except (OSError, ValueError):
        record = None
    where = (f"backend pid {holder.get('pid')} (backend started {holder.get('backend_start')}, "
             f"{holder.get('state')})")
    if not record:
        print(f"fleet lock held by {where}; no {var / FLEET_PID_FILE} from that fleet, so this "
              "build cannot tell whether it is alive. Stop it, or wait for its backend to exit.")
        return False
    if str(record.get("host")) != socket.gethostname():
        print(f"fleet lock held by {where}, recorded by pid {record.get('pid')} on host "
              f"{record.get('host')!r}; this is {socket.gethostname()!r}, so its liveness "
              "cannot be checked from here. Stop it there.")
        return False
    pid = int(record.get("pid") or 0)
    if pid and _alive(pid):
        print(f"fleet lock held by {where}, owned by live supervisor pid {pid} "
              f"(started {record.get('started_utc')}). Stop it with Ctrl-C or "
              f"`kill {pid}`; do not start a second fleet on this database.")
        return False
    print(f"fleet lock held by {where}, but its supervisor pid {pid} (started "
          f"{record.get('started_utc')}) is gone: an orphaned fleet. Terminating that "
          "backend and taking the lock.")
    terminated = repo.terminate_service_lock_holder(lock_name)
    for _ in range(50):
        if repo.acquire_service_lock(lock_name):
            print(f"fleet lock reaped from backend pid {terminated}")
            return True
        time.sleep(0.1)
    print(f"terminated backend pid {terminated} but the lock is still held; refusing")
    return False


def postgres_running(root: Path) -> bool:
    helper = Path(root) / "tools" / "postgres_instance.py"
    if not helper.is_file():
        return False
    try:
        return subprocess.run([sys.executable, str(helper), "status"], cwd=root, capture_output=True, text=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def unlink_if_ours(path: Path, written: str | None) -> None:
    try:
        if written is not None and Path(path).read_text(encoding="utf-8") == written:
            Path(path).unlink()
    except OSError:
        pass
