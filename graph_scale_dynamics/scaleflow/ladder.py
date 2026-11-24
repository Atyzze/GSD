from __future__ import annotations

import math

MIN_RUNGS_FOR_REJECTION = 3

SLOPE_SIGNIFICANCE = 2.0

POWER_LAW_MARGIN = 1.15


def _loglog_fit(xs: list[float], ys: list[float]) -> dict | None:
    pairs = [(math.log(x), math.log(y)) for x, y in zip(xs, ys)
             if x > 0 and y > 0 and math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    if sxx <= 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pairs) / sxx
    intercept = my - slope * mx
    residuals = [p[1] - (intercept + slope * p[0]) for p in pairs]
    dof = n - 2
    resid_var = sum(r * r for r in residuals) / dof if dof > 0 else 0.0
    return {
        "slope": slope,
        "slope_se": math.sqrt(resid_var / sxx) if sxx > 0 else float("inf"),
        "intercept": intercept,
        "points": n,
        "residual_rms": math.sqrt(sum(r * r for r in residuals) / n),
    }


def _linear_fit(xs: list[float], ys: list[float]) -> dict | None:
    pairs = [(x, y) for x, y in zip(xs, ys)
             if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    if sxx <= 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pairs) / sxx
    intercept = my - slope * mx
    residuals = [p[1] - (intercept + slope * p[0]) for p in pairs]
    return {"slope": slope, "intercept": intercept,
            "residual_rms": math.sqrt(sum(r * r for r in residuals) / n)}


def radius_scaling_dimension(rungs: list[dict], *,
                             significance: float = SLOPE_SIGNIFICANCE) -> dict:
    usable = [r for r in rungs
              if (r.get("component_size") or 0) > 0
              and (r.get("half_volume_radius") or 0) > 0]
    if len(usable) < MIN_RUNGS_FOR_REJECTION:
        return {
            "verdict": "insufficient_rungs",
            "rungs": len(usable),
            "required": MIN_RUNGS_FOR_REJECTION,
            "dimension": None,
            "reason": (f"{len(usable)} usable rungs; a scaling slope needs at "
                       f"least {MIN_RUNGS_FOR_REJECTION}"),
        }

    volumes = [float(r["component_size"]) for r in usable]
    radii = [float(r["half_volume_radius"]) for r in usable]
    fit = _loglog_fit(volumes, radii)
    if fit is None:
        return {"verdict": "insufficient_rungs", "rungs": len(usable),
                "required": MIN_RUNGS_FOR_REJECTION, "dimension": None,
                "reason": "component size does not vary across rungs"}

    slope, se = fit["slope"], fit["slope_se"]
    low = slope - significance * se
    high = slope + significance * se
    volume_growth = volumes[-1] / volumes[0]
    radius_growth = radii[-1] / radii[0]

    result = {
        "rungs": len(usable),
        "slope": slope,
        "slope_se": se,
        "slope_interval": [low, high],
        "volume_growth": volume_growth,
        "radius_growth": radius_growth,
        "residual_rms": fit["residual_rms"],
    }
    log_fit = _linear_fit([math.log(v) for v in volumes], radii)
    power_rms = fit["residual_rms"]
    log_rms = log_fit["residual_rms"] if log_fit else float("inf")
    scale = math.exp(sum(math.log(r) for r in radii) / len(radii))
    power_rms_radius = power_rms * scale
    result["power_law_rms"] = power_rms_radius
    result["logarithmic_rms"] = log_rms
    result["logarithmic_wins"] = bool(log_rms < power_rms_radius)

    ratio = (log_rms / power_rms_radius) if power_rms_radius > 0 else float("inf")
    result["fit_ratio"] = ratio

    if slope <= 0.0 or slope > 1.0:
        result.update({
            "verdict": "no_metric_structure",
            "dimension": None,
            "reason": (f"slope {slope:.4f} implies d = {(1.0 / slope) if slope > 0 else float('inf'):.2f}; "
                       f"radius grows {radius_growth:.2f}x over {volume_growth:.0f}x in volume, "
                       f"which no connected geometry does. A slope at or below zero means the "
                       f"component shrank as the graph grew and the two rungs are not measuring "
                       f"the same object; above one it is denser than a path."),
        })
        return result

    span_lo, span_hi = min(volumes), max(volumes)
    if span_hi > span_lo > 1.0:
        log_slope = math.log(math.log(span_hi) / math.log(span_lo)) / math.log(span_hi / span_lo)
        separation = abs(slope - log_slope) / se if se > 0 else float("inf")
        result["log_diameter_slope"] = log_slope
        result["log_diameter_separation_sigma"] = separation
        if separation < significance:
            result.update({
                "verdict": "no_metric_structure",
                "dimension": None,
                "reason": (f"slope {slope:.4f} +/- {se:.4f} is {separation:.2f} sigma "
                           f"from {log_slope:.4f}, the slope a bounded-diameter graph "
                           f"must produce over this volume range ({span_lo:.0f} to "
                           f"{span_hi:.0f}); indistinguishable from R ~ log V, so no "
                           f"dimension is reported. This ladder cannot resolve a "
                           f"dimension above about {1.0 / max(log_slope + significance * se, 1e-9):.0f}"),
            })
            return result

    if ratio < 1.0:
        result.update({
            "verdict": "no_metric_structure",
            "dimension": None,
            "reason": (f"half-volume radius is better described by a logarithm "
                       f"than by a power of component size (rms "
                       f"{log_rms:.4f} vs {power_rms_radius:.4f}); radius grows "
                       f"{radius_growth:.2f}x over {volume_growth:.0f}x in volume, "
                       f"so the graph has bounded diameter (small-world / "
                       f"expander) and no metric dimension"),
        })
        return result

    if ratio < POWER_LAW_MARGIN:
        result.update({
            "verdict": "undetermined",
            "dimension": None,
            "reason": (f"a power law and a logarithm describe the radius almost "
                       f"equally well (rms ratio {ratio:.2f}, need "
                       f"{POWER_LAW_MARGIN:.2f}); this ladder spans "
                       f"{volume_growth:.0f}x in volume, which is not enough to "
                       f"separate them. Another rung, not a verdict"),
        })
        return result

    if low <= 0.0:
        result.update({
            "verdict": "no_metric_structure",
            "dimension": None,
            "reason": (f"half-volume radius grows {radius_growth:.2f}x while the "
                       f"component grows {volume_growth:.0f}x; scaling slope "
                       f"{slope:.4f} +/- {se:.4f} is not distinguishable from "
                       f"zero, so the graph has bounded diameter "
                       f"(small-world / expander) and no metric dimension"),
        })
        return result
    result.update({
        "verdict": "metric",
        "dimension": 1.0 / slope,
        "dimension_interval": [1.0 / high, 1.0 / low],
        "reason": (f"radius grows {radius_growth:.2f}x over {volume_growth:.0f}x "
                   f"in component size; slope {slope:.4f} +/- {se:.4f} "
                   f"gives d = {1.0 / slope:.2f}"),
    })
    return result


