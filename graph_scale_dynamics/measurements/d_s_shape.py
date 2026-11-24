from __future__ import annotations

import numpy as np

from graph_scale_dynamics.measurements import estimators

SHAPE_CONTRACT = "gsd-d-s-shape-2"
MIN_GRID_POINTS = 6


def _drift(log_t: np.ndarray, d_s_t: np.ndarray) -> float | None:
    if len(d_s_t) < 3 or float(np.ptp(log_t)) == 0.0:
        return None
    return round(float(np.polyfit(log_t, d_s_t, 1)[0]), 4)


def shape(curve: dict) -> dict:
    t = np.asarray([float(v) for v in (curve.get("t") or [])], dtype=float)
    p0 = np.asarray([float(v) for v in (curve.get("p0") or [])], dtype=float)
    n_component = int(curve.get("component_size") or 0)
    out = {"contract": SHAPE_CONTRACT, "measured": False, "one_over_n_taken_off": False}
    if not len(t) or len(t) != len(p0) or n_component < 2:
        return dict(out, reason="no curve")
    found = estimators._return_grid(t, p0, n_component)
    if found is None:
        return dict(out, reason="the return probability reaches the mixing floor before a usable range")
    _picked, tg, qg = found
    if len(tg) < MIN_GRID_POINTS:
        return dict(out, reason="too few times for a running exponent")
    d_s_t = -2.0 * np.log(qg[1:] / qg[:-1]) / np.log(tg[1:] / tg[:-1])
    log_at = np.log(np.sqrt(tg[1:] * tg[:-1]))
    latest = estimators._latest_slope(tg, qg)
    window = slice(int(latest["first"]), len(d_s_t))
    return {"contract": SHAPE_CONTRACT, "measured": True, "one_over_n_taken_off": False,
            "t": [round(float(v), 2) for v in np.exp(log_at)], "d_s_t": [round(float(v), 4) for v in d_s_t],
            "window": [int(window.start), int(window.stop)],
            "d_s_of_the_window": round(float(-2.0 * latest["slope"]), 4),
            "moves_across_the_window": round(float(-2.0 * latest["moves"]), 4),
            "drift_in_window": _drift(log_at[window], d_s_t[window]),
            "drift_whole_range": _drift(log_at, d_s_t),
            "spread_in_window": round(float(np.std(d_s_t[window])), 4)}
