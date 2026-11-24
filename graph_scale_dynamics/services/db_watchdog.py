from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from graph_scale_dynamics.operations import server_lock

LOGS_COMMAND = "python3 tools/postgres_instance.py logs"


def probe(socket_dir: Path, lock_path: Path, connect) -> dict:
    socket_path = Path(socket_dir) / ".s.PGSQL.5432"
    running = server_lock.held(lock_path)
    record = server_lock.read_record(lock_path) if running is not None else {}
    ok, error = True, None
    try:
        connect()
    except Exception as exc:
        ok, error = False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
    return {"socket_present": socket_path.exists(), "server_pid": record.get("pid"), "server_running": running,
            "server_log": record.get("log"), "connect_ok": ok, "error": error}


def _server_words(facts: dict) -> str:
    running = facts.get("server_running")
    state = "running" if running else "STOPPED" if running is False else "never started under a server lock"
    log = facts.get("server_log")
    return (f"server {state} (supervisor pid {facts.get('server_pid') or '-'}): {facts.get('error')}. If it died, "
            "check `dmesg -T | grep -i killed` for the OOM killer and the PostgreSQL log"
            + (f" at {log}" if log else "") + f" (`{LOGS_COMMAND}`)")


class Watchdog:
    def __init__(self, *, socket_dir: Path, postgres_dir: Path, connect, helper: Path | None,
                 owns_instance: bool, log=print, emit=None, interval: float = 15.0,
                 restart_interval: float = 60.0, max_restarts: int = 3):
        self.socket_dir = Path(socket_dir)
        self.lock_path = Path(postgres_dir) / server_lock.LOCK_NAME
        self.connect = connect
        self.helper = Path(helper) if helper else None
        self.owns_instance = owns_instance
        self.log = log
        self.emit = emit
        self.interval = interval
        self.restart_interval = restart_interval
        self.max_restarts = max_restarts
        self.next_check = 0.0
        self.failing_since: float | None = None
        self.restarts = 0
        self.last_restart = float("-inf")

    def tick(self, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        if now < self.next_check:
            return "ok" if self.failing_since is None else "degraded"
        self.next_check = now + self.interval
        facts = probe(self.socket_dir, self.lock_path, self.connect)
        if facts["connect_ok"]:
            if self.failing_since is not None:
                self.log(f"database watchdog: PostgreSQL reachable again after "
                         f"{now - self.failing_since:.0f}s ({self.restarts} restart(s))")
                if self.emit:
                    try:
                        self.emit("database_recovered", {"restarts": self.restarts})
                    except Exception as exc:  # noqa: BLE001
                        self.log(f"database watchdog: recovery not recorded ({type(exc).__name__}: {exc})")
                self.failing_since = None
                self.restarts = 0
                return "recovered"
            return "ok"
        if self.failing_since is None:
            self.failing_since = now
            self.log("database watchdog: ALARM PostgreSQL unreachable -- socket "
                     f"{'present' if facts['socket_present'] else 'MISSING'}, " + _server_words(facts))
            if self.emit:
                try:
                    self.emit("database_unreachable", facts)
                except Exception:
                    pass
        if not self.owns_instance or self.helper is None:
            self.log("database watchdog: this supervisor does not own the database instance; "
                     "draining the fleet")
            return "drain"
        if self.restarts >= self.max_restarts:
            self.log(f"database watchdog: {self.restarts} restart attempts failed; draining the "
                     "fleet rather than running blind (durable state is preserved)")
            return "drain"
        if now - self.last_restart >= self.restart_interval:
            self.restarts += 1
            self.last_restart = now
            self.log(f"database watchdog: restart attempt {self.restarts}/{self.max_restarts} via "
                     f"{self.helper.name} ensure")
            try:
                subprocess.run([sys.executable, str(self.helper), "ensure"], check=False,
                               timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                self.log(f"database watchdog: restart attempt failed to launch: {exc}")
        return "degraded"
