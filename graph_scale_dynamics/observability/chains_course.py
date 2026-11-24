from __future__ import annotations

import bisect
import math

from graph_scale_dynamics.domain import chain_list as CL

CONTRACT = "chains-course-1"
COURSE_POINTS = 40
STRUCTURE_POINTS = 12
COURSE_FIELDS = ("sweep", "energy_per_node", "mean_degree")
STRUCTURE_FIELDS = ("sweep", "triangles_per_node", "largest_component_share")


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _short(value: float | None, digits: int = 5) -> float | None:
    return None if value is None else float(f"{value:.{digits}g}")


def kept_indexes(sweeps: list[float], keep: int) -> list[int]:
    count = len(sweeps)
    if count <= max(2, keep):
        return list(range(count))
    if any(later < earlier for earlier, later in zip(sweeps, sweeps[1:], strict=False)):
        step = (count - 1) / (keep - 1)
        return sorted({round(i * step) for i in range(keep)})
    first, last = sweeps[0], sweeps[-1]
    half = max(1, (keep - 2) // 2)
    low, high = math.log1p(max(0.0, first)), math.log1p(max(0.0, last))
    targets = ([first + (last - first) * (i + 1) / (half + 1) for i in range(half)]
               + [math.expm1(low + (high - low) * (i + 1) / (half + 1)) for i in range(half)])
    chosen = {0, count - 1}
    for target in targets:
        at = bisect.bisect_left(sweeps, target)
        near = [i for i in (at - 1, at) if 0 <= i < count]
        chosen.add(min(near, key=lambda i: (abs(sweeps[i] - target), i)))
    return sorted(chosen)


def chain_course(trajectory: list | None, n: int) -> dict | None:
    points = [p for p in trajectory or [] if isinstance(p, dict) and _number(p.get("move")) is not None]
    if not points:
        return None
    n = max(1, int(n))
    sweeps = [float(p["move"]) / n for p in points]
    course = []
    for i in kept_indexes(sweeps, COURSE_POINTS):
        point = points[i]
        energy = _number(point.get("energy"))
        degree = _number(point.get("mean_degree"))
        if degree is None and _number(point.get("edges")) is not None:
            degree = 2.0 * float(point["edges"]) / n
        course.append([_short(sweeps[i]), _short(None if energy is None else energy / n, 6), _short(degree)])
    structured = [i for i, p in enumerate(points) if _number(p.get("triangles")) is not None]
    structure = []
    for j in kept_indexes([sweeps[i] for i in structured], STRUCTURE_POINTS):
        point = points[structured[j]]
        largest = _number(point.get("largest_component"))
        structure.append([_short(sweeps[structured[j]]), _short(float(point["triangles"]) / n),
                          _short(None if largest is None else largest / n)])
    return {"points": len(points), "course": course, "structure": structure}


def seed_chains_course(envelope: dict) -> dict:
    try:
        return _seed_chains_course(envelope)
    except Exception as exc:  # noqa: BLE001
        return {"contract": CONTRACT, "error": f"{type(exc).__name__}: {exc}"}


def _seed_chains_course(envelope: dict) -> dict:
    n = max(1, int(envelope.get("n") or 1))
    declared = CL.record(envelope, CL.GIVEN)
    given_chain = CL.block(envelope, CL.GIVEN)
    given = None if declared.get("skipped") else chain_course(given_chain.get("trajectory"), n)
    if given is not None:
        start = declared.get("init") or given_chain.get("init")
        given.update({"start": start if isinstance(start, str) else None,
                     "kernel": declared.get("kernel") or given_chain.get("kernel")})
    out = {"contract": CONTRACT, "n": n, "fields": {"course": list(COURSE_FIELDS),
                                                    "structure": list(STRUCTURE_FIELDS)},
           "empty": chain_course(CL.trajectory(envelope, CL.FROM_EMPTY), n), "given": given}
    for name in CL.more_names(envelope):
        summary, block = CL.record(envelope, name), CL.block(envelope, name)
        course = None if (summary or {}).get("skipped") else chain_course(block.get("trajectory"), n)
        if course is not None:
            course.update({"start": (summary or {}).get("init") or block.get("init"),
                           "kernel": (summary or {}).get("kernel") or block.get("kernel"),
                           "ended_at_cap": bool(block.get("ended"))})
        out[str(name)] = course
    return out
