from __future__ import annotations

import threading
import time
import traceback

from graph_scale_dynamics.observability.console import error as console_error

INCIDENT_CONTRACT = "gsd-incident-record-1"

MAX_INCIDENTS = 32

REPEAT_LOG_SECONDS = 300.0

_lock = threading.Lock()
_incidents: dict[str, dict] = {}


def _origin(exc: BaseException) -> str | None:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1]}:{last.lineno} in {last.name}"


def record(service: str, where: str, exc: BaseException, *,
           detail: str | None = None) -> dict:
    key = f"{service}:{where}:{type(exc).__name__}:{exc}"
    now = time.time()
    text = f"{type(exc).__name__}: {exc}"
    origin = _origin(exc)
    with _lock:
        existing = _incidents.get(key)
        if existing is None:
            if len(_incidents) >= MAX_INCIDENTS:
                oldest = min(_incidents, key=lambda k: _incidents[k]["last_epoch"])
                _incidents.pop(oldest, None)
            existing = {
                "contract": INCIDENT_CONTRACT, "service": service, "where": where,
                "error": text, "origin": origin, "detail": detail,
                "traceback": "".join(traceback.format_exception(
                    type(exc), exc, exc.__traceback__))[-4000:],
                "count": 0, "first_epoch": now, "last_epoch": now,
                "_logged_epoch": 0.0,
            }
            _incidents[key] = existing
        existing["count"] += 1
        existing["last_epoch"] = now
        existing["detail"] = detail or existing.get("detail")
        should_log = (now - existing["_logged_epoch"]) >= REPEAT_LOG_SECONDS
        if should_log:
            existing["_logged_epoch"] = now
        count, tb = existing["count"], existing["traceback"]
    if should_log:
        suffix = f" at {origin}" if origin else ""
        repeat = f" (x{count})" if count > 1 else ""
        console_error(service, f"{where} failed{repeat}: {text}{suffix}")
        if count == 1:
            console_error(service, tb.rstrip())
    return existing


def recent(limit: int = 8) -> list[dict]:
    with _lock:
        rows = sorted(_incidents.values(), key=lambda f: f["last_epoch"], reverse=True)
        return [{k: v for k, v in row.items() if not k.startswith("_")}
                for row in rows[:limit]]


def clear(service: str | None = None, where: str | None = None) -> int:
    with _lock:
        drop = [k for k, f in _incidents.items()
                if (service is None or f["service"] == service)
                and (where is None or f["where"] == where)]
        for k in drop:
            _incidents.pop(k, None)
        return len(drop)
