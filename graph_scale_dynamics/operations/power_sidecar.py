from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.operations.process_ownership import folder_identity

CONTRACT = "gsd-power-sidecar-1"

FD_ENV = "GSD_BTOP_SIDECAR_FD"
META_ENV = "GSD_BTOP_SIDECAR"

PTY_ROWS, PTY_COLUMNS = 24, 100

RAPL_ENERGY = Path("/sys/class/powercap/intel-rapl:0/energy_uj")

WANTED_FLAGS = (
    ("--utf-force", "start even where the locale is not UTF-8"),
)

TTY_OFF_FLAGS = ("--tty_off", "+t")

SIDECAR_OVERRIDES = {
    "shown_boxes": '"cpu"',
    "update_ms": "500",
    "tty_mode": "False",
    "show_cpu_watts": "True",
    "check_temp": "True",
    "temp_scale": '"celsius"',
    "show_gpu_info": '"Off"',
    "show_uptime": "False",
    "show_battery": "False",
    "clock_format": '""',
    "terminal_sync": "False",
    "save_config_on_exit": "False",
    "log_level": '"ERROR"',
}

_CAPABILITY_NAMES = {
    0: "cap_chown", 1: "cap_dac_override", 2: "cap_dac_read_search", 3: "cap_fowner",
    6: "cap_setgid", 7: "cap_setuid", 12: "cap_net_admin", 17: "cap_sys_rawio",
    19: "cap_sys_ptrace", 21: "cap_sys_admin", 24: "cap_sys_resource", 38: "cap_perfmon",
}


def operator_config_path() -> Path | None:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    home = os.environ.get("HOME")
    if xdg:
        return Path(xdg) / "btop" / "btop.conf"
    if home:
        return Path(home) / ".config" / "btop" / "btop.conf"
    return None


def configured_cpu_sensor() -> tuple[str | None, str | None]:
    path = operator_config_path()
    if path is None:
        return None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, str(path)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "cpu_sensor":
            continue
        value = value.strip().strip('"').strip("'")
        if value and value.lower() != "auto":
            return value, str(path)
        return None, str(path)
    return None, str(path)


def sidecar_config() -> dict:
    configured, config_path = configured_cpu_sensor()
    source = operator_config_path()
    inherited: list[str] = []
    seeded_from = None
    error = None
    try:
        if source is not None and source.is_file():
            for raw in source.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key and key not in SIDECAR_OVERRIDES:
                    inherited.append(line)
            seeded_from = str(source)
    except OSError as exc:
        error = f"{exc.__class__.__name__}: {exc}"
    sensor = configured or "Auto"
    escaped = sensor.replace("\\", "\\\\").replace('"', '\\"')
    forced = dict(SIDECAR_OVERRIDES) | {"cpu_sensor": f'"{escaped}"'}
    lines = inherited + [f"{key} = {value}" for key, value in sorted(forced.items())] + [""]
    return {"text": "\n".join(lines), "config_path": config_path, "seeded_from": seeded_from,
            "inherited_keys": len(inherited), "error": error}


def supported_flags(path: str) -> tuple[frozenset[str], str | None]:
    try:
        done = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return frozenset(), f"{exc.__class__.__name__}: {exc}"
    text = (done.stdout or "") + (done.stderr or "")
    return frozenset(re.findall(r"(?<![\w+-])([-+]{1,2}[A-Za-z][\w-]*)", text)), None


def argv(path: str, update_ms: int = 500) -> tuple[list[str], list[str], str | None]:
    supported, error = supported_flags(path)
    command, dropped = [path], []
    tty_off = next((flag for flag in TTY_OFF_FLAGS if not supported or flag in supported), None)
    if tty_off:
        command.append(tty_off)
    else:
        dropped.extend(TTY_OFF_FLAGS)
    for flag, _why in WANTED_FLAGS:
        (command if (not supported or flag in supported) else dropped).append(flag)
    if not supported or "-u" in supported or "--update" in supported:
        command += ["-u", str(int(update_ms))]
    else:
        dropped.append("-u")
    return command, dropped, error


def file_capabilities(path: str | None) -> list[str]:
    if not path:
        return []
    try:
        blob = os.getxattr(path, "security.capability")
    except (OSError, AttributeError, ValueError):
        return []
    if len(blob) < 12:
        return []
    words = (len(blob) - 4) // 8
    names: list[str] = []
    for word in range(words):
        permitted, _inheritable = struct.unpack_from("<II", blob, 4 + word * 8)
        for bit in range(32):
            if permitted & (1 << bit):
                index = word * 32 + bit
                names.append(_CAPABILITY_NAMES.get(index, f"cap_{index}"))
    return names


def rapl_readable() -> bool | None:
    if not RAPL_ENERGY.exists():
        return None
    try:
        with open(RAPL_ENERGY, "rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def inside_scratch_namespace(root: Path | None) -> bool:
    if root is None:
        return False
    try:
        from graph_scale_dynamics.operations.scratch_namespace import mounted_here
        return bool(mounted_here(Path(root)))
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Handle:
    master_fd: int
    process: subprocess.Popen | None = None
    pid: int | None = None
    path: str | None = None
    command: list[str] = field(default_factory=list)
    dropped_flags: list[str] = field(default_factory=list)
    help_error: str | None = None
    temp_dir: str | None = None
    config_seeded_from: str | None = None
    config_inherited_keys: int = 0
    capabilities: list[str] = field(default_factory=list)
    exec_inside_scratch_namespace: bool = False
    rapl_readable: bool | None = None
    started_by: str = "api"

    def conditions(self) -> dict:
        return {
            "started_by": self.started_by,
            "exec_inside_scratch_namespace": self.exec_inside_scratch_namespace,
            "btop_capabilities": list(self.capabilities),
            "rapl_energy_path": str(RAPL_ENERGY),
            "rapl_readable_without_capability": self.rapl_readable,
            "config_seeded_from": self.config_seeded_from,
            "config_inherited_keys": self.config_inherited_keys,
            "argv": list(self.command),
        }

    def metadata(self) -> dict:
        return {"contract": CONTRACT, "pid": self.pid, "path": self.path} | self.conditions()


def why_no_watts(conditions: dict) -> str | None:  # noqa: C901
    withdrawn = conditions.get("watts_withdrawn")
    if withdrawn is not None:
        return (f"btop last drew a wattage {withdrawn:.0f}s ago and has drawn "
                f"{int(conditions.get('frames_without_watts') or 0)} frame(s) without one since. "
                "A reading that has not been redrawn is not the current power, so it is withheld "
                "rather than shown")
    if conditions.get("rapl_readable_without_capability") is None:
        return ("this host has no RAPL package energy counter at "
                f"{conditions.get('rapl_energy_path')}, so btop has no wattage to draw")
    if conditions.get("rapl_readable_without_capability"):
        return None
    capabilities = list(conditions.get("btop_capabilities") or [])
    if not capabilities:
        return ("this btop carries no file capabilities and the package energy counter is "
                "root-only, so it cannot read the power; setcap cap_dac_read_search,"
                "cap_perfmon=ep on the btop binary")
    if conditions.get("exec_inside_scratch_namespace"):
        return (f"btop was exec'd inside the folder's scratch user namespace. It still holds "
                f"{', '.join(capabilities)}, but that capability overrides permissions only on "
                "files whose owner and group are mapped in the namespace, and the package energy "
                "counter is root-only while the namespace maps one uid. Start the sidecar before "
                "the fleet enters the namespace")
    return None


def _die_with_parent() -> None:
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(1, int(signal.SIGKILL), 0, 0, 0)
    except Exception:  # noqa: BLE001
        pass


SIDECAR_TEMP_PREFIX = "gsd-btop-telemetry-"


def reap_orphaned_sidecars() -> list[int]:
    killed = []
    try:
        import psutil
    except ImportError:
        return killed
    for proc in psutil.process_iter(["pid", "name", "ppid"]):
        try:
            if proc.info.get("name") != "btop" or proc.info.get("ppid") != 1:
                continue
            home = str(proc.environ().get("XDG_CONFIG_HOME") or "")
            if SIDECAR_TEMP_PREFIX not in home:
                continue
            proc.kill()
            killed.append(int(proc.info["pid"]))
        except (psutil.Error, OSError):
            continue
    return killed


def start(root: Path | None = None, *, update_ms: int = 500, started_by: str = "api") -> Handle:
    path = shutil.which("btop")
    if not path:
        raise RuntimeError("btop not found in PATH")
    if not sys.platform.startswith("linux"):
        raise RuntimeError("btop telemetry backend is Linux-only")
    import fcntl
    import pty
    import termios

    config = sidecar_config()
    temp_dir = tempfile.mkdtemp(prefix=SIDECAR_TEMP_PREFIX)
    master_fd = None
    try:
        config_dir = Path(temp_dir) / "btop"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "btop.conf").write_text(config["text"], encoding="utf-8")
        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", PTY_ROWS, PTY_COLUMNS, 0, 0))
        environment = os.environ.copy()
        environment.setdefault("TERM", "xterm-256color")
        environment["XDG_CONFIG_HOME"] = temp_dir
        environment.pop(FD_ENV, None)
        environment.pop(META_ENV, None)
        command, dropped, help_error = argv(path, update_ms)
        namespaced = inside_scratch_namespace(root)
        try:
            process = subprocess.Popen(
                command, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                env=environment, close_fds=True,
                start_new_session=False,
                preexec_fn=_die_with_parent if started_by == "publisher" else None,
            )
        finally:
            os.close(slave_fd)
    except BaseException:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return Handle(
        master_fd=master_fd, process=process, pid=process.pid, path=path, command=command,
        dropped_flags=list(dropped), help_error=help_error, temp_dir=temp_dir,
        config_seeded_from=config["seeded_from"], config_inherited_keys=config["inherited_keys"],
        capabilities=file_capabilities(path), exec_inside_scratch_namespace=namespaced,
        rapl_readable=rapl_readable(), started_by=started_by,
    )


def stop(handle: Handle | None) -> None:
    if handle is None:
        return
    if handle.master_fd is not None:
        try:
            os.close(handle.master_fd)
        except OSError:
            pass
        handle.master_fd = None  # type: ignore[assignment]
    process = handle.process
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
                process.wait(timeout=1.5)
            except (OSError, subprocess.SubprocessError):
                pass
    if handle.temp_dir:
        shutil.rmtree(handle.temp_dir, ignore_errors=True)
        handle.temp_dir = None


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-2A-Z])")
CPU_LINE_RE = re.compile(r"CPU\s.{0,400}?(?P<load>\d{1,3})%", re.DOTALL)
TEMP_RE = re.compile(r"(?<![\d.])(?P<temp>-?\d{1,3})\s*\u00b0?\s?C(?![a-zA-Z])")
WATTS_RE = re.compile(r"(?<![\d.])(?P<watts>\d+(?:\.\d+)?)\s*W(?![a-zA-Z])")


def parse_telemetry(raw: bytes | str) -> tuple[float | None, float | None]:
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
    plain = ANSI_RE.sub("", text).replace("\r", " ").replace("\n", " ")
    matches = list(CPU_LINE_RE.finditer(plain))
    if not matches:
        return None, None
    tail = plain[matches[-1].end():matches[-1].end() + 240]
    temp = watts = None
    found = TEMP_RE.search(tail)
    if found:
        try:
            value = float(found.group("temp"))
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value) and -20 <= value <= 150:
            temp = value
    found = WATTS_RE.search(tail)
    if found:
        try:
            value = float(found.group("watts"))
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value) and 0 < value <= 5000:
            watts = value
    return temp, watts


READING_MAX_AGE_SECONDS = 10.0
READING_FILE = ("var", "run", "cpu-power.json")
PIDFILE = ("var", "run", "cpu-power-publisher.json")
RESTART_BACKOFF_SECONDS = 30.0
RESTART_AT_ONCE_AFTER_FRAMES = 1
PUBLISH_INTERVAL_SECONDS = ticks(1)
READY_TIMEOUT_SECONDS = 10.0


def reading_path(root: Path) -> Path:
    return Path(root).resolve().joinpath(*READING_FILE)


def _pidfile(root: Path) -> Path:
    return Path(root).resolve().joinpath(*PIDFILE)


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def publisher_pid(root: Path) -> int | None:
    try:
        record = json.loads(_pidfile(root).read_text())
        pid = int(record["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if record.get("boot_id") != _boot_id():
        return None
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    if __name__.encode() not in command or str(Path(root).resolve()).encode() not in command:
        return None
    return pid


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    partial.replace(path)


def _publish(root: Path) -> int:
    import select
    import signal as signal_module

    from graph_scale_dynamics.operations.process_ownership import die_with_owner

    root = Path(root).resolve()
    die_with_owner()
    identity = folder_identity(root)
    if identity is None:
        return 0
    (root / "var").mkdir(exist_ok=True)
    reap_orphaned_sidecars()
    stopping: list[bool] = []
    for signum in (signal_module.SIGTERM, signal_module.SIGINT, signal_module.SIGHUP):
        signal_module.signal(signum, lambda *_: stopping.append(True))
    _write_atomic(_pidfile(root), {"contract": CONTRACT, "pid": os.getpid(), "root": str(root),
                                   "boot_id": _boot_id(),
                                   "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    handle: Handle | None = None
    error: str | None = None
    retry_at = 0.0
    frames_this_run = 0
    restarts = 0
    rolling = b""
    watts = temperature = None
    watts_at = temperature_at = frame_at = None
    frames_without_watts = 0
    cpu_line_without_watts = None
    published_at = 0.0
    try:
        while not stopping:
            if folder_identity(root) != identity:
                break
            if handle is None and time.monotonic() >= retry_at:
                try:
                    handle = start(root, started_by="publisher")
                    error, rolling, frames_this_run = None, b"", 0
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    handle, error = None, f"{type(exc).__name__}: {exc}"
                    retry_at = time.monotonic() + RESTART_BACKOFF_SECONDS
            if handle is not None:
                if handle.process is not None and handle.process.poll() is not None:
                    drew = frames_this_run >= RESTART_AT_ONCE_AFTER_FRAMES
                    restarts += 1
                    error = (f"btop stopped (exit {handle.process.returncode}) after "
                             f"{frames_this_run} frame(s); restart {restarts}")
                    stop(handle)
                    handle = None
                    retry_at = time.monotonic() + (0.0 if drew else RESTART_BACKOFF_SECONDS)
                else:
                    try:
                        ready, _, _ = select.select([handle.master_fd], [], [], 0.5)
                        chunk = os.read(handle.master_fd, 65536) if ready else b""
                    except (OSError, ValueError) as exc:
                        error = f"btop PTY read failed: {type(exc).__name__}: {exc}"
                        stop(handle)
                        restarts += 1
                        handle = None
                        retry_at = time.monotonic() + (
                            0.0 if frames_this_run >= RESTART_AT_ONCE_AFTER_FRAMES
                            else RESTART_BACKOFF_SECONDS)
                        chunk = b""
                    if chunk:
                        rolling = (rolling + chunk)[-131072:]
                        temperature_now, watts_now = parse_telemetry(rolling)
                        now = time.time()
                        plain = ANSI_RE.sub("", rolling.decode("utf-8", "ignore")).replace("\n", " ")
                        drawn = CPU_LINE_RE.search(plain)
                        if drawn:
                            frame_at = now
                            frames_this_run += 1
                        if temperature_now is not None:
                            temperature, temperature_at = temperature_now, now
                        if watts_now is not None:
                            watts, watts_at = watts_now, now
                            frames_without_watts, cpu_line_without_watts = 0, None
                        elif drawn:
                            frames_without_watts += 1
                            cpu_line_without_watts = drawn.group(0)[-400:]
            else:
                time.sleep(0.25)
            if time.monotonic() - published_at >= PUBLISH_INTERVAL_SECONDS:
                published_at = time.monotonic()
                conditions = handle.conditions() if handle is not None else {
                    "started_by": "publisher", "exec_inside_scratch_namespace": None,
                    "btop_capabilities": file_capabilities(shutil.which("btop")),
                    "rapl_energy_path": str(RAPL_ENERGY),
                    "rapl_readable_without_capability": rapl_readable(),
                    "config_seeded_from": None, "config_inherited_keys": 0, "argv": [],
                }
                try:
                    _write_atomic(reading_path(root), {
                        "contract": CONTRACT, "wrote_at": time.time(), "pid": os.getpid(),
                        "btop_pid": None if handle is None else handle.pid,
                        "btop_path": None if handle is None else handle.path,
                        "running": handle is not None,
                        "watts": watts, "watts_at": watts_at,
                        "temperature_celsius": temperature, "temperature_at": temperature_at,
                        "frame_at": frame_at, "frames_without_watts": frames_without_watts,
                        "cpu_line_without_watts": cpu_line_without_watts,
                        "restarts": restarts,
                        "last_error": error, "flags_dropped": [] if handle is None else list(handle.dropped_flags),
                        "help_error": None if handle is None else handle.help_error,
                    } | conditions)
                except FileNotFoundError:
                    break
    finally:
        stop(handle)
        if folder_identity(root) == identity:
            for path in (reading_path(root), _pidfile(root)):
                try:
                    path.unlink()
                except OSError:
                    pass
    return 0


def ensure_publisher(root: Path, *, log=print) -> int | None:
    root = Path(root).resolve()
    pid = publisher_pid(root)
    if pid is not None:
        log(f"cpu power: publisher already running (pid {pid})", flush=True)
        return pid
    if not shutil.which("btop"):
        log("cpu power: btop is not in PATH, so the CPU tile will show a dash", flush=True)
        return None
    logfile = root / "var" / "log" / "cpu-power.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(logfile, "ab") as out:
            from graph_scale_dynamics.operations.process_ownership import owned_env, popen_owned
            process = popen_owned(
                [sys.executable, "-m", __name__, "publish", str(root)], cwd=str(root),
                stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True,
                close_fds=True, env=owned_env(dict(os.environ, PYTHONPATH=str(root))))
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"cpu power: the publisher did not start ({type(exc).__name__}: {exc})", flush=True)
        return None
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        pid = publisher_pid(root)
        if pid == process.pid and reading_path(root).exists():
            log(f"cpu power: {describe_reading(read_published(root))}", flush=True)
            return pid
        if process.poll() is not None:
            break
        time.sleep(0.05)
    tail = logfile.read_text(errors="replace")[-400:] if logfile.exists() else ""
    log(f"cpu power: the publisher did not come up (exit {process.poll()}): {tail.strip()}", flush=True)
    return None


def stop_publisher(root: Path, *, started: int | None | bool = True) -> bool:
    pid = publisher_pid(root)
    if pid is None or started is None or (started is not True and int(started) != pid):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def read_published(root: Path, *, max_age: float = READING_MAX_AGE_SECONDS) -> dict:
    path = reading_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"published": False, "reason": f"no published reading at {path}"}
    if not isinstance(payload, dict) or payload.get("contract") != CONTRACT:
        return {"published": False, "reason": f"{path} is not a {CONTRACT} reading"}
    now = time.time()
    out = dict(payload)
    out["published"] = True
    out["published_age_seconds"] = max(0.0, now - float(payload.get("wrote_at") or 0.0))
    for name, stamp in (("watts", "watts_at"), ("temperature_celsius", "temperature_at")):
        at = payload.get(stamp)
        age = None if at is None else max(0.0, now - float(at))
        out[f"{name}_age_seconds"] = age
        if out.get(name) is not None and (age is None or age > max_age):
            out[f"{name}_withdrawn"] = round(age, 1) if age is not None else None
            out[name] = None
    frame_at = payload.get("frame_at")
    out["frame_age_seconds"] = None if frame_at is None else max(0.0, now - float(frame_at))
    if out["published_age_seconds"] > max(max_age, PUBLISH_INTERVAL_SECONDS * 5):
        out["stale"] = True
        out["watts"] = out["temperature_celsius"] = None
    return out


def describe_reading(reading: dict) -> str:
    if not reading.get("published"):
        return f"no CPU power sidecar ({reading.get('reason') or 'not started'}); the tile will show a dash"
    where = ("inside the scratch namespace, where a capability does not reach a root-owned file"
             if reading.get("exec_inside_scratch_namespace") else
             "outside the scratch namespace, under the host's own uid mapping")
    capabilities = ", ".join(reading.get("btop_capabilities") or []) or "none"
    line = f"btop pid={reading.get('btop_pid')} started {where}; capabilities {capabilities}"
    if reading.get("watts") is not None:
        return f"{line}; drawing {reading['watts']} W"
    reason = why_no_watts(reading)
    return f"{line}; {reason}" if reason else line


def describe(handle: Handle | None, error: str | None = None) -> str:
    if handle is None:
        return f"no CPU power sidecar ({error or 'not started'}); the dashboard's CPU tile will show a dash"
    conditions = handle.conditions()
    capabilities = ", ".join(conditions["btop_capabilities"]) or "none"
    where = ("inside the scratch namespace, where a capability does not reach a root-owned file"
             if conditions["exec_inside_scratch_namespace"] else
             "outside the scratch namespace, under the host's own uid mapping")
    reason = why_no_watts(conditions)
    line = f"btop pid={handle.pid} started {where}; capabilities {capabilities}"
    return f"{line}; {reason}" if reason else line


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "publish":
        raise SystemExit(_publish(Path(sys.argv[2])))
    print("usage: python -m graph_scale_dynamics.operations.power_sidecar publish <folder>",
          file=sys.stderr)
    raise SystemExit(2)
