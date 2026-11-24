from __future__ import annotations

import math

MEASURED_SIGMAS = 2.0


def _error(values, index: int) -> float | None:
    value = values[index] if values is not None and 0 <= index < len(values) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def step_tolerances(sizes, measured, pairs) -> list | None:
    if not sizes or not measured or not pairs:
        return None
    from graph_scale_dynamics.calibration import finite_size
    out = []
    for i_a, i_b in pairs:
        m_a, m_b = _error(measured, i_a), _error(measured, i_b)
        if m_a is None or m_b is None or i_a >= len(sizes) or i_b >= len(sizes):
            return None
        out.append(MEASURED_SIGMAS * math.hypot(m_a, m_b) + finite_size.tolerance(int(sizes[i_a]), int(sizes[i_b])))
    return out


def settled_share(a: tuple, b: tuple) -> float | None:
    if a[2] is None or b[2] is None:
        return None
    from graph_scale_dynamics.calibration import finite_size
    excess = abs(float(b[1]) - float(a[1])) - finite_size.tolerance(int(a[0]), int(b[0]))
    noise = MEASURED_SIGMAS * math.hypot(float(a[2]), float(b[2]))
    if excess <= 0:
        return 1.0
    return 0.0 if noise <= 0 else max(0.0, 1.0 - excess / noise)


__all__ = ["MEASURED_SIGMAS", "settled_share", "step_tolerances"]
