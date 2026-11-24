from __future__ import annotations

import os
from pathlib import Path

_IO_FIELDS = ("rchar", "wchar", "read_bytes", "write_bytes", "cancelled_write_bytes")


def process_io(pid: int | str = "self") -> dict:
    try:
        text = Path(f"/proc/{pid}/io").read_text(encoding="ascii")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() in _IO_FIELDS:
            try:
                out[key.strip()] = int(value.strip())
            except ValueError:
                continue
    return out


def snapshot() -> dict:
    times = os.times()
    return {"io": process_io(), "cpu_seconds": float(times.user + times.system)}


def delta(before: dict, after: dict) -> dict:
    io_before, io_after = before.get("io") or {}, after.get("io") or {}
    return {"io": {key: io_after[key] - io_before.get(key, 0) for key in io_after if key in io_before},
            "cpu_seconds": round(float(after.get("cpu_seconds", 0.0)) - float(before.get("cpu_seconds", 0.0)), 6)}


def record(child_cost: dict | None, worker_start: dict) -> dict:
    child = child_cost or {}
    around = delta(worker_start, snapshot())
    child_io = child.get("io") or {}
    own_io = {key: max(0, value - int(child_io.get(key, 0))) for key, value in (around.get("io") or {}).items()}
    return {"contract": "attempt-cost-2", "child": child,
            "bookkeeping": {"io": own_io, "cpu_seconds": around.get("cpu_seconds")},
            "bookkeeping_io_including_child": around.get("io"),
            "note": "PostgreSQL's writes for the attempt are in its backends, not here"}
