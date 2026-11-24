from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from graph_scale_dynamics.observability.console import iso_utc_now

CONSOLE_LOG_CONTRACT = "gsd-console-log-1"
MAX_BYTES = 32 * 1024 * 1024
GENERATIONS = 3
WARN_EVERY_SECONDS = 60.0
_TERMINAL_LOCK = threading.Lock()
_LOGS: dict[str, "ConsoleLog"] = {}
_LOGS_LOCK = threading.Lock()


class ConsoleLog:
    def __init__(self, path: Path, *, max_bytes: int = MAX_BYTES, generations: int = GENERATIONS,
                 terminal=None):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.generations = max(1, int(generations))
        self.terminal = terminal
        self.failed_writes = 0
        self.last_error = ""
        self._handle = None
        self._lock = threading.Lock()
        self._warned_at = 0.0
        self._unwarned = 0

    def line(self, source: str, text: str) -> bool:
        data = f"{iso_utc_now()} [{source}] {text.rstrip(chr(10)).rstrip(chr(13))}\n".encode("utf-8", "replace")
        with self._lock:
            try:
                if self._handle is None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self._handle = open(self.path, "ab", buffering=0)
                self._handle.write(data)
                if self._handle.tell() > self.max_bytes:
                    self._rotate()
                return True
            except (OSError, ValueError) as exc:
                self.failed_writes += 1
                self._unwarned += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._close()
                self._warn()
                return False

    def _rotate(self) -> None:
        self._close()
        for index in range(self.generations - 1, 0, -1):
            older = self.path.with_suffix(self.path.suffix + f".{index}")
            if older.exists():
                os.replace(older, self.path.with_suffix(self.path.suffix + f".{index + 1}"))
        os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))
        self._handle = open(self.path, "ab", buffering=0)

    def _close(self) -> None:
        try:
            if self._handle is not None:
                self._handle.close()
        except OSError:
            pass
        self._handle = None

    def _warn(self) -> None:
        now = time.monotonic()
        if now - self._warned_at < WARN_EVERY_SECONDS:
            return
        self._warned_at = now
        message = (f"{iso_utc_now()} [console-log] {self._unwarned} line(s) not written to {self.path} "
                   f"({self.last_error}); the terminal still shows them\n")
        self._unwarned = 0
        terminal_write(message.encode("utf-8", "replace"), self.terminal)


def for_path(path: Path) -> ConsoleLog:
    key = str(Path(path).resolve())
    with _LOGS_LOCK:
        if key not in _LOGS:
            _LOGS[key] = ConsoleLog(Path(path))
        return _LOGS[key]


def terminal_write(data: bytes, terminal=None) -> None:
    stream = terminal if terminal is not None else sys.__stdout__
    try:
        with _TERMINAL_LOCK:
            target = getattr(stream, "buffer", None)
            if target is not None:
                target.write(data)
            else:
                stream.write(data.decode("utf-8", "replace"))
            stream.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _pump(pipe, source: str, log: ConsoleLog, terminal) -> None:
    try:
        for raw in iter(pipe.readline, b""):
            try:
                terminal_write(raw, terminal)
                log.line(source, raw.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                continue
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def popen_logged(cmd: list[str], *, source: str, var: Path | None = None, log_path: Path | None = None,
                 terminal=None, **kwargs) -> subprocess.Popen:
    if log_path is None:
        from graph_scale_dynamics.observability.evidence_sources import supervisor_log_path
        log_path = supervisor_log_path(Path(var))
    env = dict(kwargs.pop("env", None) or os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, **kwargs)
    reader = threading.Thread(target=_pump, args=(proc.stdout, str(source), for_path(log_path), terminal),
                              name=f"console-{source}", daemon=True)
    reader.start()
    return proc


class LineTee:
    def __init__(self, log: ConsoleLog, source: str = "supervisor"):
        self.log = log
        self.source = source
        self._partial = ""
        self._lock = threading.Lock()

    def feed(self, text: str) -> None:
        with self._lock:
            self._partial += text
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self.log.line(self.source, line)
