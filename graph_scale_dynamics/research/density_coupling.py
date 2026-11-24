from __future__ import annotations

import math

from graph_scale_dynamics.research.refused_rungs import masked

CONTRACT = "gsd-density-coupling-1"

MIN_READINGS = 20

OUTLIER_FLOORS = 1.0



def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fit(points: list[tuple[float, float]]) -> dict | None:
    count = len(points)
    if count < 3:
        return None
    mean_x = sum(p[0] for p in points) / count
    mean_y = sum(p[1] for p in points) / count
    var_x = sum((p[0] - mean_x) ** 2 for p in points) / count
    var_y = sum((p[1] - mean_y) ** 2 for p in points) / count
    if var_x <= 0:
        return None
    cov = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / count
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    residuals = [p[1] - (intercept + slope * p[0]) for p in points]
    scatter = math.sqrt(sum(r * r for r in residuals) / count)
    r2 = (cov * cov) / (var_x * var_y) if var_y > 0 else None
    return {"slope": slope, "intercept": intercept, "scatter": scatter, "r2": r2,
            "mean_degree_mean": mean_x, "d_s_spread": math.sqrt(var_y)}


def density_coupling(rows: list[dict], *, floors: dict | None = None,
                     min_readings: int = MIN_READINGS,
                     outlier_floors: float = OUTLIER_FLOORS) -> dict:
    floor = _finite((floors or {}).get("d_s"))
    by_rung: dict[int, list[tuple[float, float, str]]] = {}
    for row in rows or []:
        sizes = row.get("sizes") or []
        degrees = row.get("mean_degree") or []
        spectral = masked(((row.get("probes") or {}).get("d_s")) or [], (row.get("probe_buckets") or {}).get("d_s"))
        law = str(row.get("candidate_id") or "")
        for index, size in enumerate(sizes):
            if index >= len(degrees) or index >= len(spectral):
                continue
            degree = _finite(degrees[index])
            value = _finite(spectral[index])
            if degree is None or value is None:
                continue
            by_rung.setdefault(int(size), []).append((degree, value, law))

    rungs: dict[str, dict] = {}
    departures: list[dict] = []
    for size in sorted(by_rung):
        points = [(a, b) for a, b, _ in by_rung[size]]
        if len(points) < min_readings:
            rungs[str(size)] = {"readings": len(points),
                                "why": f"fewer than {min_readings} readings; not fitted"}
            continue
        fit = _fit(points)
        if fit is None:
            rungs[str(size)] = {"readings": len(points),
                                "why": "every reading sits at one mean degree; nothing to fit"}
            continue
        in_floors = (fit["scatter"] / floor) if floor else None
        collapsed = in_floors is not None and in_floors < 1.0
        entry = {
            "readings": len(points),
            "r2": round(fit["r2"], 5) if fit["r2"] is not None else None,
            "slope": round(fit["slope"], 5),
            "intercept": round(fit["intercept"], 5),
            "scatter": round(fit["scatter"], 5),
            "scatter_in_noise_floors": (None if in_floors is None else round(in_floors, 4)),
            "d_s_spread": round(fit["d_s_spread"], 5),
            "collapsed_onto_one_curve": collapsed,
        }
        if not collapsed:
            entry["departures"] = None
            entry["why_no_departures"] = (
                "the population's own scatter here is at or above the probe's noise floor, so "
                "there is no line tight enough for a departure from it to mean anything")
            rungs[str(size)] = entry
            continue
        for degree, value, law in by_rung[size]:
            residual = value - (fit["intercept"] + fit["slope"] * degree)
            if floor and abs(residual) >= outlier_floors * floor:
                departures.append({
                    "candidate_id": law, "n": size, "mean_degree": round(degree, 4),
                    "d_s": round(value, 4),
                    "predicted_from_mean_degree": round(fit["intercept"] + fit["slope"] * degree, 4),
                    "residual": round(residual, 4),
                    "residual_in_noise_floors": round(abs(residual) / floor, 3),
                    "residual_in_population_scatter": (
                        round(abs(residual) / fit["scatter"], 2) if fit["scatter"] > 0 else None)})
        entry["departures"] = sum(1 for d in departures if d["n"] == size)
        rungs[str(size)] = entry

    fitted = {n: r for n, r in rungs.items() if r.get("r2") is not None}
    collapsed = {n: r for n, r in fitted.items() if r.get("collapsed_onto_one_curve")}
    deepest = max((int(n) for n in fitted), default=None)
    tightest = min((r["scatter_in_noise_floors"] for r in collapsed.values()
                    if r.get("scatter_in_noise_floors") is not None), default=None)
    by_depth = [(int(n), r["r2"]) for n, r in sorted(fitted.items(), key=lambda x: int(x[0]))
                if r.get("r2") is not None]
    if not fitted:
        reading = "no rung carried enough readings to fit d_s against mean degree"
    elif not collapsed:
        reading = ("at no fitted rung is the population tight enough around one d_s(mean degree) "
                   "curve for the two to be called the same measurement; d_s and mean degree "
                   "carry distinguishable information here")
    elif departures:
        reading = (
            f"{len(departures)} readings sit {outlier_floors:g} noise floor or more off the "
            f"d_s(mean degree) line at a rung where that line is tighter than the probe can "
            "resolve. Those are the laws carrying something density does not predict, and they "
            "are where a geometry would show up first.")
    else:
        reading = (
            f"at every collapsed rung d_s is predicted by mean degree alone to within "
            f"{tightest:.2f} of the probe's own noise floor, and not one law departs from that "
            f"line by {outlier_floors:g} floor or more. On this population d_s is not a second "
            "measurement; it is mean degree read through a spectral probe. A law that is "
            "measuring a geometry is one that leaves this line.")
    if len(by_depth) >= 2 and by_depth[0][1] is not None and by_depth[-1][1] is not None:
        first, last = by_depth[0][1], by_depth[-1][1]
        moves = "grows" if last > first else "weakens" if last < first else "stays the same"
        reading += (f" The coupling {moves} with N: r^2 runs {first:.2f} at N={by_depth[0][0]:,} "
                    f"to {last:.2f} at N={by_depth[-1][0]:,}.")
    departures.sort(key=lambda d: -d["residual_in_noise_floors"])
    return {
        "contract": CONTRACT,
        "descriptive_advisory_only": True,
        "gates_nothing": True,
        "d_s_noise_floor": floor,
        "outlier_threshold_in_noise_floors": outlier_floors,
        "by_rung": rungs,
        "deepest_fitted_rung": deepest,
        "collapsed_rungs": sorted(int(n) for n in collapsed),
        "tightest_scatter_in_noise_floors": tightest,
        "r2_by_rung": {str(n): r2 for n, r2 in by_depth},
        "departures": departures[:100],
        "departure_count": len(departures),
        "reading": reading,
        "caution": (
            "A tight fit says the population lies on one curve, not which curve. And laws reaching the deep rungs were "
            "selected for having settled d_s, so the deep fits describe that lane and not the "
            "space; the base-block rungs are the unbiased ones."),
    }
