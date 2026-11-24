from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

LOCK_NAME = "server.lock"
TAKE_SECONDS = 2.0


def take(path: Path, *, seconds: float = TAKE_SECONDS) -> int | None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.05)


def held(path: Path) -> bool | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def write_record(fd: int, record: dict) -> None:
    data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    os.ftruncate(fd, 0)
    os.pwrite(fd, data, 0)


def read_record(path: Path) -> dict:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def _holds(pid: int, identity: tuple[int, int]) -> bool:
    folder = f"/proc/{int(pid)}/fd"
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    for name in names:
        try:
            stat = os.stat(f"{folder}/{name}")
        except OSError:
            continue
        if (stat.st_dev, stat.st_ino) == identity:
            return True
    return False


def holds(pid: int, path: Path) -> bool:
    identity = _identity(Path(path))
    return identity is not None and int(pid) > 1 and _holds(int(pid), identity)


def _parent(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def holders(path: Path) -> list[int]:
    identity = _identity(Path(path))
    if identity is None:
        return []
    found = []
    for name in os.listdir("/proc"):
        if name.isdigit() and int(name) > 1 and int(name) != os.getpid() and _holds(int(name), identity):
            found.append(int(name))
    return sorted(found)


def first_holder(path: Path) -> int | None:
    found = holders(path)
    roots = [pid for pid in found if _parent(pid) not in found]
    return min(roots or found) if found else None


def holder(path: Path) -> int | None:
    if not held(path):
        return None
    pid = read_record(path).get("pid")
    if isinstance(pid, int) and holds(pid, path):
        return pid
    return first_holder(path)
