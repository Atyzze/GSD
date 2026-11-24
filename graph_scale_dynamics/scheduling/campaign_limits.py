from __future__ import annotations

from graph_scale_dynamics.scheduling.rungs import extension_enabled
import math


DEFAULT_WALL_SECONDS = 604_800.0

def campaign_wall_seconds(spec: dict, default: float | None = DEFAULT_WALL_SECONDS
                          ) -> float | None:
    budgets = spec.get("budgets") or {}
    if extension_enabled(spec):
        return None
    if "wall_seconds" not in budgets:
        return None if default is None else float(default)
    raw = budgets["wall_seconds"]
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None if default is None else float(default)
    if not math.isfinite(value) or value <= 0:
        return None if default is None else float(default)
    return value

def campaign_max_n(spec: dict) -> int | None:
    if extension_enabled(spec):
        return None
    raw = (spec.get("budgets") or {}).get("max_n")
    return int(raw if raw is not None else 4096)
