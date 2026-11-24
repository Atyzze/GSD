from __future__ import annotations

import math

RUNG_ETA_CONTRACT = "gsd-rung-eta-1"

CENSOR_FLOOR_FRACTION = 0.5

MIN_SAMPLES = 5


def _ceiling(spec: dict | None, n: int | None = None) -> float:
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    from graph_scale_dynamics.scheduling.limits import estimated_seconds
    if not is_engine_campaign(spec or {}) or n is None:
        return math.inf
    try:
        found = estimated_seconds(spec or {}, int(n))
    except (TypeError, ValueError):
        return math.inf
    return float(found) if found else math.inf


def classify_attempts(rows, *, ceiling: float) -> dict:
    events, censored, discarded = [], [], 0
    floor = ceiling * CENSOR_FLOOR_FRACTION if math.isfinite(ceiling) else math.inf
    for row in rows or []:
        wall = row.get("wall_seconds")
        if not isinstance(wall, (int, float)) or isinstance(wall, bool) or wall <= 0:
            continue
        wall = float(wall)
        if row.get("exit_code") == 0:
            events.append(wall)
        elif wall >= floor:
            censored.append(wall)
        else:
            discarded += 1
    return {"events": sorted(events), "censored": sorted(censored),
            "discarded_short_failures": discarded}


def kaplan_meier(events: list[float], censored: list[float]) -> list[tuple[float, float]]:
    points: list[tuple[float, int]] = [(t, 1) for t in events] + [(t, 0) for t in censored]
    points.sort(key=lambda pair: (pair[0], -pair[1]))
    at_risk = len(points)
    survival = 1.0
    curve: list[tuple[float, float]] = []
    index = 0
    while index < len(points):
        time = points[index][0]
        deaths = 0
        exits = 0
        while index < len(points) and points[index][0] == time:
            deaths += points[index][1]
            exits += 1
            index += 1
        if deaths and at_risk > 0:
            survival *= 1.0 - deaths / at_risk
            curve.append((time, survival))
        at_risk -= exits
    return curve


def quantile(curve: list[tuple[float, float]], fraction: float) -> float | None:
    target = 1.0 - fraction
    for time, survival in curve:
        if survival <= target + 1e-12:
            return time
    return None


def rung_duration(rows, *, spec: dict | None = None,
                  ceiling: float | None = None) -> dict:
    limit = float(ceiling) if ceiling is not None else _ceiling(spec)
    parts = classify_attempts(rows, ceiling=limit)
    events, censored = parts["events"], parts["censored"]
    usable = len(events) + len(censored)
    result = {
        "contract": RUNG_ETA_CONTRACT,
        "attempts": usable,
        "completed": len(events),
        "censored": len(censored),
        "discarded_short_failures": parts["discarded_short_failures"],
        "ceiling_seconds": None if not math.isfinite(limit) else round(limit, 1),
        "median_seconds": None,
        "p25_seconds": None,
        "p75_seconds": None,
        "identifiable": False,
        "reason": None,
    }
    if usable < MIN_SAMPLES:
        result["reason"] = f"only {usable} usable attempt(s); {MIN_SAMPLES} needed"
        return result
    if not events:
        result["reason"] = "no attempt at this rung has finished"
        return result
    curve = kaplan_meier(events, censored)
    median = quantile(curve, 0.5)
    if median is None:
        result["reason"] = (
            f"{len(censored)} of {usable} attempts hit the time ceiling without finishing, "
            "so more than half the population never completed and the median is not "
            "identifiable from this data"
        )
        result["exceeds_seconds"] = round(max(events + censored), 1)
        return result
    result.update({
        "median_seconds": round(median, 1),
        "p25_seconds": (lambda v: None if v is None else round(v, 1))(quantile(curve, 0.25)),
        "p75_seconds": (lambda v: None if v is None else round(v, 1))(quantile(curve, 0.75)),
        "identifiable": True,
    })
    return result


def extrapolated_estimate(own_by_rung: dict, n: int) -> dict:
    lower = [(int(k), float(v)) for k, v in (own_by_rung or {}).items()
             if int(k) < int(n) and float(v) > 0]
    if not lower:
        return {"seconds": None, "basis": None,
                "reason": "the first rung of this law: nothing below it to extrapolate from, "
                          "and no comparable attempt at this rung yet"}
    from_n, seconds = max(lower)
    factor = float(n) / float(from_n)
    return {"seconds": round(seconds * factor, 1), "basis": from_n, "factor": round(factor, 2),
            "reason": (f"no median for this rung yet, so extrapolated from this law's own "
                       f"N={from_n} at {factor:.0f}x the work; a rough scaling, not a measurement")}


def job_budget_seconds(job: dict) -> float | None:
    one_shot = (((job.get("spec") or {}).get("execution") or {}).get("one_shot") or {})
    units, unit = one_shot.get("work_budget"), (one_shot.get("work_unit") or {}).get("seconds_a_unit")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (units, unit)):
        return None
    return float(units) * float(unit)


def estimate_for_job(duration_samples: dict, spec: dict, job: dict, elapsed: float,
                     *, own_by_rung: dict | None = None,
                     population_median_by_rung: dict | None = None) -> dict | None:
    try:
        multiplier = float(((job.get("spec") or {}).get("execution") or {})
                           .get("sweeps_multiplier") or 1.0)
    except (TypeError, ValueError):
        multiplier = 1.0
    rows = duration_samples.get((int(job["n"]), multiplier))
    ceiling = job_budget_seconds(job) or _ceiling(spec, int(job["n"]))
    estimate = rung_duration(rows, spec=spec, ceiling=ceiling) if rows else {
        "identifiable": False, "median_seconds": None, "attempts": 0, "censored": 0}
    scale = candidate_scale(own_by_rung or {}, population_median_by_rung or {})
    if scale.get("factor") is not None:
        estimate = dict(estimate, candidate_factor=scale["factor"])
    extrapolated = None
    if estimate.get("median_seconds") is None:
        extrapolated = extrapolated_estimate(own_by_rung or {}, int(job["n"]))
        if extrapolated.get("seconds") is not None:
            estimate = dict(estimate, median_seconds=extrapolated["seconds"],
                            p75_seconds=extrapolated["seconds"] * 1.8,
                            extrapolated=True, candidate_factor=None)
    return dict(estimate, n=int(job["n"]), sweeps_multiplier=multiplier,
                candidate_scale=scale, extrapolation=extrapolated,
                progress=remaining(estimate, elapsed))


def own_rung_seconds(rungs, *, seeds: int = 3) -> dict[int, float]:
    divisor = max(1, int(seeds))
    return {int(r["n"]): float(r["elapsed_s"]) / divisor for r in (rungs or [])
            if (r.get("elapsed_s") or 0) > 0}


def population_median_by_rung(rung_spend: dict) -> dict[int, float]:
    by_n: dict[int, list[float]] = {}
    for key, seconds in (rung_spend or {}).items():
        try:
            n = int(key[1])
        except (TypeError, IndexError, ValueError):
            continue
        if seconds and float(seconds) > 0:
            by_n.setdefault(n, []).append(float(seconds))
    out: dict[int, float] = {}
    for n, values in by_n.items():
        values.sort()
        mid = len(values) // 2
        out[n] = values[mid] if len(values) % 2 else 0.5 * (values[mid - 1] + values[mid])
    return out


def candidate_scale(own_by_rung: dict, population_median_by_rung: dict, *,
                    min_rungs: int = 2, clamp: float = 8.0) -> dict:
    ratios: list[float] = []
    used: list[int] = []
    for n, own in sorted((int(k), float(v)) for k, v in (own_by_rung or {}).items()):
        pop = (population_median_by_rung or {}).get(n)
        if pop is None or float(pop) <= 0 or own <= 0:
            continue
        ratios.append(own / float(pop))
        used.append(n)
    if len(ratios) < int(min_rungs):
        return {"factor": None, "rungs": used, "reason": (
            f"{len(ratios)} comparable lower rung(s); at least {int(min_rungs)} are needed "
            "before this law's own history says anything about its position in the population")}
    geometric = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
    factor = min(max(geometric, 1.0 / float(clamp)), float(clamp))
    return {"factor": round(factor, 3), "rungs": used,
            "clamped": factor != geometric,
            "reason": (f"this law ran {factor:.2f}x the population median over its own "
                       f"N={', '.join(str(n) for n in used)}")}


def remaining(estimate: dict, elapsed_seconds: float) -> dict:
    elapsed = max(0.0, float(elapsed_seconds or 0.0))
    out = {"elapsed_seconds": round(elapsed, 1), "remaining_seconds": None,
           "overdue": False, "overdue_by_seconds": None,
           "identifiable": bool(estimate.get("identifiable"))}
    median = estimate.get("median_seconds")
    if median is None:
        return out
    factor = estimate.get("candidate_factor")
    scale = float(factor) if isinstance(factor, (int, float)) and factor > 0 else 1.0
    median = float(median) * scale
    p75 = float(estimate.get("p75_seconds") or median) * scale
    out["scaled_by"] = round(scale, 3) if scale != 1.0 else None
    out["median_seconds"] = round(median, 1)
    if elapsed > p75:
        out["overdue"] = True
        out["overdue_by_seconds"] = round(elapsed - p75, 1)
        return out
    out["remaining_seconds"] = round(max(0.0, float(median) - elapsed), 1)
    return out
