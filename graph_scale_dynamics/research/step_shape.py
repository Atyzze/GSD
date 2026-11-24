from __future__ import annotations

DECEL_RATIO_MAX = 1.0


def step_ratios(abs_deltas: list[float]) -> list[float | None]:
    return [abs_deltas[i + 1] / abs_deltas[i] if abs_deltas[i] > 1e-9 else None for i in range(len(abs_deltas) - 1)]


def shown(ratios: list) -> list:
    return [None if r is None else round(r, 4) for r in ratios]


def decelerating(ratios: list, *, judge: int = 2) -> bool:
    judged = [r for r in (ratios or [])[-judge:] if r is not None]
    return bool(judged) and all(r < DECEL_RATIO_MAX for r in judged)


def remaining_distance(abs_deltas: list[float], ratios: list) -> float | None:
    resolved = [r for r in (ratios or []) if r is not None]
    if not resolved or not abs_deltas:
        return None
    r = resolved[-1]
    if not (0.0 < r < 1.0):
        return None
    return abs_deltas[-1] * r / (1.0 - r)


__all__ = ["DECEL_RATIO_MAX", "decelerating", "remaining_distance", "shown", "step_ratios"]
