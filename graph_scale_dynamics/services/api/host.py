from __future__ import annotations

import atexit
import math
import os
import psutil
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from graph_scale_dynamics import PROJECT_ROOT
from graph_scale_dynamics.observability.cpu_sensors import (
    _btop_hwmon_temperature_sensors, _powercap_energy_zones, _read_number, _read_number_diagnostic,
)
from graph_scale_dynamics.observability.host_resources import (
    cpu_iowait_sampled as _cpu_iowait_sampled, cpu_percent_sampled as _cpu_percent_sampled,
)
from graph_scale_dynamics.observability.membw_dashboard import MONITOR as MEMBW_MONITOR
from graph_scale_dynamics.operations import power_sidecar as _power_sidecar


_SERVICE_PROC_SAMPLES: dict[int, tuple[float, float, int | None, int | None]] = {}
_SAMPLES_KEPT = 64
_SAMPLES_LOCK = threading.Lock()


def _service_process_sample(pid: int) -> dict:
    now = time.monotonic()
    try:
        proc = psutil.Process(int(pid))
        cpu = proc.cpu_times()
        cpu_total = float(cpu.user + cpu.system)
        mem = proc.memory_info()
        io_available = True
        try:
            io = proc.io_counters()
            read_bytes, write_bytes = int(io.read_bytes), int(io.write_bytes)
        except (psutil.AccessDenied, AttributeError):
            io_available = False
            read_bytes = write_bytes = None
        with _SAMPLES_LOCK:
            prior = _SERVICE_PROC_SAMPLES.get(int(pid))
        cpu_percent = read_bps = write_bps = None
        if prior is not None:
            then, prior_cpu, prior_read, prior_write = prior
            dt = max(1e-6, now - then)
            cpu_percent = max(0.0, 100.0 * (cpu_total - prior_cpu) / dt)
            if read_bytes is not None and prior_read is not None:
                read_bps = max(0.0, (read_bytes - prior_read) / dt)
            if write_bytes is not None and prior_write is not None:
                write_bps = max(0.0, (write_bytes - prior_write) / dt)
        with _SAMPLES_LOCK:
            _SERVICE_PROC_SAMPLES[int(pid)] = (now, cpu_total, read_bytes, write_bytes)
            known = list(_SERVICE_PROC_SAMPLES) if len(_SERVICE_PROC_SAMPLES) > _SAMPLES_KEPT else []
        gone = [p for p in known if not psutil.pid_exists(p)]
        if gone:
            with _SAMPLES_LOCK:
                for p in gone:
                    _SERVICE_PROC_SAMPLES.pop(p, None)
        return {
            "pid": int(pid), "process_state": proc.status(), "rss_bytes": int(mem.rss),
            "cpu_percent_one_core": None if cpu_percent is None else round(cpu_percent, 2),
            "read_bytes_per_second": None if read_bps is None else round(read_bps, 1),
            "write_bytes_per_second": None if write_bps is None else round(write_bps, 1),
            "io_counters_available": io_available,
            "io_rate_ready": read_bps is not None or write_bps is not None,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, ValueError):
        with _SAMPLES_LOCK:
            _SERVICE_PROC_SAMPLES.pop(int(pid), None)
        return {"pid": int(pid), "process_state": "missing", "rss_bytes": None,
                "cpu_percent_one_core": None, "read_bytes_per_second": None,
                "write_bytes_per_second": None, "io_counters_available": False,
                "io_rate_ready": False}

_SWALLOWED_LOG: dict[str, float] = {}


def _note_swallowed(where: str, exc: BaseException) -> None:
    now = time.monotonic()
    last = _SWALLOWED_LOG.get(where)
    if last is not None and now - last < 60.0:
        return
    _SWALLOWED_LOG[where] = now
    frame = exc.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    origin = (f"{frame.tb_frame.f_code.co_filename.rsplit('/', 1)[-1]}:{frame.tb_lineno}"
              if frame is not None else "?")
    print(f"[api] {where}: swallowed {type(exc).__name__}: "
          f"{str(exc).splitlines()[0][:160] if str(exc) else ''} (at {origin})",
          file=sys.stderr, flush=True)


_cpu_percent_sampled()

_DISK_IO_LOCK = threading.Lock()
_DISK_IO_STATE: tuple[float, int, int] | None = None

def _disk_io_rates() -> tuple[float | None, float | None]:
    global _DISK_IO_STATE
    try:
        counters = psutil.disk_io_counters()
    except (OSError, RuntimeError):
        return None, None
    if counters is None:
        return None, None
    now = time.monotonic()
    read = int(counters.read_bytes or 0)
    write = int(counters.write_bytes or 0)
    with _DISK_IO_LOCK:
        prior = _DISK_IO_STATE
        _DISK_IO_STATE = (now, read, write)
    if prior is None:
        return None, None
    dt = now - prior[0]
    if dt <= 0:
        return None, None
    return max(0.0, (read - prior[1]) / dt), max(0.0, (write - prior[2]) / dt)

_CPU_SENSOR_LOCK = threading.Lock()
_RAPL_ENERGY_STATE: dict[str, tuple[int, float]] = {}


_btop_configured_cpu_sensor = _power_sidecar.configured_cpu_sensor


def _cpu_temperature_snapshot(hwmon_root: Path = Path("/sys/class/hwmon"),
                              thermal_root: Path = Path("/sys/class/thermal")) -> tuple[float | None, str | None, str | None]:
    records = _btop_hwmon_temperature_sensors(hwmon_root, thermal_root)
    by_name = {str(record["name"]): record for record in records}
    override = os.environ.get("GSD_CPU_SENSOR", "").strip()
    if override and override in by_name:
        selected = by_name[override]
        return selected["temperature_celsius"], selected["name"], selected["path"]

    configured, _ = _btop_configured_cpu_sensor()
    if configured and configured in by_name:
        selected = by_name[configured]
        return selected["temperature_celsius"], selected["name"], selected["path"]

    _, btop_temp, btop_detail = _btop_telemetry_snapshot(start=False)
    if btop_temp is not None:
        return btop_temp, "btop sidecar", btop_detail

    if not records:
        getter = getattr(psutil, "sensors_temperatures", None)
        if getter is None:
            return None, None, None
        try:
            groups = getter(fahrenheit=False) or {}
        except (AttributeError, NotImplementedError, OSError):
            return None, None, None
        for group_name, entries in groups.items():
            for entry in entries or ():
                try:
                    current = float(entry.current)
                except (AttributeError, TypeError, ValueError):
                    continue
                if math.isfinite(current) and -20 <= current <= 150:
                    label = str(getattr(entry, "label", "") or "temp")
                    return current, f"psutil:{group_name}/{label}", None
        return None, None, None

    for record in records:
        if record["preferred"]:
            return record["temperature_celsius"], record["name"], record["path"]

    k10_ccd = [record for record in records
               if str(record.get("group", "")).lower() == "k10temp"
               and str(record.get("label", "")).lower().startswith("tccd")]
    if k10_ccd:
        def ccd_index(record: dict) -> int:
            label = str(record.get("label", ""))
            digits = "".join(ch for ch in label if ch.isdigit())
            return int(digits) if digits else -1
        selected = max(k10_ccd, key=ccd_index)
        return selected["temperature_celsius"], selected["name"], selected["path"]

    cpuish = [record for record in records
              if "cpu" in str(record["name"]).lower()
              or "k10temp" in str(record["name"]).lower()]
    if cpuish:
        selected = cpuish[0]
        return selected["temperature_celsius"], selected["name"], selected["path"]

    selected = records[0]
    return selected["temperature_celsius"], selected["name"], selected["path"]


_BTOP_TELEMETRY_LOCK = threading.RLock()
_BTOP_PROCESS: subprocess.Popen | None = None
_BTOP_MASTER_FD: int | None = None
_BTOP_READER_THREAD: threading.Thread | None = None
_BTOP_TEMP_DIR: str | None = None
_BTOP_HANDLE: "_power_sidecar.Handle | None" = None
_BTOP_STATE: dict[str, object] = {
    "watts": None,
    "watts_monotonic": 0.0,
    "temperature_celsius": None,
    "last_sample_monotonic": 0.0,
    "last_error": None,
    "path": None,
    "pid": None,
    "retry_after_monotonic": 0.0,
}

_BTOP_ANSI_RE = _power_sidecar.ANSI_RE
_BTOP_CPU_LINE_RE = _power_sidecar.CPU_LINE_RE

_BTOP_WANTED_FLAGS = _power_sidecar.WANTED_FLAGS
_BTOP_TTY_OFF_FLAGS = _power_sidecar.TTY_OFF_FLAGS
_btop_supported_flags = _power_sidecar.supported_flags
_btop_argv = _power_sidecar.argv


_parse_btop_telemetry = _power_sidecar.parse_telemetry


def _btop_reader_loop(process: subprocess.Popen | None, master_fd: int) -> None:
    import select

    rolling = b""
    try:
        while process is None or process.poll() is None:
            try:
                ready, _, _ = select.select([master_fd], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 65536)
            except OSError as exc:
                with _BTOP_TELEMETRY_LOCK:
                    if _BTOP_PROCESS is process and process is not None:
                        _BTOP_STATE["last_error"] = f"btop PTY read failed: {exc.__class__.__name__}: {exc}"
                break
            if not chunk:
                break
            rolling = (rolling + chunk)[-131072:]
            temp, watts = _parse_btop_telemetry(rolling)
            if temp is None and watts is None:
                if _BTOP_CPU_LINE_RE.search(
                        _BTOP_ANSI_RE.sub("", rolling.decode("utf-8", "ignore")).replace("\n", " ")):
                    with _BTOP_TELEMETRY_LOCK:
                        if _BTOP_PROCESS is process or process is None:
                            _BTOP_STATE["frames_without_a_reading"] = int(
                                _BTOP_STATE.get("frames_without_a_reading") or 0) + 1
                            _BTOP_STATE["last_frame_monotonic"] = time.monotonic()
                continue
            with _BTOP_TELEMETRY_LOCK:
                if temp is not None:
                    _BTOP_STATE["temperature_celsius"] = temp
                if watts is not None:
                    _BTOP_STATE["watts"] = watts
                    _BTOP_STATE["watts_monotonic"] = time.monotonic()
                    _BTOP_STATE["frames_without_watts"] = 0
                    _BTOP_STATE["cpu_line_without_watts"] = None
                elif temp is not None:
                    _BTOP_STATE["frames_without_watts"] = int(
                        _BTOP_STATE.get("frames_without_watts") or 0) + 1
                    found = _BTOP_CPU_LINE_RE.search(
                        _BTOP_ANSI_RE.sub("", rolling.decode("utf-8", "ignore")).replace("\n", " "))
                    if found:
                        _BTOP_STATE["cpu_line_without_watts"] = found.group(0)[-400:]
                _BTOP_STATE["last_sample_monotonic"] = time.monotonic()
                _BTOP_STATE["last_error"] = None
    finally:
        with _BTOP_TELEMETRY_LOCK:
            if process is None:
                if _BTOP_HANDLE is not None and _BTOP_HANDLE.process is None:
                    _BTOP_STATE["last_error"] = (
                        "the sidecar the supervisor started has stopped; a replacement started "
                        "from here would be inside the scratch namespace and could not read the "
                        "package power. Restart the fleet for a new one.")
                    _BTOP_STATE["retry_after_monotonic"] = time.monotonic() + 3600.0
            elif _BTOP_PROCESS is process and process.poll() is not None:
                stderr = f"exit {process.returncode}"
                _BTOP_STATE["last_error"] = _BTOP_STATE.get("last_error") or f"btop sidecar stopped ({stderr})"
                _BTOP_STATE["retry_after_monotonic"] = time.monotonic() + 30.0


def _stop_btop_sidecar() -> None:
    global _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_READER_THREAD, _BTOP_TEMP_DIR, _BTOP_HANDLE
    with _BTOP_TELEMETRY_LOCK:
        process = _BTOP_PROCESS
        master_fd = _BTOP_MASTER_FD
        reader_thread = _BTOP_READER_THREAD
        temp_dir = _BTOP_TEMP_DIR
        _BTOP_PROCESS = None
        _BTOP_MASTER_FD = None
        _BTOP_READER_THREAD = None
        _BTOP_TEMP_DIR = None
        _BTOP_HANDLE = None
        _BTOP_STATE.update({
            "watts": None,
            "temperature_celsius": None,
            "last_sample_monotonic": 0.0,
            "last_error": None,
            "path": None,
            "pid": None,
            "retry_after_monotonic": 0.0,
        })

    if master_fd is not None:
        try:
            os.close(master_fd)
        except OSError:
            pass
    if process is not None:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.5)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=1.5)
                except (OSError, subprocess.SubprocessError):
                    pass
        else:
            try:
                process.wait(timeout=0)
            except (OSError, subprocess.SubprocessError):
                pass
    if (reader_thread is not None and reader_thread is not threading.current_thread()
            and reader_thread.is_alive()):
        reader_thread.join(timeout=2.0)
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


atexit.register(_stop_btop_sidecar)


def _start_btop_sidecar_locked() -> bool:
    global _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_READER_THREAD, _BTOP_TEMP_DIR, _BTOP_HANDLE
    if _BTOP_PROCESS is not None and _BTOP_PROCESS.poll() is None:
        return True
    try:
        handle = _power_sidecar.start(PROJECT_ROOT, started_by="api")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        _BTOP_STATE.update({
            "path": shutil.which("btop"),
            "pid": None,
            "last_error": (str(exc) if isinstance(exc, RuntimeError)
                           else f"failed to start btop telemetry: {exc.__class__.__name__}: {exc}"),
            "retry_after_monotonic": time.monotonic() + 30.0,
        })
        return False

    if handle.dropped_flags or handle.help_error:
        _BTOP_STATE["flags_dropped"] = list(handle.dropped_flags)
        _BTOP_STATE["help_error"] = handle.help_error
    _BTOP_HANDLE = handle
    _BTOP_PROCESS = handle.process
    _BTOP_MASTER_FD = handle.master_fd
    _BTOP_TEMP_DIR = handle.temp_dir
    _BTOP_STATE.update({
        "watts": None,
        "watts_monotonic": 0.0,
        "temperature_celsius": None,
        "last_sample_monotonic": 0.0,
        "last_error": None,
        "path": handle.path,
        "pid": handle.pid,
        "retry_after_monotonic": 0.0,
        "argv": list(handle.command),
        "config_seeded_from": handle.config_seeded_from,
        "config_inherited_keys": handle.config_inherited_keys,
    })
    thread = threading.Thread(target=_btop_reader_loop, args=(handle.process, handle.master_fd),
                              name="gsd-btop-telemetry", daemon=True)
    _BTOP_READER_THREAD = thread
    thread.start()
    return True


def _btop_sidecar_is_running_locked() -> bool:
    return _BTOP_PROCESS is not None and _BTOP_PROCESS.poll() is None


def _published_sidecar_reading() -> dict:
    return _power_sidecar.read_published(PROJECT_ROOT)


def _btop_telemetry_snapshot(*, start: bool = True, wait_seconds: float = 0.0) -> tuple[float | None, float | None, str]:
    published = _published_sidecar_reading()
    if published.get("published"):
        age = published.get("watts_age_seconds")
        detail = (f"btop sidecar pid={published.get('btop_pid')} path={published.get('btop_path')} "
                  f"published_age={published.get('published_age_seconds', 0.0):.2f}s"
                  + ("" if age is None else f" watts_age={age:.2f}s"))
        reason = _power_sidecar.why_no_watts(published) if published.get("watts") is None else None
        return (published.get("watts"), published.get("temperature_celsius"),
                f"{detail}; {reason}" if reason else detail)
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    attempted_restart = False
    while True:
        with _BTOP_TELEMETRY_LOCK:
            process_alive = _btop_sidecar_is_running_locked()
            last_seen = float(_BTOP_STATE.get("last_sample_monotonic") or 0.0)
            stale = bool(last_seen and time.monotonic() - last_seen > 5.0)
            retry_after = float(_BTOP_STATE.get("retry_after_monotonic") or 0.0)
            can_retry = time.monotonic() >= retry_after
            if start and (not process_alive or stale) and not attempted_restart and (stale or can_retry):
                inherited = _BTOP_HANDLE is not None and _BTOP_HANDLE.process is None
                if process_alive and stale and not inherited:
                    need_restart = True
                else:
                    need_restart = False
                    _start_btop_sidecar_locked()
                attempted_restart = True
            else:
                need_restart = False
            watts = _BTOP_STATE.get("watts")
            temp = _BTOP_STATE.get("temperature_celsius")
            path = _BTOP_STATE.get("path")
            pid = _BTOP_STATE.get("pid")
            error = _BTOP_STATE.get("last_error")
            last_seen = float(_BTOP_STATE.get("last_sample_monotonic") or 0.0)
        if need_restart:
            _stop_btop_sidecar()
            with _BTOP_TELEMETRY_LOCK:
                _start_btop_sidecar_locked()
            continue
        if start and not process_alive and error and time.monotonic() < retry_after:
            remaining = max(0.0, retry_after - time.monotonic())
            return None, None, f"btop sidecar path={path or '-'}; {error}; retry in {remaining:.1f}s"
        if last_seen and (watts is not None or temp is not None):
            now = time.monotonic()
            age = max(0.0, now - last_seen)
            watts_age = max(0.0, now - float(_BTOP_STATE.get("watts_monotonic") or 0.0))
            withdrawn = None
            if watts is not None and watts_age > _power_sidecar.READING_MAX_AGE_SECONDS:
                withdrawn, watts = watts_age, None
            if age > _power_sidecar.READING_MAX_AGE_SECONDS:
                watts = temp = None
            detail = f"btop sidecar pid={pid} path={path} sample_age={age:.2f}s"
            if withdrawn is not None:
                detail += (f"; the last wattage it drew was {withdrawn:.0f}s ago and is withheld, "
                           "because a reading that has not been redrawn is not the current power")
            elif watts is None and temp is None:
                detail += "; no frame in that time, so nothing here is current"
            return (None if watts is None else float(watts),
                    None if temp is None else float(temp), detail)
        if attempted_restart and error and not process_alive:
            return None, None, f"btop sidecar path={path or '-'}; {error}"
        if time.monotonic() >= deadline:
            detail = f"btop sidecar path={path or '-'}"
            if error:
                detail += f"; {error}"
            elif start:
                with _BTOP_TELEMETRY_LOCK:
                    frames = int(_BTOP_STATE.get("frames_without_a_reading") or 0)
                    dropped = list(_BTOP_STATE.get("flags_dropped") or [])
                detail += (f"; running and drawing, but {frames} CPU frame(s) carried neither a "
                           "temperature nor a wattage: this host's btop shows neither"
                           if frames else "; waiting for first CPU telemetry frame")
                if dropped:
                    detail += f"; this btop does not accept {', '.join(dropped)}"
            else:
                detail += "; not running"
            return None, None, detail
        time.sleep(0.05)


def _btop_telemetry_status() -> dict:
    published = _published_sidecar_reading()
    if published.get("published"):
        watts_age = published.get("watts_age_seconds")
        return {
            "source": "publisher",
            "path": published.get("btop_path"),
            "pid": published.get("btop_pid"),
            "running": bool(published.get("running")),
            "watts": published.get("watts"),
            "watts_age_seconds": watts_age,
            "watts_withdrawn_age_seconds": published.get("watts_withdrawn"),
            "temperature_celsius": published.get("temperature_celsius"),
            "sample_age_seconds": published.get("frame_age_seconds"),
            "published_age_seconds": published.get("published_age_seconds"),
            "last_error": published.get("last_error"),
            "retry_after_seconds": 0.0,
            "frames_without_watts": int(published.get("frames_without_watts") or 0),
            "frames_without_a_reading": 0,
            "cpu_line_without_watts": published.get("cpu_line_without_watts"),
            "no_watts_because": (None if published.get("watts") is not None
                                 else _power_sidecar.why_no_watts(published)),
            "started_by": published.get("started_by"),
            "exec_inside_scratch_namespace": published.get("exec_inside_scratch_namespace"),
            "btop_capabilities": list(published.get("btop_capabilities") or []),
            "rapl_energy_path": published.get("rapl_energy_path"),
            "rapl_readable_without_capability": published.get("rapl_readable_without_capability"),
            "config_seeded_from": published.get("config_seeded_from"),
            "config_inherited_keys": published.get("config_inherited_keys"),
            "argv": list(published.get("argv") or []),
        }
    with _BTOP_TELEMETRY_LOCK:
        running = _btop_sidecar_is_running_locked()
        now = time.monotonic()
        last_seen = float(_BTOP_STATE.get("last_sample_monotonic") or 0.0)
        watts_seen = float(_BTOP_STATE.get("watts_monotonic") or 0.0)
        watts_age = None if not watts_seen else max(0.0, now - watts_seen)
        watts = _BTOP_STATE.get("watts")
        withdrawn = None
        if watts is not None and (watts_age is None or watts_age > _power_sidecar.READING_MAX_AGE_SECONDS):
            withdrawn, watts = watts_age, None
        handle = _BTOP_HANDLE
        conditions = handle.conditions() if handle is not None else {
            "started_by": None, "exec_inside_scratch_namespace": None,
            "btop_capabilities": [], "rapl_energy_path": str(_power_sidecar.RAPL_ENERGY),
            "rapl_readable_without_capability": None, "config_seeded_from": None,
            "config_inherited_keys": 0, "argv": list(_BTOP_STATE.get("argv") or []),
        }
        conditions["watts_withdrawn"] = withdrawn
        conditions["frames_without_watts"] = int(_BTOP_STATE.get("frames_without_watts") or 0)
        return conditions | {
            "source": "api",
            "no_watts_because": None if watts is not None else _power_sidecar.why_no_watts(conditions),
            "watts_withdrawn_age_seconds": withdrawn,
            "watts_age_seconds": watts_age,
            "config_error": _BTOP_STATE.get("config_error"),
            "path": _BTOP_STATE.get("path"),
            "pid": _BTOP_STATE.get("pid"),
            "running": running,
            "watts": watts,
            "temperature_celsius": _BTOP_STATE.get("temperature_celsius"),
            "sample_age_seconds": None if not last_seen else max(0.0, now - last_seen),
            "last_error": _BTOP_STATE.get("last_error"),
            "retry_after_seconds": max(0.0, float(_BTOP_STATE.get("retry_after_monotonic") or 0.0) - now),
            "frames_without_a_reading": int(_BTOP_STATE.get("frames_without_a_reading") or 0),
            "cpu_line_without_watts": _BTOP_STATE.get("cpu_line_without_watts"),
        }


def _sample_rapl_zones(package_zones: list[Path]) -> tuple[float | None, float | None, int]:
    now = time.monotonic()
    watts_total = 0.0
    sampled = 0
    stalled = 0
    limit_total = 0.0
    limited = 0
    with _CPU_SENSOR_LOCK:
        for zone in package_zones:
            energy = _read_number(zone / "energy_uj")
            if energy is None:
                continue
            energy_i = int(energy)
            try:
                key = str((zone / "energy_uj").resolve())
            except OSError:
                key = str(zone / "energy_uj")
            previous = _RAPL_ENERGY_STATE.get(key)
            _RAPL_ENERGY_STATE[key] = (energy_i, now)
            if previous is not None:
                previous_energy, previous_time = previous
                elapsed = now - previous_time
                delta = energy_i - previous_energy
                if delta < 0:
                    maximum = _read_number(zone / "max_energy_range_uj")
                    if maximum is not None and maximum > 0:
                        delta += int(maximum)
                if elapsed > 0 and delta > 0:
                    watts = (delta / 1_000_000.0) / elapsed
                    if math.isfinite(watts) and 0 < watts <= 5000:
                        watts_total += watts
                        sampled += 1
                elif elapsed > 0 and delta == 0:
                    stalled += 1
            limit = _read_number(zone / "constraint_0_power_limit_uw")
            if limit is not None and limit > 0:
                limit_total += limit / 1_000_000.0
                limited += 1
    return (watts_total if sampled else None,
            limit_total if limited else None,
            stalled)


def _rapl_power_snapshot_detailed(powercap_root: Path = Path("/sys/class/powercap")) -> tuple[float | None, float | None, str]:
    exact_zone = powercap_root / "intel-rapl:0"
    exact_energy = exact_zone / "energy_uj"
    value, error = _read_number_diagnostic(exact_energy)
    exact_problem: str | None = None
    if value is not None:
        watts, limit, stalled = _sample_rapl_zones([exact_zone])
        detail = str(exact_energy)
        if watts is not None:
            return watts, limit, detail
        if stalled:
            exact_problem = f"{exact_energy} is readable but its energy counter did not advance between samples"
        else:
            detail += " (sampling primed; next dashboard poll yields watts)"
            return watts, limit, detail
    if exact_problem is not None:
        pass
    elif error == "permission denied":
        if Path(powercap_root) == Path("/sys/class/powercap"):
            btop_watts, _, btop_detail = _btop_telemetry_snapshot(start=True, wait_seconds=0.0)
            if btop_watts is not None:
                return btop_watts, None, btop_detail
        exact_problem = f"permission denied reading {exact_energy}"
        if Path(powercap_root) == Path("/sys/class/powercap"):
            exact_problem += f"; {btop_detail}"
    else:
        exact_problem = f"{exact_energy}: {error}"

    package_zones: list[Path] = []
    for zone in _powercap_energy_zones(powercap_root):
        if zone == exact_zone or not (zone / "energy_uj").is_file():
            continue
        try:
            zone_name = (zone / "name").read_text(encoding="utf-8").strip().lower()
        except OSError:
            zone_name = zone.name.lower()
        if (zone_name.startswith("package-") or zone_name.startswith("package ")
                or zone_name == "package"):
            package_zones.append(zone)
    if package_zones:
        watts, limit, stalled = _sample_rapl_zones(package_zones)
        if watts is not None:
            return watts, limit, ", ".join(str(zone / "energy_uj") for zone in package_zones)
        if stalled:
            exact_problem = (f"{stalled} package zone(s) readable but their energy counters "
                             f"did not advance between samples: "
                             + ", ".join(str(zone / "energy_uj") for zone in package_zones))
        if limit is not None:
            return None, limit, exact_problem
    return None, None, exact_problem


def _hwmon_power_snapshot(hwmon_root: Path = Path("/sys/class/hwmon")) -> tuple[float | None, float | None]:
    from graph_scale_dynamics.observability.host_resources import hwmon_power_snapshot
    watts, cap, _path = hwmon_power_snapshot(hwmon_root)
    return watts, cap


def _cpu_power_snapshot_detailed() -> tuple[float | None, float | None, str | None, str | None]:
    watts, limit, detail = _rapl_power_snapshot_detailed()
    if watts is not None:
        source = "btop sidecar" if detail.startswith("btop sidecar") else "RAPL"
        return watts, limit, source, detail
    fallback_watts, fallback_limit = _hwmon_power_snapshot()
    if fallback_watts is not None:
        return (fallback_watts,
                fallback_limit if fallback_limit is not None else limit,
                "hwmon",
                "CPU-specific hwmon fallback")
    return None, limit, None, detail


def _cpu_iowait_percent() -> float | None:
    return _cpu_iowait_sampled()


def system_resources() -> dict:
    vm = psutil.virtual_memory()
    total = int(vm.total)
    available = int(vm.available)
    used = max(0, total - available)
    power_thermal_disabled = os.environ.get("GSD_DISABLE_POWER_TELEMETRY", "").strip().lower() in {"1", "true", "yes", "on"}
    if power_thermal_disabled:
        power_watts = power_limit_watts = temperature_celsius = temperature_path = None
        power_source = temperature_source = "operator-disabled"
        power_detail = "GSD_DISABLE_POWER_TELEMETRY=1"
    else:
        power_watts, power_limit_watts, power_source, power_detail = _cpu_power_snapshot_detailed()
        temperature_celsius, temperature_source, temperature_path = _cpu_temperature_snapshot()
    disk_read_bps, disk_write_bps = _disk_io_rates()
    return {
        "cpu_percent": _cpu_percent_sampled(),
        "cpu_power_watts": None if power_watts is None else round(float(power_watts), 1),
        "cpu_power_limit_watts": None if power_limit_watts is None else round(float(power_limit_watts), 1),
        "cpu_power_source": power_source,
        "cpu_power_detail": power_detail,
        "cpu_temperature_celsius": None if temperature_celsius is None else round(float(temperature_celsius), 1),
        "cpu_temperature_source": temperature_source,
        "cpu_temperature_path": temperature_path,
        "cpu_power_sidecar": None if power_thermal_disabled else _btop_telemetry_status(),
        "memory_total_bytes": total,
        "memory_used_bytes": used,
        "memory_free_bytes": available,
        "memory_load_percent": round(100.0 * used / total, 1) if total else 0.0,
        "memory_bandwidth": MEMBW_MONITOR.snapshot(start=True, wait_seconds=0.0),
        "disk_read_bytes_per_second": None if disk_read_bps is None else round(float(disk_read_bps), 1),
        "disk_write_bytes_per_second": None if disk_write_bps is None else round(float(disk_write_bps), 1),
    }


_HOST_SNAPSHOT: dict = {"at": 0.0, "value": None}
_HOST_SNAPSHOT_LOCK = threading.Lock()
_HOST_SNAPSHOT_INTERVAL_SECONDS = max(
    0.1, float(os.environ.get("GSD_HOST_SNAPSHOT_INTERVAL_SECONDS", "4.0")))


def host_snapshot(now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    with _HOST_SNAPSHOT_LOCK:
        cached = _HOST_SNAPSHOT["value"]
        if cached is not None and now - _HOST_SNAPSHOT["at"] < _HOST_SNAPSHOT_INTERVAL_SECONDS:
            return cached
        try:
            value = system_resources()
        except Exception as exc:
            _note_swallowed("host_snapshot", exc)
            return cached if cached is not None else {}
        _HOST_SNAPSHOT.update(at=now, value=value)
        return value
