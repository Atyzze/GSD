from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from graph_scale_dynamics.observability import evidence_sources

TRACEBACK_MARK = "Traceback (most recent call last)"
LINE_CHARS = 300
HELD_BACK = frozenset({"traceback"})
ONE_LINE_FIELDS = frozenset({"error", "detail"})
SUPERVISOR_LOG_LINES = (50, 2000, 20000)
GENERIC_FAULT = "internal server error"
KEPT_FROM_A_FAULT = ("request_id", "retryable", "retry_after_ms")


def one_line(text) -> str | None:
    if text is None:
        return None
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[-1] if any(TRACEBACK_MARK in line for line in lines) else lines[0]
    return line[:LINE_CHARS]


def refresh_error(text, admin: bool):
    return text if admin else one_line(text)


def answer_for(payload, code: int, admin: bool) -> tuple[object, str | None]:
    if admin or int(code) < 500 or not isinstance(payload, dict):
        return payload, None
    if int(code) != 500:
        return {key: value for key, value in payload.items() if key != "detail"}, None
    request_id = str(payload.get("request_id") or uuid.uuid4().hex[:12])
    kept = {key: payload[key] for key in KEPT_FROM_A_FAULT if key in payload}
    said = None if payload.get("error") == GENERIC_FAULT else f"{request_id}: {payload.get('error')}"
    return {"error": GENERIC_FAULT, **kept, "request_id": request_id}, said


def incidents(rows: list[dict], admin: bool) -> list[dict]:
    if admin:
        return rows
    return [{key: (one_line(value) if key in ONE_LINE_FIELDS else value)
             for key, value in row.items() if key not in HELD_BACK} for row in rows or []]


def supervisor_log(handler, var: Path) -> None:
    least, usual, most = SUPERVISOR_LOG_LINES
    query = parse_qs(urlparse(handler.path).query)
    try:
        lines = max(least, min(most, int((query.get("lines") or [str(usual)])[0])))
    except ValueError:
        lines = usual
    text = evidence_sources.supervisor_log_tail(Path(var), lines=lines)
    handler._send_bytes(text.encode("utf-8", "replace"), "text/plain; charset=utf-8")
