from __future__ import annotations

import os
import re
from typing import Mapping

POSTGRES_TUNING_CONTRACT = "gsd-postgres-tuning-1"

_MIB = 1024 * 1024
_GIB = 1024 * 1024 * 1024

_FALLBACK_RAM_BYTES = 8 * _GIB
_FALLBACK_CPUS = 4

def format_size(value: int) -> str:
    value = int(value)
    for unit, factor in (("GB", _GIB), ("MB", _MIB), ("kB", 1024)):
        if value >= factor and value % factor == 0:
            return f"{value // factor}{unit}"
    return f"{max(0, value // 1024)}kB"


def _clamp(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, value)))


def _round_to(value: int, quantum: int) -> int:
    return max(quantum, (int(value) // quantum) * quantum)


def total_memory_bytes() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return _FALLBACK_RAM_BYTES


def cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or _FALLBACK_CPUS)


def resource_plan(*, memory_bytes: int | None = None, cpus: int | None = None,
                  env: Mapping[str, str] | None = None) -> dict[str, object]:
    env = os.environ if env is None else env
    memory_bytes = int(memory_bytes if memory_bytes is not None else total_memory_bytes())
    memory_bytes = max(_GIB, memory_bytes)
    cpus = int(cpus if cpus is not None else cpu_count())
    cpus = max(1, cpus)

    shared_buffers = _round_to(_clamp(memory_bytes * 0.15, 256 * _MIB, 8 * _GIB), 128 * _MIB)

    work_mem = _round_to(_clamp(memory_bytes * 0.0015, 16 * _MIB, 128 * _MIB), 16 * _MIB)

    maintenance_work_mem = _round_to(_clamp(memory_bytes * 0.03, 64 * _MIB, 2 * _GIB), 64 * _MIB)
    effective_cache_size = _round_to(_clamp(memory_bytes * 0.55, 512 * _MIB, 48 * _GIB), 256 * _MIB)
    temp_buffers = _round_to(_clamp(memory_bytes * 0.001, 8 * _MIB, 64 * _MIB), 8 * _MIB)

    min_dsm = _round_to(_clamp(memory_bytes * 0.02, 0, 2 * _GIB), 128 * _MIB)

    worker_slots = _clamp(cpus, 8, 32)
    parallel_workers = _clamp(cpus, 2, 32)
    per_gather = _clamp(max(2, cpus // 2), 2, 8)

    budget: dict[str, object] = {
        "contract": POSTGRES_TUNING_CONTRACT,
        "memory_bytes": memory_bytes,
        "cpus": cpus,
        "shared_buffers_bytes": shared_buffers,
        "work_mem_bytes": work_mem,
        "min_dynamic_shared_memory_bytes": min_dsm,
        "resident_floor_bytes": shared_buffers + min_dsm,
    }

    settings: dict[str, str] = {
        "shared_buffers": format_size(shared_buffers),
        "work_mem": format_size(work_mem),
        "maintenance_work_mem": format_size(maintenance_work_mem),
        "effective_cache_size": format_size(effective_cache_size),
        "temp_buffers": format_size(temp_buffers),
        "min_dynamic_shared_memory": format_size(min_dsm),
        "random_page_cost": "1.1",
        "effective_io_concurrency": str(_clamp(cpus * 16, 32, 512)),
        "maintenance_io_concurrency": str(_clamp(cpus * 8, 16, 256)),
        "max_worker_processes": str(worker_slots),
        "max_parallel_workers": str(parallel_workers),
        "max_parallel_workers_per_gather": str(per_gather),
        "max_parallel_maintenance_workers": str(_clamp(max(2, cpus // 4), 2, 8)),
        "commit_delay": "5000",
        "commit_siblings": "2",
        "huge_pages": "try",
        "track_io_timing": "on",
        "track_wal_io_timing": "on",
        "log_temp_files": "64MB",
    }

    overrides: dict[str, str] = {}
    for guc in tuple(settings):
        key = "GSD_PG_" + guc.upper()
        raw = str(env.get(key, "")).strip()
        if raw:
            overrides[guc] = raw
            settings[guc] = raw
    budget["overrides"] = overrides
    return {"settings": settings, "budget": budget}


def render_settings(settings: Mapping[str, str]) -> str:
    lines = []
    for key, value in settings.items():
        text = str(value)
        if not re.fullmatch(r"[A-Za-z0-9_.]+", text):
            text = "'" + text.replace("'", "''") + "'"
        lines.append(f"{key} = {text}")
    return "\n".join(lines) + "\n"
