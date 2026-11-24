from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import sys
import threading
import time
from pathlib import Path

_DEFAULT_FLUSH_BYTES = 64 * 1024
WARNING_INTERVAL_SECONDS = 60.0
_DEFAULT_FLUSH_SECONDS = 4.0
_IMMEDIATE_EVENTS = frozenset({
    "start", "exit", "stop", "shutdown", "error", "failure", "failed",
    "fatal", "crash", "fence", "violation", "alert", "corruption",
})


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class Log:
    def __init__(self, root: str | Path, service: str):
        runtime_log_dir = os.environ.get("GSD_RUNTIME_LOG_DIR", "").strip()
        log_root = Path(runtime_log_dir) if runtime_log_dir else (Path(root) / "log")
        self.path = log_root / f"{service}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.service = service
        self.max_bytes = max(64 * 1024, int(os.environ.get("GSD_LOG_MAX_BYTES", "25000000")))
        self.retained = max(1, int(os.environ.get("GSD_LOG_RETAINED", "5")))
        self.run_id = os.environ.get("GSD_RUN_ID") or f"{os.getpid()}-{time.time_ns():x}"
        self.flush_bytes = max(0, int(os.environ.get("GSD_LOG_FLUSH_BYTES", _DEFAULT_FLUSH_BYTES)))
        self.flush_seconds = max(0.0, float(os.environ.get("GSD_LOG_FLUSH_SECONDS", _DEFAULT_FLUSH_SECONDS)))
        self._always_flush = _truthy(os.environ.get("GSD_LOG_SYNCHRONOUS"))
        self._fsync = os.environ.get("GSD_LOG_FSYNC") == "1"
        self._echo = bool(os.environ.get("GSD_LOG_STDERR"))
        self._lock = threading.Lock()
        self._buffer: list[bytes] = []
        self._buffered_bytes = 0
        self._last_flush = time.monotonic()
        self._handle = None
        self._handle_bytes = 0
        self._warned_at = None
        self._unwarned = 0
        atexit.register(self.close)

    def _open(self) -> None:
        if self._handle is not None:
            return
        self._handle = self.path.open("ab", buffering=0)
        try:
            self._handle_bytes = self.path.stat().st_size
        except OSError:
            self._handle_bytes = 0

    def _close_handle(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None and not handle.closed:
            try:
                handle.close()
            except OSError:
                pass

    def _rotate_if_needed(self, incoming: int) -> None:
        if self._handle_bytes + incoming <= self.max_bytes:
            return
        self._close_handle()
        oldest = self.path.with_suffix(self.path.suffix + f".{self.retained}")
        oldest.unlink(missing_ok=True)
        for index in range(self.retained - 1, 0, -1):
            source = self.path.with_suffix(self.path.suffix + f".{index}")
            if source.exists():
                source.replace(self.path.with_suffix(self.path.suffix + f".{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
        self._handle_bytes = 0

    def _write_batch(self, batch: list[bytes]) -> None:
        if not batch:
            return
        payload = b"".join(batch)
        self._open()
        handle = self._handle
        if handle is None:
            return
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        handle.write(payload)
        self._handle_bytes += len(payload)
        if self._fsync:
            os.fsync(handle.fileno())

    def _flush_locked(self) -> None:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return
        pending, self._buffer = self._buffer, []
        self._buffered_bytes = 0
        self._last_flush = time.monotonic()
        try:
            batch: list[bytes] = []
            batch_bytes = 0
            for line in pending:
                if self._handle_bytes + batch_bytes + len(line) > self.max_bytes:
                    if batch:
                        self._write_batch(batch)
                        batch, batch_bytes = [], 0
                    self._rotate_if_needed(len(line))
                batch.append(line)
                batch_bytes += len(line)
            if batch:
                self._write_batch(batch)
        except OSError as exc:
            self._warn(exc)
            self._close_handle()

    def _warn(self, exc: OSError) -> None:
        now = time.monotonic()
        if self._warned_at is not None and now - self._warned_at < WARNING_INTERVAL_SECONDS:
            self._unwarned += 1
            return
        also = f" ({self._unwarned} more since the last warning)" if self._unwarned else ""
        print(f"warning: log write failed for {self.service}: {exc}{also}", file=sys.stderr, flush=True)
        self._warned_at, self._unwarned = now, 0

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        try:
            with self._lock:
                self._flush_locked()
                self._close_handle()
        except Exception:
            pass

    def _should_flush(self, event: str) -> bool:
        if self._always_flush or self.flush_seconds <= 0:
            return True
        if str(event).lower() in _IMMEDIATE_EVENTS:
            return True
        if self.flush_bytes and self._buffered_bytes >= self.flush_bytes:
            return True
        return (time.monotonic() - self._last_flush) >= self.flush_seconds

    def write(self, event: str, **fields) -> None:
        epoch = time.time()
        record = {
            "ts": round(epoch, 3),
            "utc": dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(timespec="milliseconds")
                     .replace("+00:00", "Z"),
            "service": self.service,
            "pid": os.getpid(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        line = (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            self._buffer.append(line)
            self._buffered_bytes += len(line)
            if self._should_flush(event):
                self._flush_locked()
        if self._echo:
            print(line.decode("utf-8").rstrip(), file=sys.stderr)
