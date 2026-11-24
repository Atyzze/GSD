from __future__ import annotations

import atexit
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

DEFAULT_EXTERNAL_FILE = "/run/membw/latest.json"
DEFAULT_INTERVAL_SECONDS = 4.0
HISTORY_POINTS = 15
RETRY_SECONDS = 30.0


def _finite(value, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def find_existing_umc_perf_owner(proc_root: Path = Path("/proc")) -> tuple[int, str] | None:
    own_pid = os.getpid()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == own_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        if ("umc_mem_bandwidth" in cmd or "umc_data_bus_utilization" in cmd) and "perf" in cmd:
            return pid, cmd[:300]
    return None


class MemoryBandwidthMonitor:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.temp_dir: str | None = None
        self.private_file: Path | None = None
        self.log_file: Path | None = None
        self.retry_after_monotonic = 0.0
        self.last_error: str | None = None
        self.source: str | None = None
        self.history: deque[dict] = deque(maxlen=HISTORY_POINTS)
        self.seen_sample_ts: float | None = None
        self.started_monotonic: float | None = None
        self.last_observed_monotonic: float | None = None
        self.area_gb = 0.0
        self.elapsed_seconds = 0.0
        self.observed_min: float | None = None
        self.observed_max = 0.0
        self.cap_gbps: float | None = None
        self.cap_source: str | None = None
        self.ratios: deque[float] = deque(maxlen=64)

    @staticmethod
    def interval_seconds() -> float:
        raw = os.environ.get("GSD_MEMBW_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
        value = _finite(raw, minimum=1.0, maximum=60.0)
        return value if value is not None else DEFAULT_INTERVAL_SECONDS

    @staticmethod
    def source_mode() -> str:
        mode = os.environ.get("GSD_MEMBW_SOURCE", "auto").strip().lower()
        return mode if mode in {"auto", "file", "perf", "off"} else "auto"

    @staticmethod
    def external_file() -> Path:
        return Path(os.environ.get("GSD_MEMBW_FILE", DEFAULT_EXTERNAL_FILE)).expanduser()

    def _read_record(self, path: Path) -> tuple[dict | None, str | None]:
        try:
            stat = path.stat()
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return None, f"no collector file at {path}"
        except PermissionError:
            return None, f"cannot read collector file {path} (permission denied)"
        except (OSError, ValueError, TypeError) as exc:
            return None, f"collector file unreadable: {exc.__class__.__name__}: {exc}"
        if not isinstance(raw, dict):
            return None, "collector file is not a JSON object"

        age = max(0.0, time.time() - stat.st_mtime)
        published_interval = _finite(raw.get("interval"), minimum=0.02, maximum=3600.0)
        stale_after = max(12.0, 3.0 * (published_interval or self.interval_seconds()))
        if age > stale_after:
            return None, f"collector data is stale ({age:.0f}s old)"

        bw = _finite(raw.get("bw"), minimum=0.0, maximum=100000.0)
        util = _finite(raw.get("util"), minimum=0.0, maximum=100.0)
        ts = _finite(raw.get("ts"), minimum=0.0)
        cap = _finite(raw.get("cap"), minimum=0.001, maximum=100000.0)
        status = raw.get("status")
        if status is not None:
            status = str(status)
        return {
            "bw": bw,
            "util": util,
            "ts": ts if ts is not None else stat.st_mtime,
            "cap": cap,
            "cap_src": str(raw.get("cap_src") or "collector") if cap is not None else None,
            "interval": published_interval,
            "status": status,
            "file_age_seconds": age,
        }, None

    def _observe_locked(self, record: dict, source: str) -> None:
        sample_ts = float(record["ts"])
        if self.seen_sample_ts is not None and sample_ts == self.seen_sample_ts:
            return
        self.seen_sample_ts = sample_ts
        bw = record.get("bw")
        util = record.get("util")
        cap = record.get("cap")
        if cap is not None:
            self.cap_gbps = float(cap)
            self.cap_source = record.get("cap_src") or "collector"
        elif bw is not None and util is not None and util >= 15.0:
            ratio = float(bw) / (float(util) / 100.0)
            if math.isfinite(ratio) and ratio > 0:
                self.ratios.append(ratio)
                ratios = sorted(self.ratios)
                self.cap_gbps = ratios[len(ratios) // 2]
                self.cap_source = "bus util"
        now = time.monotonic()
        if bw is not None:
            bw = float(bw)
            if self.started_monotonic is None:
                self.started_monotonic = now
            if self.last_observed_monotonic is not None:
                dt = now - self.last_observed_monotonic
                if 0.0 < dt < 60.0:
                    self.area_gb += bw * dt
                    self.elapsed_seconds += dt
            self.last_observed_monotonic = now
            self.observed_min = bw if self.observed_min is None else min(self.observed_min, bw)
            self.observed_max = max(self.observed_max, bw)
            self.history.append({"ts": sample_ts, "bw": round(bw, 3)})
        self.source = source

    def _private_log_tail_locked(self) -> str | None:
        if self.log_file is None:
            return None
        try:
            text = self.log_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not text:
            return None
        return text[-1200:].replace("\x1b", "")

    def _cleanup_private_locked(self, *, remove_dir: bool = True) -> None:
        process = self.process
        temp_dir = self.temp_dir
        self.process = None
        self.private_file = None
        self.log_file = None
        self.temp_dir = None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1.0)
            except (OSError, subprocess.SubprocessError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
        if remove_dir and temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _start_private_locked(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        now = time.monotonic()
        if now < self.retry_after_monotonic:
            return False
        if not sys.platform.startswith("linux"):
            self.last_error = "memory-bandwidth perf collector is Linux-only"
            self.retry_after_monotonic = now + RETRY_SECONDS
            return False
        perf = shutil.which("perf")
        if not perf:
            self.last_error = "perf not found in PATH"
            self.retry_after_monotonic = now + RETRY_SECONDS
            return False
        owner = find_existing_umc_perf_owner()
        if owner is not None:
            pid, cmd = owner
            self.last_error = (
                f"another AMD UMC perf collector is active (pid={pid}); "
                "publish/read its JSON file or stop it before GSD claims the counters; "
                f"cmd={cmd}"
            )
            self.retry_after_monotonic = now + RETRY_SECONDS
            return False

        temp_dir = tempfile.mkdtemp(prefix="gsd-membw-")
        output = Path(temp_dir) / "latest.json"
        log = Path(temp_dir) / "collector.log"
        from graph_scale_dynamics.operations.process_ownership import owned_env, popen_owned
        env = owned_env(dict(os.environ, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1"))
        interval = self.interval_seconds()
        cmd = [
            sys.executable,
            "-m",
            "graph_scale_dynamics.observability.membw_tool",
            "--source",
            "perf",
            "--interval",
            f"{interval:g}s",
            "--serve",
            "--file",
            str(output),
        ]
        try:
            with log.open("ab", buffering=0) as log_handle:
                process = popen_owned(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                    env=env,
                    close_fds=True,
                    start_new_session=True,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.last_error = f"failed to start memory-bandwidth collector: {exc.__class__.__name__}: {exc}"
            self.retry_after_monotonic = now + RETRY_SECONDS
            return False

        self.process = process
        self.temp_dir = temp_dir
        self.private_file = output
        self.log_file = log
        self.last_error = None
        self.retry_after_monotonic = 0.0
        return True

    def _private_record_locked(self) -> tuple[dict | None, str | None]:
        if not self._start_private_locked():
            remaining = max(0.0, self.retry_after_monotonic - time.monotonic())
            detail = self.last_error or "memory-bandwidth collector unavailable"
            if remaining:
                detail += f"; retry in {remaining:.1f}s"
            return None, detail
        assert self.process is not None
        if self.process.poll() is not None:
            tail = self._private_log_tail_locked()
            code = self.process.returncode
            self.last_error = tail or f"memory-bandwidth collector exited with code {code}"
            self.retry_after_monotonic = time.monotonic() + RETRY_SECONDS
            self._cleanup_private_locked(remove_dir=True)
            return None, self.last_error
        assert self.private_file is not None
        record, error = self._read_record(self.private_file)
        if record is None and error and error.startswith("no collector file"):
            return None, "memory-bandwidth collector starting"
        return record, error

    def snapshot(self, *, start: bool = True, wait_seconds: float = 0.0) -> dict:
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        while True:
            with self.lock:
                mode = self.source_mode()
                if mode == "off":
                    return self._payload_locked(None, "disabled by GSD_MEMBW_SOURCE=off")

                record = None
                error = None
                source = None
                external = self.external_file()
                if mode in {"auto", "file"}:
                    record, error = self._read_record(external)
                    if record is not None:
                        source = f"file:{external}"
                if record is None and mode in {"auto", "perf"} and start:
                    record, perf_error = self._private_record_locked()
                    if record is not None:
                        source = "perf sidecar"
                        error = None
                    elif perf_error:
                        error = perf_error if mode == "perf" or not error else f"{error}; {perf_error}"
                if record is not None and source is not None:
                    self._observe_locked(record, source)
                    return self._payload_locked(record, record.get("status"))
                payload = self._payload_locked(None, error)
            if time.monotonic() >= deadline:
                return payload
            time.sleep(0.1)

    def _payload_locked(self, record: dict | None, status: str | None) -> dict:
        bw = None if record is None else record.get("bw")
        util = None if record is None else record.get("util")
        age = None if record is None else record.get("file_age_seconds")
        avg = self.area_gb / self.elapsed_seconds if self.elapsed_seconds > 0 else bw
        return {
            "available": bw is not None,
            "bandwidth_gbps": None if bw is None else round(float(bw), 2),
            "utilization_percent": None if util is None else round(float(util), 1),
            "average_gbps": None if avg is None else round(float(avg), 2),
            "observed_min_gbps": None if self.observed_min is None else round(self.observed_min, 2),
            "observed_max_gbps": round(self.observed_max, 2) if self.history else None,
            "cap_gbps": None if self.cap_gbps is None else round(self.cap_gbps, 1),
            "cap_source": self.cap_source,
            "source": self.source,
            "sample_age_seconds": None if age is None else round(float(age), 2),
            "refresh_seconds": self.interval_seconds(),
            "history_gbps": [item["bw"] for item in self.history],
            "status": status,
        }

    def status(self) -> dict:
        with self.lock:
            process = self.process
            return {
                "mode": self.source_mode(),
                "external_file": str(self.external_file()),
                "private_pid": None if process is None else process.pid,
                "private_running": bool(process is not None and process.poll() is None),
                "private_file": None if self.private_file is None else str(self.private_file),
                "last_error": self.last_error,
                "retry_after_seconds": max(0.0, self.retry_after_monotonic - time.monotonic()),
            } | self._payload_locked(None, None)

    def close(self) -> None:
        with self.lock:
            self._cleanup_private_locked(remove_dir=True)


MONITOR = MemoryBandwidthMonitor()
atexit.register(MONITOR.close)
