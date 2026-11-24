from __future__ import annotations

TICK_SECONDS = 4.0


def ticks(count: float) -> float:
    return float(count) * TICK_SECONDS


def idle_backoff(previous: float, did_work: bool, *, floor: float, ceiling: float) -> float:
    if did_work:
        return float(floor)
    return min(float(ceiling), max(float(floor), float(previous) * 2.0))
