from __future__ import annotations

import os


def apply_snapshot_session_policy(environ=None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    try:
        deadline = float(environ.get("GSD_REPORT_SNAPSHOT_TIMEOUT", "3600"))
    except (TypeError, ValueError):
        deadline = 3600.0
    bound_ms = str(max(120_000, int(deadline * 1000) + 300_000))
    applied = {}
    for name in ("GSD_DATABASE_IDLE_TX_TIMEOUT_MS", "GSD_DATABASE_STATEMENT_TIMEOUT_MS"):
        if not environ.get(name):
            environ[name] = bound_ms
            applied[name] = bound_ms
    return applied
