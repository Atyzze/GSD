from __future__ import annotations

import ctypes
import os
import signal
import queue
import subprocess
import sys
import threading
import time

OWNER_PID_ENV = "GSD_OWNER_PID"

PR_SET_PDEATHSIG = 1


def owned_env(env: dict[str, str] | None = None) -> dict[str, str]:
    out = dict(os.environ if env is None else env)
    out[OWNER_PID_ENV] = str(os.getpid())
    return out


_SPAWNER: dict[str, object] = {"queue": None}
_SPAWNER_LOCK = threading.Lock()


def _spawner_queue() -> queue.Queue:
    with _SPAWNER_LOCK:
        if _SPAWNER["queue"] is None:
            jobs: queue.Queue = queue.Queue()

            def run() -> None:
                while True:
                    args, kwargs, out, done = jobs.get()
                    try:
                        out["process"] = subprocess.Popen(*args, **kwargs)
                    except BaseException as exc:  # noqa: BLE001
                        out["error"] = exc
                    finally:
                        done.set()

            threading.Thread(target=run, name="gsd-owned-spawner", daemon=True).start()
            _SPAWNER["queue"] = jobs
        return _SPAWNER["queue"]  # type: ignore[return-value]


def popen_owned(*args, **kwargs) -> subprocess.Popen:
    if threading.current_thread() is threading.main_thread():
        return subprocess.Popen(*args, **kwargs)
    out: dict = {}
    done = threading.Event()
    _spawner_queue().put((args, kwargs, out, done))
    done.wait()
    if "error" in out:
        raise out["error"]
    return out["process"]


def _set_parent_death_signal(sig: int) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_PDEATHSIG, int(sig), 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def die_with_owner(sig: int = signal.SIGTERM) -> str:
    named = os.environ.pop(OWNER_PID_ENV, None)
    if not named:
        return "unowned"
    try:
        owner = int(named)
    except ValueError:
        return "unowned"
    if not _set_parent_death_signal(sig):
        return "unsupported"
    if os.getppid() != owner:
        os.kill(os.getpid(), sig)
        return "orphaned"
    return "armed"


def folder_identity(root) -> tuple[int, int] | None:
    try:
        status = os.stat(root)
    except OSError:
        return None
    return (status.st_dev, status.st_ino)


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


class interrupt_on:
    def __init__(self, signals=STOP_SIGNALS):
        self.signals = tuple(signals)
        self.previous: dict = {}

    def __enter__(self):
        def _raise(signum, _frame):
            raise KeyboardInterrupt(f"stopped by signal {signum}")
        for sig in self.signals:
            try:
                self.previous[sig] = signal.signal(sig, _raise)
            except (ValueError, OSError):
                pass
        return self

    def __exit__(self, *_exc):
        for sig, handler in self.previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        return False


def stop_process_group(child: subprocess.Popen, *, grace: float = 30.0, log=None) -> int | None:
    step = max(0.5, float(grace) / 2)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + (step if sig != signal.SIGKILL else 5.0)
        while time.monotonic() < deadline and _group_alive(child.pid):
            child.poll()
            time.sleep(0.1)
        if not _group_alive(child.pid):
            break
        if log is not None:
            log(f"process group {child.pid} still running after {signal.Signals(sig).name}")
    try:
        return child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return None


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
