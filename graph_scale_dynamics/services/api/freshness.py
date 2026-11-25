from __future__ import annotations

import math

from graph_scale_dynamics.domain.cadence import TICK_SECONDS, ticks

ROUNDS = 2.0
MOST_STALE_AFTER_SECONDS = ticks(15)
REFRESH_SLOT_WAIT_SECONDS = ticks(4)
CONTRACT = "gsd-dashboard-freshness-1"


def build_seconds(payload: dict | None) -> float | None:
    found = ((payload or {}).get("dashboard_response") or {}).get("build_ms")
    try:
        value = float(found) / 1000.0
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def one_round_seconds(ttl: float, builds: list[float | None], slots: int) -> float:
    waves = math.ceil(max(1, len(builds)) / max(1, int(slots)))
    slowest = max([float(b) for b in builds if b] or [0.0])
    return float(ttl) + TICK_SECONDS + waves * slowest


def stale_after_seconds(ttl: float, builds: list[float | None], slots: int) -> float:
    least = 3.0 * float(ttl)
    return max(least, min(MOST_STALE_AFTER_SECONDS, ROUNDS * one_round_seconds(ttl, builds, slots)))


def answer(ttl: float, builds: list[float | None], slots: int) -> dict:
    return {"stale_after_ms": round(stale_after_seconds(ttl, builds, slots) * 1000.0),
            "freshness": reading(ttl, builds, slots)}


def reading(ttl: float, builds: list[float | None], slots: int) -> dict:
    return {"contract": CONTRACT, "ttl_seconds": float(ttl), "snapshots": len(builds), "slots": int(slots),
            "slowest_build_seconds": round(max([float(b) for b in builds if b] or [0.0]), 3),
            "one_round_seconds": round(one_round_seconds(ttl, builds, slots), 3),
            "stale_after_seconds": round(stale_after_seconds(ttl, builds, slots), 3)}
