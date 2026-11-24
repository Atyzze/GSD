from __future__ import annotations

import math

from graph_scale_dynamics.research.family_classification import classify_law

PROBES = ("d_s", "d_V", "d_B", "d_w")


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def place(rungs, *, anchors: dict | None) -> dict | None:
    read = []
    for n, values, degree in rungs:
        clean = {p: float(v) for p, v in (values or {}).items() if p in PROBES and _finite(v) is not None}
        if clean:
            read.append((int(n), clean, degree))
    if not read:
        return None
    by_n = {}
    for n, values, degree in sorted(read):
        if len(values) < 2:
            continue
        ranked = classify_law(values, n=n, mean_degree=degree,
                              refused_probes=tuple(p for p in PROBES if p not in values),
                              anchors=anchors).get("geometries") or []
        if ranked:
            by_n[n] = (ranked[0]["family"], ranked[0]["distance"])
    top = max(row[0] for row in read)
    placed = max(by_n, default=None)
    family, distance = by_n[placed] if placed is not None else (None, None)
    return {"by_n": by_n, "n": top, "placed_n": placed, "nearest": family, "distance": distance}
