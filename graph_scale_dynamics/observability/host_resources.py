from __future__ import annotations

import atexit
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

from graph_scale_dynamics.observability.membw_dashboard import MONITOR as MEMBW_MONITOR

_RAPL_STATE: dict[str, tuple[float, float]] = {}
_BTOP_LOCK = threading.RLock()
_BTOP_PROCESS: subprocess.Popen | None = None
_BTOP_MASTER_FD: int | None = None
_BTOP_THREAD: threading.Thread | None = None
_BTOP_TEMP_DIR: str | None = None
_BTOP_STATE: dict[str, object] = {
    "watts": None, "temperature_celsius": None, "last_seen": 0.0,
    "error": None, "retry_after": 0.0,
}
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-2A-Z])")
_CPU_LINE = re.compile(
    r"CPU\s.{0,320}?(?P<load>\d{1,3})%.{0,160}?(?P<temp>-?\d{1,3})\s*°?C"
    r"(?:.{0,120}?(?P<watts>\d+(?:\.\d+)?)\s*W)?", re.DOTALL,
)


def _read_number(path: Path) -> float | None:
    try:
        value = float(path.read_text(encoding="utf-8").strip())
        return value if math.isfinite(value) else None
    except (OSError, ValueError):
        return None


def _powercap_zones(root: Path = Path("/sys/class/powercap")) -> list[Path]:
    try:
        roots = list(root.iterdir())
    except OSError:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for entry in roots:
        candidates = [entry]
        try:
            if entry.is_dir():
                candidates.extend(list(entry.iterdir()))
        except OSError:
            pass
        for zone in candidates:
            if not (zone / "energy_uj").is_file():
                continue
            try:
                key = str(zone.resolve())
            except OSError:
                key = str(zone)
            if key not in seen:
                seen.add(key)
                found.append(zone)
    return found


def _rapl_snapshot() -> tuple[float | None, float | None, str | None]:
    zones = _powercap_zones()
    exact = Path("/sys/class/powercap/intel-rapl:0")
    ordered = ([exact] if exact in zones else []) + [z for z in zones if z != exact]
    top_level = [zone for zone in ordered
                 if zone.name.startswith("intel-rapl:") and zone.name.count(":") == 1]
    if top_level:
        package = top_level
    else:
        named: list[Path] = []
        for zone in ordered:
            name = ""
            try:
                name = (zone / "name").read_text(encoding="utf-8").strip().lower()
            except OSError:
                pass
            if any(token in name for token in ("package", "socket", "pkg")):
                named.append(zone)
        package = named or ordered[:1]
    if not package:
        return None, None, None

    now = time.monotonic()
    watts_total = 0.0
    sampled = 0
    limits: list[float] = []
    used: list[str] = []
    for zone in package:
        energy = _read_number(zone / "energy_uj")
        if energy is None:
            continue
        key = str(zone)
        previous = _RAPL_STATE.get(key)
        _RAPL_STATE[key] = (energy, now)
        max_range = _read_number(zone / "max_energy_range_uj")
        if previous is not None:
            prev_energy, prev_time = previous
            elapsed = now - prev_time
            delta = energy - prev_energy
            if delta < 0 and max_range and max_range > 0:
                delta += max_range
            if elapsed > 0 and delta >= 0:
                watts = (delta / 1_000_000.0) / elapsed
                if math.isfinite(watts) and 0 <= watts <= 5000:
                    watts_total += watts
                    sampled += 1
        limit = _read_number(zone / "constraint_0_power_limit_uw")
        if limit and limit > 0:
            limits.append(limit / 1_000_000.0)
        used.append(str(zone / "energy_uj"))
    return (watts_total if sampled else None,
            max(limits) if limits else None,
            ", ".join(used) if used else None)


def _hwmon_power_snapshot(root: Path = Path("/sys/class/hwmon")) -> tuple[float | None, float | None, str | None]:
    try:
        devices = list(root.glob("hwmon*"))
    except OSError:
        return None, None, None
    candidates: list[tuple[int, float, float | None, str]] = []
    cpu_names = ("zenpower", "fam15h_power", "amd_energy", "cpu", "rapl")
    gpu_names = ("amdgpu", "nouveau", "nvidia", "xe", "i915")
    for device in devices:
        try:
            name = (device / "name").read_text(encoding="utf-8").strip().lower()
        except OSError:
            name = ""
        if any(token in name for token in gpu_names):
            continue
        explicit_cpu_driver = any(token in name for token in cpu_names)
        for sensor in list(device.glob("power*_average")) + list(device.glob("power*_input")):
            stem = sensor.name.rsplit("_", 1)[0]
            try:
                label = (device / f"{stem}_label").read_text(encoding="utf-8").strip().lower()
            except OSError:
                label = ""
            cpuish = explicit_cpu_driver or any(
                token in label for token in ("cpu package", "package power", "cpu power", "socket power"))
            if not cpuish:
                continue
            microwatts = _read_number(sensor)
            if microwatts is None or microwatts <= 0:
                continue
            watts = microwatts / 1_000_000.0
            if not math.isfinite(watts) or watts > 5000:
                continue
            priority = 20 if sensor.name.endswith("_average") else 10
            if any(token in label for token in ("package", "cpu", "socket")):
                priority += 20
            if any(token in name for token in ("zenpower", "fam15h_power", "amd_energy", "rapl")):
                priority += 10
            cap = _read_number(device / f"{stem}_cap")
            candidates.append((priority, watts, None if cap is None or cap <= 0 else cap / 1_000_000.0, str(sensor)))
    if not candidates:
        return None, None, None
    _, watts, cap, path = max(candidates, key=lambda item: item[0])
    return watts, cap, path


hwmon_power_snapshot = _hwmon_power_snapshot


def _parse_btop(raw: bytes | str) -> tuple[float | None, float | None]:
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
    plain = _ANSI.sub("", text).replace("\r", " ").replace("\n", " ")
    matches = list(_CPU_LINE.finditer(plain))
    if not matches:
        return None, None
    match = matches[-1]
    try:
        temp = float(match.group("temp"))
        raw_watts = match.group("watts")
        watts = None if raw_watts is None else float(raw_watts)
    except (TypeError, ValueError):
        return None, None
    if not (-20 <= temp <= 150 and math.isfinite(temp)):
        temp = None
    if watts is not None and not (0 <= watts <= 5000 and math.isfinite(watts)):
        watts = None
    return temp, watts


def _reader(process: subprocess.Popen, master_fd: int) -> None:
    import select
    rolling = b""
    while process.poll() is None:
        try:
            ready, _, _ = select.select([master_fd], [], [], 1.0)
            if not ready:
                continue
            chunk = os.read(master_fd, 65536)
            if not chunk:
                break
        except (OSError, ValueError):
            break
        rolling = (rolling + chunk)[-131072:]
        temp, watts = _parse_btop(rolling)
        if temp is None and watts is None:
            continue
        with _BTOP_LOCK:
            if temp is not None:
                _BTOP_STATE["temperature_celsius"] = temp
            if watts is not None:
                _BTOP_STATE["watts"] = watts
            _BTOP_STATE["last_seen"] = time.monotonic()
            _BTOP_STATE["error"] = None
    with _BTOP_LOCK:
        _BTOP_STATE["retry_after"] = time.monotonic() + 30.0


def stop_btop_sidecar() -> None:
    global _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_THREAD, _BTOP_TEMP_DIR
    with _BTOP_LOCK:
        process, fd, thread, temp_dir = _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_THREAD, _BTOP_TEMP_DIR
        _BTOP_PROCESS = None
        _BTOP_MASTER_FD = None
        _BTOP_THREAD = None
        _BTOP_TEMP_DIR = None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    if process is not None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except OSError:
            pass
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=1)
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


atexit.register(stop_btop_sidecar)


def _start_btop() -> bool:
    global _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_THREAD, _BTOP_TEMP_DIR
    with _BTOP_LOCK:
        if _BTOP_PROCESS is not None and _BTOP_PROCESS.poll() is None:
            return True
        if time.monotonic() < float(_BTOP_STATE.get("retry_after") or 0.0):
            return False
        path = shutil.which("btop")
        if not path or not sys.platform.startswith("linux"):
            _BTOP_STATE["retry_after"] = time.monotonic() + 30.0
            return False
        try:
            import fcntl
            import pty
            import struct
            import termios
            temp_dir = tempfile.mkdtemp(prefix="gsd-resource-btop-")
            config = Path(temp_dir) / "btop.conf"
            config.write_text("\n".join([
                'shown_boxes = "cpu"', 'update_ms = 500', 'show_cpu_watts = True',
                'check_temp = True', 'cpu_sensor = "Auto"', 'show_coretemp = False',
                'temp_scale = "celsius"', 'show_gpu_info = "Off"',
                'cpu_single_graph = True', 'show_uptime = False',
                'show_cpu_freq = False', 'show_battery = False', 'clock_format = ""',
                'terminal_sync = False', 'save_config_on_exit = False',
                'log_level = "ERROR"', '',
            ]), encoding="utf-8")
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            process = subprocess.Popen(
                [path, "--tty", "--force-utf", "--config", str(config), "--update", "500"],
                stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
                start_new_session=False,
            )
            os.close(slave)
        except (OSError, subprocess.SubprocessError):
            if "master" in locals():
                try:
                    os.close(master)
                except OSError:
                    pass
            if "temp_dir" in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)
            _BTOP_STATE["retry_after"] = time.monotonic() + 30.0
            return False
        _BTOP_PROCESS, _BTOP_MASTER_FD, _BTOP_TEMP_DIR = process, master, temp_dir
        thread = threading.Thread(target=_reader, args=(process, master),
                                  name="gsd-resource-btop", daemon=True)
        _BTOP_THREAD = thread
        thread.start()
        return True


def _btop_snapshot(wait_seconds: float = 0.0) -> tuple[float | None, float | None, str | None]:
    _start_btop()
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        with _BTOP_LOCK:
            age = time.monotonic() - float(_BTOP_STATE.get("last_seen") or 0.0)
            watts = _BTOP_STATE.get("watts")
            temp = _BTOP_STATE.get("temperature_celsius")
            if age <= 5.0 and (watts is not None or temp is not None):
                return (None if watts is None else float(watts),
                        None if temp is None else float(temp), "btop sidecar")
        if time.monotonic() >= deadline:
            return None, None, None
        time.sleep(0.05)


def _temperature_snapshot() -> tuple[float | None, str | None]:
    try:
        getter = getattr(psutil, "sensors_temperatures", None)
        if getter:
            groups = getter(fahrenheit=False) or {}
            preferred = []
            for name, entries in groups.items():
                lname = name.lower()
                priority = 2 if any(k in lname for k in ("k10temp", "coretemp", "zenpower", "cpu")) else 1
                for entry in entries:
                    value = getattr(entry, "current", None)
                    label = str(getattr(entry, "label", "") or "")
                    if value is not None and math.isfinite(float(value)) and -20 <= float(value) <= 150:
                        preferred.append((priority + (1 if "package" in label.lower() or "tdie" in label.lower() else 0), float(value), f"psutil:{name}:{label}"))
            if preferred:
                _, value, source = max(preferred, key=lambda row: row[0])
                return value, source
    except (psutil.Error, OSError, TypeError, ValueError):
        pass
    return None, None


_CPU_SAMPLE: dict = {"at": 0.0, "value": None, "armed": False, "times": None, "iowait": None}
_CPU_MIN_INTERVAL_SECONDS = 1.0
_CPU_LOCK = threading.Lock()


def _cpu_totals(times) -> tuple[float, float, float]:
    fields = times._asdict() if hasattr(times, "_asdict") else dict(times)
    total = sum(float(v) for v in fields.values()) - float(fields.get("guest", 0.0)) - float(fields.get("guest_nice", 0.0))
    iowait = float(fields.get("iowait", 0.0))
    return total - float(fields.get("idle", 0.0)) - iowait, total, iowait


def cpu_percent_sampled(now: float | None = None) -> float | None:
    now = time.monotonic() if now is None else now
    with _CPU_LOCK:
        if _CPU_SAMPLE["armed"] and now - _CPU_SAMPLE["at"] < _CPU_MIN_INTERVAL_SECONDS:
            return _CPU_SAMPLE["value"]
        try:
            busy, total, iowait = _cpu_totals(psutil.cpu_times())
        except Exception:
            return _CPU_SAMPLE["value"]
        previous = _CPU_SAMPLE["times"]
        _CPU_SAMPLE.update(at=now, armed=True, times=(busy, total, iowait))
        if previous is None or total <= previous[1]:
            return _CPU_SAMPLE["value"]
        span = total - previous[1]
        _CPU_SAMPLE.update(value=round(max(0.0, min(100.0, 100.0 * (busy - previous[0]) / span)), 1),
                           iowait=round(max(0.0, min(100.0, 100.0 * (iowait - previous[2]) / span)), 2))
        return _CPU_SAMPLE["value"]


def cpu_iowait_sampled() -> float | None:
    cpu_percent_sampled()
    return _CPU_SAMPLE["iowait"]


def system_resources() -> dict:
    vm = psutil.virtual_memory()
    total = int(vm.total)
    available = int(vm.available)
    used = max(0, total - available)
    power_thermal_disabled = os.environ.get("GSD_DISABLE_POWER_TELEMETRY", "").strip().lower() in {"1", "true", "yes", "on"}
    watts = limit = detail = source = None
    temp = temp_source = None
    if not power_thermal_disabled:
        watts, limit, detail = _rapl_snapshot()
        source = "RAPL" if watts is not None else None
        if watts is None:
            watts, hw_limit, detail = _hwmon_power_snapshot()
            if watts is not None:
                limit = hw_limit if hw_limit is not None else limit
                source = "hwmon"
        btop_temp = None
        if watts is None:
            watts, btop_temp, btop_detail = _btop_snapshot(wait_seconds=1.25)
            if watts is not None:
                source, detail = "btop sidecar", btop_detail
        temp, temp_source = _temperature_snapshot()
        if temp is None and btop_temp is not None:
            temp, temp_source = btop_temp, "btop sidecar"
    else:
        source = "operator-disabled"
        detail = "GSD_DISABLE_POWER_TELEMETRY=1"
        temp_source = "operator-disabled"
    return {
        "cpu_percent": cpu_percent_sampled(),
        "cpu_power_watts": None if watts is None else round(float(watts), 3),
        "cpu_power_limit_watts": None if limit is None else round(float(limit), 3),
        "cpu_power_source": source,
        "cpu_power_detail": detail,
        "cpu_temperature_celsius": None if temp is None else round(float(temp), 2),
        "cpu_temperature_source": temp_source,
        "memory_total_bytes": total,
        "memory_used_bytes": used,
        "memory_free_bytes": available,
        "memory_load_percent": round(100.0 * used / total, 1) if total else 0.0,
        "memory_bandwidth": MEMBW_MONITOR.snapshot(start=True, wait_seconds=0.0),
    }
