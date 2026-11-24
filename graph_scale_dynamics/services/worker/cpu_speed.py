from __future__ import annotations

import os
from pathlib import Path

CPU_SPEED_CONTRACT = "gsd-cpu-speed-1"


def chain_moves(checkpoint: dict | None) -> int:
    total = 0
    for block in (checkpoint or {}).get("chains") or []:
        attempted = (block or {}).get("attempted") or {}
        total += sum(int(value) for value in attempted.values() if isinstance(value, (int, float)))
    return total


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def last_cpu() -> int | None:
    stat = _read("/proc/self/stat")
    if not stat:
        return None
    rest = stat.rsplit(")", 1)[-1].split()
    try:
        return int(rest[36])
    except (IndexError, ValueError):
        return None


def topology(cpu: int | None) -> dict:
    if cpu is None:
        return {}
    base = f"/sys/devices/system/cpu/cpu{int(cpu)}"
    out = {"core": _read(f"{base}/topology/core_id"), "package": _read(f"{base}/topology/physical_package_id"),
           "siblings": _read(f"{base}/topology/thread_siblings_list"), "l3": _read(f"{base}/cache/index3/id")}
    return {key: value for key, value in out.items() if value is not None}


def cpu_speed(envelope: dict, resume: dict | None, cpu_seconds: float) -> dict:
    moves = max(0, chain_moves(envelope.get("sampling_checkpoint"))
                - chain_moves((resume or {}).get("checkpoint")))
    cpu = last_cpu()
    try:
        allowed = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = None
    return {"contract": CPU_SPEED_CONTRACT, "moves": moves,
            "moves_per_cpu_second": round(moves / cpu_seconds, 1) if cpu_seconds > 0 else None,
            "cpu": cpu, **topology(cpu), "cpus_allowed": allowed}
