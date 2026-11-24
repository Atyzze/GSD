from __future__ import annotations

import os
from pathlib import Path


def cores_of(cpus, sysfs=Path("/sys/devices/system/cpu")) -> int | None:
    cores = set()
    for cpu in cpus:
        topology = Path(sysfs) / f"cpu{int(cpu)}" / "topology"
        try:
            cores.add(((topology / "physical_package_id").read_text().strip(),
                       (topology / "core_id").read_text().strip()))
        except OSError:
            return None
    return len(cores) or None


def cpu_topology() -> tuple[int, int]:
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = []
    logical = len(allowed) or max(1, os.cpu_count() or 1)
    logical = max(1, int(logical))

    physical = cores_of(allowed) if allowed else None
    if not physical:
        try:
            import psutil
            physical = psutil.cpu_count(logical=False)
        except Exception:
            physical = None
    if not physical:
        physical = logical
    physical = max(1, min(logical, int(physical)))
    return physical, logical


def choose_auto_slots(*, physical: int, logical: int,
                      override: int | None = None,
                      use_smt: bool = True,
                      physical_safety_cap: int = 16,
                      logical_safety_cap: int = 32) -> int:
    logical = max(1, int(logical))
    physical = max(1, min(logical, int(physical)))
    if override is not None:
        return max(1, min(logical, int(override)))
    if use_smt:
        return max(1, min(logical, int(logical_safety_cap)))
    return max(1, min(physical, int(physical_safety_cap)))


def configured_monitor_ceiling(total_slots: int, logical_threads: int) -> float:
    logical = max(1, int(logical_threads))
    return min(100.0, 100.0 * max(0, int(total_slots)) / logical)


def one_worker_a_core(physical: int, logical: int, say=print) -> int:
    logical = max(1, int(logical))
    physical = max(1, min(logical, int(physical)))
    smt = f"SMT on, {logical} hardware threads" if logical > physical else "no SMT"
    say(f"compute slots: the ramp grows to one worker a physical core, {physical} at most ({smt}); "
        "--workers K holds K slots, GSD_MAX_WORKERS=K raises the ramp's ceiling to K")
    return physical


def fleet_ceiling(environ, physical: int, logical: int, say=print) -> int:
    configured = (environ or {}).get("GSD_MAX_WORKERS")
    if configured:
        say(f"compute slots: the ramp grows to GSD_MAX_WORKERS={int(configured)} at most")
        return max(1, int(configured))
    return one_worker_a_core(physical, logical, say=say)


def held_slots(workers: int, environ, say=print) -> tuple[int, int]:
    held = max(1, int(workers))
    configured = (environ or {}).get("GSD_MAX_WORKERS")
    ceiling = max(held, int(configured)) if configured else held
    say(f"compute slots: --workers {held} holds {held} slot(s); the ramp gives none back"
        + (f" and grows to GSD_MAX_WORKERS={ceiling} at most" if ceiling > held else ""))
    return held, ceiling
