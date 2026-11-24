from __future__ import annotations


def classification_from_summary(summary: dict, limits: dict | None) -> str | None:
    limits = limits or {}
    window = (limits.get("mean_degree_window") or {})
    cap = window.get("max")
    degree = (summary or {}).get("mean_degree")
    degree = degree.get("mean") if isinstance(degree, dict) else degree
    has_degree = isinstance(degree, (int, float)) and not isinstance(degree, bool)
    if has_degree and cap is not None and float(degree) >= float(cap):
        return "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
    if cap is None or not has_degree:
        return None
    floor_value = window.get("min")
    if floor_value is not None and float(degree) < float(floor_value):
        return "REFUSED_MEAN_DEGREE_BELOW_WINDOW"
    return None
