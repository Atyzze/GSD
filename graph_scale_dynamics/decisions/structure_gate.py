from __future__ import annotations

import math

GATE_CONTRACT = "structure-gate-1"
CHAINS = ("empty", "given")

FINITE = "finite dimension"
NOT_FINITE = "no finite dimension"
SPLIT = "chains disagree on structure"
UNDECIDABLE = "undecidable"

GIANT_BELOW_HALF = "giant_below_half"
TOO_FEW_RUNGS = "too_few_rungs"
GAP_UNREADABLE = "gap_unreadable"
OUTSIDE_GRAPH_RANGE = "outside_graph_range"
STRUCTURE_CHANGED = "structure_changed"
LOG_DIAMETER_UNKNOWN = "log_diameter_unknown"
LOG_DIAMETER_RAISED = "log_diameter_raised"
NO_CENSUS = "no_census"



def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _slope(points: list) -> float | None:
    points = [(float(x), float(y)) for x, y in points if _finite(x) and _finite(y) and x > 0 and y > 0]
    if len({x for x, _ in points}) < 2:
        return None
    lx = [math.log(x) for x, _ in points]
    ly = [math.log(y) for _, y in points]
    mx, my = sum(lx) / len(lx), sum(ly) / len(ly)
    sxx = sum((x - mx) ** 2 for x in lx)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(lx, ly, strict=True)) / sxx


def thresholds_of(policy) -> dict:
    return {"gap_exponent_at_most": float(policy.gap_exponent_at_most),
            "diameter_exponent_at_least": float(policy.diameter_exponent_at_least),
            "gap_window": tuple(int(n) for n in policy.gap_window),
            "diameter_window": tuple(int(n) for n in policy.diameter_window),
            "giant_fraction_at_least": float(policy.giant_fraction_at_least),
            "gap_exponent_at_least": float(policy.gap_exponent_at_least),
            "diameter_exponent_at_most": float(policy.diameter_exponent_at_most),
            "gap_opens_above": float(policy.gap_opens_above),
            "diameter_shrinks_below": float(policy.diameter_shrinks_below)}


def _mean(values: list) -> float | None:
    values = [float(v) for v in values if _finite(v)]
    return (sum(values) / len(values)) if values else None


def rung_structure(measurements: list[dict]) -> dict[int, dict]:
    from graph_scale_dynamics.measurements.analysis import select_best_runs

    rows = [m for m in measurements or []
            if not ((((m.get("metrics") or {}).get("health") or {}).get("sampler") or {}).get("sampler_audit"))]
    by_n: dict[int, list] = {}
    for m in select_best_runs(rows):
        by_n.setdefault(int(m["n"]), []).append(m.get("metrics") or {})
    from graph_scale_dynamics.domain import chain_list as CL
    out = {}
    for n in sorted(by_n):
        rung = {chain: _one_chain(n, [CL.of_chain(metrics.get("census"), chain) or {} for metrics in by_n[n]])
                for chain in CHAINS}
        rung[CL.GIVEN]["log_diameter"] = log_diameter_flags([CL.probes_of(m, CL.GIVEN) or {} for m in by_n[n]])
        more = sorted({name for metrics in by_n[n] for name in CL.chains_in(metrics.get("census"))
                       if name not in CHAINS})
        if more:
            rung["more_given"] = {
                name: dict(_one_chain(n, [CL.of_chain(metrics.get("census"), name) or {} for metrics in by_n[n]]),
                           log_diameter=log_diameter_flags([CL.probes_of(m, name) or {} for m in by_n[n]]))
                for name in more}
        rung["log_diameter"] = log_diameter_flags(by_n[n])
        out[n] = rung
    return out


def log_diameter_flags(readings: list[dict]) -> dict:
    flags = {"raised": 0, "false": 0, "unknown": 0, "not_measured": 0}
    for metrics in readings:
        if "log_diameter_flag" not in metrics:
            continue
        flag = metrics.get("log_diameter_flag")
        if flag is True:
            flags["raised"] += 1
        elif flag is False:
            flags["false"] += 1
        elif (metrics.get("log_diameter") or {}).get("basis") == "not measured":
            flags["not_measured"] += 1
        else:
            flags["unknown"] += 1
    return flags


def _one_chain(n: int, censuses: list[dict]) -> dict:
    giants, gaps, diameters, reasons = [], [], [], {}
    for census in censuses:
        if not census:
            continue
        component = census.get("largest_component") or {}
        giants.append((component.get("size") or 0) / max(1, n))
        gap = component.get("spectral_gap") or {}
        if _finite(gap.get("value")):
            gaps.append(gap["value"])
        elif gap.get("reason"):
            reasons[str(gap["reason"])] = reasons.get(str(gap["reason"]), 0) + 1
        diameters.append((component.get("diameter") or {}).get("lower_bound"))
    return {"seeds": len(giants), "giant": _mean(giants), "gap": _mean(gaps), "diameter": _mean(diameters),
            "gap_reason": (max(sorted(reasons), key=lambda r: reasons[r]) if reasons else None)}


def chain_rows(rungs, chain: str) -> list[dict]:
    rows = []
    for rung in rungs:
        s = ((getattr(rung, "structure", None) or {}).get(chain)) or {}
        if not s or not s.get("seeds"):
            continue
        rows.append({"n": int(rung.n), "seeds": int(s.get("seeds") or 0),
                     "spectral_gap": {"mean": s.get("gap")}, "diameter": {"mean": s.get("diameter")},
                     "measured_giant_fraction": {"mean": s.get("giant")},
                     "gap_reason": s.get("gap_reason")})
    return rows


def verdict(rows: list[dict], t: dict) -> dict:
    gap_lo, gap_hi = t["gap_window"]
    d_lo, d_hi = t["diameter_window"]
    floor = t.get("giant_fraction_at_least", 0.5)

    def giant(r) -> float:
        value = (r.get("measured_giant_fraction") or {}).get("mean")
        return 1.0 if value is None else float(value)

    def value(r, key):
        v = (r.get(key) or {}).get("mean")
        return float(v) if _finite(v) and float(v) > 0 else None

    usable = [r for r in rows if giant(r) >= floor]
    dropped = sorted(int(r["n"]) for r in rows if giant(r) < floor)
    gap_pts = [(r["n"] * giant(r), value(r, "spectral_gap")) for r in usable if gap_lo <= r["n"] <= gap_hi]
    diam_pts = [(r["n"] * giant(r), value(r, "diameter")) for r in usable if d_lo <= r["n"] <= d_hi]
    a_gap = _slope([p for p in gap_pts if p[1] is not None])
    a_diam = _slope([p for p in diam_pts if p[1] is not None])
    exponents = {"gap": a_gap, "gap_rungs": len([p for p in gap_pts if p[1] is not None]),
                 "diameter": a_diam, "diameter_rungs": len([p for p in diam_pts if p[1] is not None]),
                 "against": "the giant component's size", "rungs_below_giant_floor": dropped}
    out = {"exponents": exponents, "thresholds": {k: t[k] for k in ("gap_exponent_at_most",
                                                                    "diameter_exponent_at_least",
                                                                    "gap_window", "diameter_window")}}
    if a_gap is None or a_diam is None:
        missing = [name for name, v in (("the gap", a_gap), ("the diameter", a_diam)) if v is None]
        in_windows = [int(r["n"]) for r in rows if gap_lo <= r["n"] <= gap_hi or d_lo <= r["n"] <= d_hi]
        if dropped and any(n in dropped for n in in_windows) and len(usable) < len(rows):
            code = GIANT_BELOW_HALF
        elif a_gap is None and any(value(r, "spectral_gap") is None for r in usable if gap_lo <= r["n"] <= gap_hi) \
                and len([r for r in usable if gap_lo <= r["n"] <= gap_hi]) >= 2:
            code = GAP_UNREADABLE
        elif not rows:
            code = NO_CENSUS
        else:
            code = TOO_FEW_RUNGS
        return out | {"finite_dimension": None, "code": code,
                      "why": f"{' and '.join(missing)} {'need' if len(missing) > 1 else 'needs'} two rungs inside "
                             f"its window (gap {gap_lo:,} to {gap_hi:,}, diameter {d_lo:,} to {d_hi:,})"
                             + (f" with a giant component of at least {floor:.0%}; below it: "
                                + ", ".join(f"{n:,}" for n in dropped) if dropped else "")
                             + ("; the gap solver read no value at a rung in its window"
                                if code == GAP_UNREADABLE else "")}
    if a_diam > t["diameter_exponent_at_most"] or a_gap < t["gap_exponent_at_least"]:
        return out | {"finite_dimension": None, "code": OUTSIDE_GRAPH_RANGE,
                      "why": (f"gap exponent {a_gap:.3f} and diameter exponent {a_diam:.3f} are outside what a graph "
                              f"of fixed structure can do (a diameter exponent above {t['diameter_exponent_at_most']}, "
                              f"or a gap closing faster than a ring's, below {t['gap_exponent_at_least']}): the "
                              "structure changed between the rungs, so no exponent is read yet")}
    if a_gap > t["gap_opens_above"] or a_diam < t["diameter_shrinks_below"]:
        return out | {"finite_dimension": None, "code": STRUCTURE_CHANGED,
                      "why": (f"gap exponent {a_gap:+.3f} (a gap that opens as N grows, above "
                              f"{t['gap_opens_above']:+g}) or diameter exponent {a_diam:+.3f} (a diameter that "
                              f"shrinks, below {t['diameter_shrinks_below']:+g}): the structure changed between "
                              "the rungs")}
    closes = a_gap <= t["gap_exponent_at_most"]
    grows = a_diam >= t["diameter_exponent_at_least"]
    why = [f"gap exponent {a_gap:.3f} {'<=' if closes else '>'} {t['gap_exponent_at_most']}"
           + (" (closes as a power of N)" if closes else " (stays open or shuts as a logarithm)"),
           f"diameter exponent {a_diam:.3f} {'>=' if grows else '<'} {t['diameter_exponent_at_least']}"
           + (" (grows as a power of N)" if grows else " (grows as a logarithm or not at all)")]
    return out | {"finite_dimension": bool(closes and grows), "code": None,
                  "implied_spectral_dimension": (-2.0 / a_gap) if a_gap < 0 else None,
                  "implied_fractal_dimension": (1.0 / a_diam) if a_diam > 0 else None,
                  "why": "; ".join(why)}


def log_diameter_at(rungs) -> dict | None:
    top = rungs[-1] if rungs else None
    flags = ((getattr(top, "structure", None) or {}).get("log_diameter")) if top is not None else None
    return dict(flags) if flags else None


def read_chains(rungs, t: dict) -> dict:
    rungs = sorted(rungs, key=lambda r: r.n)
    chains = {chain: verdict(chain_rows(rungs, chain), t) for chain in CHAINS}
    flag = log_diameter_at(rungs)
    from_empty = chains["empty"]
    raised, unknown = (int((flag or {}).get("raised") or 0), int((flag or {}).get("unknown") or 0))
    if from_empty["finite_dimension"] is True and (raised or unknown):
        code, state, count = ((LOG_DIAMETER_RAISED, "raised", raised) if raised
                              else (LOG_DIAMETER_UNKNOWN, "unknown", unknown))
        chains["empty"] = dict(from_empty, finite_dimension=None, code=code,
                                 why=from_empty["why"] + f"; but the log-diameter flag is {state} on {count} "
                                                      f"seed(s) at N={rungs[-1].n}, and a {state} flag "
                                                      "does not pass")
    says = {chain: chains[chain]["finite_dimension"] for chain in CHAINS}
    codes = {c: chains[c]["code"] for c in CHAINS if chains[c]["finite_dimension"] is None}
    if says["empty"] is True and says["given"] is True:
        result = FINITE
    elif says["empty"] is False and says["given"] is False:
        result = NOT_FINITE
    elif None in says.values():
        result = UNDECIDABLE
    else:
        result = SPLIT
    return {"result": result, "chains": chains, "log_diameter": flag, "codes": codes,
            "no_giant_component": codes.get("empty") == GIANT_BELOW_HALF}


def has_census(rungs) -> bool:
    return any(chain_rows(rungs, chain) for chain in CHAINS)


def early_clear_case(rungs, policy, t: dict) -> dict:
    lo, hi = int(policy.gap_window[0]), int(policy.early_gate_at_n)
    windowed = dict(t, gap_window=(lo, hi), diameter_window=(lo, hi))
    chains = {chain: verdict(chain_rows([r for r in rungs if r.n <= hi], chain), windowed) for chain in CHAINS}

    def clear(reading) -> bool:
        e = reading.get("exponents") or {}
        return (reading.get("code") is None and e.get("gap") is not None and e.get("diameter") is not None
                and e["gap"] > float(policy.early_gap_exponent_above)
                and e["diameter"] < float(policy.early_diameter_exponent_below))

    return {"would_refuse": all(clear(chains[c]) for c in CHAINS),
            "chains": {c: {"exponents": chains[c].get("exponents"), "code": chains[c].get("code")} for c in CHAINS},
            "limits": {"gap_exponent_above": float(policy.early_gap_exponent_above),
                       "diameter_exponent_below": float(policy.early_diameter_exponent_below),
                       "window": [lo, hi]}}


def near_threshold(reading: dict, policy) -> bool:
    gap_limit, diameter_limit = float(policy.gap_exponent_at_most), float(policy.diameter_exponent_at_least)
    for chain in CHAINS:
        e = (((reading.get("chains") or {}).get(chain) or {}).get("exponents")) or {}
        gap, diameter = e.get("gap"), e.get("diameter")
        if gap is not None and abs(float(gap) - gap_limit) <= float(policy.gate_audit_gap_margin):
            return True
        if diameter is not None and abs(float(diameter) - diameter_limit) <= float(policy.gate_audit_diameter_margin):
            return True
    return False
