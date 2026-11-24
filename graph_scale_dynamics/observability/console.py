from __future__ import annotations

import datetime as dt
import os
import sys
import threading
from pathlib import Path


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TimestampedStream:
    def __init__(self, raw, service: str):
        self.raw = raw
        self.service = service
        self._line_start = True
        self._lock = threading.Lock()

    def write(self, text: str):
        if not text:
            return 0
        with self._lock:
            for part in text.splitlines(keepends=True):
                if self._line_start and part:
                    self.raw.write(f"{iso_utc_now()} [{self.service}] ")
                self.raw.write(part)
                self._line_start = part.endswith("\n") or part.endswith("\r")
            self.raw.flush()
        return len(text)

    def flush(self):
        self.raw.flush()

    def isatty(self):
        return self.raw.isatty()

    def fileno(self):
        return self.raw.fileno()

    @property
    def encoding(self):
        return getattr(self.raw, "encoding", "utf-8")


class TeeStream:
    def __init__(self, raw, log_handle, lock: threading.RLock):
        self.raw = raw
        self.log_handle = log_handle
        self._lock = lock

    def write(self, text: str):
        if not text:
            return 0
        with self._lock:
            self.raw.write(text)
            self.raw.flush()
            self.log_handle.write(text)
            self.log_handle.flush()
        return len(text)

    def flush(self):
        with self._lock:
            self.raw.flush()
            self.log_handle.flush()

    def isatty(self):
        return self.raw.isatty()

    def fileno(self):
        return self.raw.fileno()

    @property
    def encoding(self):
        return getattr(self.raw, "encoding", "utf-8")


def install(service: str):
    old = (sys.stdout, sys.stderr)
    sys.stdout = TimestampedStream(sys.stdout, service)
    sys.stderr = TimestampedStream(sys.stderr, service)
    return old


def restore(old) -> None:
    sys.stdout, sys.stderr = old


def install_append_log(path: Path, *, argv: list[str] | None = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    handle = os.fdopen(fd, "a", encoding="utf-8", buffering=1)
    lock = threading.RLock()
    old = (sys.stdout, sys.stderr)
    sys.stdout = TeeStream(old[0], handle, lock)
    sys.stderr = TeeStream(old[1], handle, lock)
    command = " ".join(argv or sys.argv)
    with lock:
        handle.write(f"\n===== main session {iso_utc_now()} pid={os.getpid()} command={command} =====\n")
        handle.flush()
    return old, handle


def restore_append_log(state) -> None:
    if not state:
        return
    old, handle = state
    try:
        with getattr(sys.stdout, "_lock", threading.RLock()):
            handle.write(f"===== main session end {iso_utc_now()} pid={os.getpid()} =====\n")
            handle.flush()
    except Exception:
        pass
    sys.stdout, sys.stderr = old
    try:
        handle.close()
    except Exception:
        pass


def error(service: str, message: str) -> None:
    print(f"{iso_utc_now()} [{service}] ERROR {message}", file=sys.stderr, flush=True)
