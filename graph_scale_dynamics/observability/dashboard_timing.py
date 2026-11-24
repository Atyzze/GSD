from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics import PROJECT_ROOT

SLOW_SECONDS = 1.0
LOG_NAME = "dashboard_slow.jsonl"
MAX_BYTES = 2 * 1024 * 1024

_LOCK = threading.Lock()


def log_path(root: Path | None = None) -> Path:
    return Path(root or PROJECT_ROOT) / "var" / "log" / LOG_NAME


def proxy_timeout_seconds() -> float:
    try:
        return max(0.25, float(os.environ.get("GSD_WEB_API_TIMEOUT_SECONDS", "1.5")))
    except ValueError:
        return 1.5


class RequestClock:
    def __init__(self, route: str):
        self.route = route
        self.started = time.monotonic()
        self.last = self.started
        self.phases: dict[str, float] = {}

    def mark(self, phase: str) -> None:
        now = time.monotonic()
        self.phases[phase] = round(now - self.last, 4)
        self.last = now

    def finish(self, outcome: str = "ok", *, root: Path | None = None, **extra) -> dict | None:
        total = time.monotonic() - self.started
        self.phases.setdefault("handler", round(time.monotonic() - self.last, 4))
        if total < SLOW_SECONDS:
            return None
        row = {"utc": utc_now(), "route": self.route, "outcome": outcome,
               "total_seconds": round(total, 4), "phases": self.phases,
               "proxy_gave_up": total >= proxy_timeout_seconds(), **extra}
        record(row, root=root)
        return row


def record(row: dict, *, root: Path | None = None) -> None:
    path = log_path(root)
    line = json.dumps(row, sort_keys=True, default=str) + "\n"
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_BYTES:
                path.replace(path.with_suffix(path.suffix + ".1"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


def recent(limit: int = 50, *, root: Path | None = None) -> list[dict]:
    path = log_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-int(limit):]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
