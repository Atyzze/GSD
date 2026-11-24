from __future__ import annotations

import numpy as np

from graph_scale_dynamics.measurements.estimators import diffusive_window_evidence

FIRST_USABLE_T = 3
MIXING_FLOOR_MULTIPLE = 4.0
MIN_WINDOW_POINTS = 8

GRID_POINTS = 28


def whole_range(curve: dict) -> dict:
    t = [float(v) for v in (curve.get("t") or [])]
    p0 = [float(v) for v in (curve.get("p0") or [])]
    n_component = int(curve.get("component_size") or 0)
    if not t or not p0 or n_component < 2:
        return {"whole_range_comparable": False}
    equilibrium = 1.0 / max(2, n_component)
    usable = [(time, value - equilibrium) for time, value in zip(t, p0, strict=False)
              if time >= FIRST_USABLE_T and value - equilibrium > MIXING_FLOOR_MULTIPLE * equilibrium]
    if len(usable) < MIN_WINDOW_POINTS:
        return {"whole_range_comparable": False}
    t_use = np.asarray([time for time, _ in usable], dtype=float)
    q_use = np.asarray([value for _, value in usable], dtype=float)
    grid = np.unique(np.geomspace(t_use[0], t_use[-1], num=min(GRID_POINTS, len(t_use))).astype(int))
    pick = np.clip(np.searchsorted(t_use, grid), 0, len(t_use) - 1)
    tg, qg = t_use[pick], q_use[pick]
    keep = np.concatenate([[True], np.diff(tg) > 0])
    tg, qg = tg[keep], qg[keep]
    evidence = diffusive_window_evidence(tg, qg)
    if not evidence.get("comparable"):
        return {"whole_range_comparable": False}
    return {"whole_range_comparable": True, "whole_range_points": int(len(tg)),
            "whole_range_delta_aicc": round(float(evidence["delta_aicc"]), 4),
            "whole_range_is_power_law": bool(evidence["is_power_law"])}
