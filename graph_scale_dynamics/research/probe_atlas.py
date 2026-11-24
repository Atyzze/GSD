from __future__ import annotations

import math
import statistics
from collections import defaultdict

from graph_scale_dynamics.scaleflow.probes import PROBES

PROBE_ATLAS_CONTRACT = "gsd-probe-atlas-1"
ASYMPTOTE_RANGE_MARGIN = 0.5

TOLERANCES = (0.50, 0.25, 0.10, 0.05, 0.02)


def _finite(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _cells_by(table: dict) -> dict[tuple[str, str, int], list[dict]]:
    out: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for cell in (table.get("cells") or {}).values():
        family = str(cell.get("family") or "")
        n = cell.get("n")
        if not family or isinstance(n, bool) or not isinstance(n, int):
            continue
        for probe in PROBES:
            ch = ((cell.get("channels") or {}).get(probe)) or {}
            value = _finite(ch.get("value")) if ch.get("valid") else None
            if value is None:
                out[(family, probe, n)].append({"value": None, "se": None, "refused": True,
                                                "reason": ch.get("reason")})
            else:
                out[(family, probe, n)].append({"value": value, "se": _finite(ch.get("se")), "refused": False})
    return out


def build_probe_atlas(table: dict | None) -> dict:
    table = table or {}
    families = table.get("families") or {}
    measure = {name: meta for name, meta in families.items()
               if str((meta or {}).get("expectation") or "") == "MEASURE" and (meta or {}).get("theory")}
    refuse = {name: meta for name, meta in families.items()
              if str((meta or {}).get("expectation") or "") == "REFUSE"}
    cells = _cells_by(table)
    convergence = ((table.get("deviation") or {}).get("families")) or {}

    atlas: dict[str, dict] = {}
    for probe in PROBES:
        rows_by_n: dict[int, dict] = {}
        per_family: dict[str, dict] = {}
        for family, meta in sorted(measure.items()):
            theory = _finite((meta.get("theory") or {}).get(probe))
            if theory is None:
                continue
            fam_rows = []
            for (f, p, n), seeds in sorted(cells.items(), key=lambda kv: kv[0][2]):
                if f != family or p != probe:
                    continue
                valid = [s for s in seeds if not s["refused"]]
                if not valid:
                    fam_rows.append({"n": n, "refused": len(seeds), "measured": 0})
                    continue
                values = [s["value"] for s in valid]
                ses = [s["se"] for s in valid if s["se"] is not None]
                mean = statistics.fmean(values)
                spread = statistics.pstdev(values) if len(values) > 1 else 0.0
                row = {
                    "n": n, "measured": len(valid), "refused": len(seeds) - len(valid),
                    "mean": round(mean, 4), "spread": round(spread, 4),
                    "median_se": round(statistics.median(ses), 4) if ses else None,
                    "deviation": round(mean - theory, 4), "abs_deviation": round(abs(mean - theory), 4),
                    "error": round(abs(mean - theory) + spread, 4),
                }
                fam_rows.append(row)
                agg = rows_by_n.setdefault(n, {"n": n, "families": 0, "errors": [], "spreads": [], "abs_devs": []})
                agg["families"] += 1
                agg["errors"].append(row["error"]); agg["spreads"].append(spread); agg["abs_devs"].append(abs(mean - theory))
            conv = ((convergence.get(family) or {}).get("convergence") or {}).get(probe) or {}
            first_below = {f"{tol:g}": _from_n_onward([(r["n"], r["error"]) for r in fam_rows if r.get("error") is not None], tol)
                           for tol in TOLERANCES}
            per_family[family] = {
                "theory": theory, "why": meta.get("why"),
                "rungs": fam_rows,
                "verdict": conv.get("verdict"),
                **_guarded_asymptote(conv, fam_rows),
                "early_median_drift": conv.get("early_median_drift"),
                "late_median_drift": conv.get("late_median_drift"),
                "late_median_spread": conv.get("late_median_spread"),
                "trend": trend_of(conv),
                "at_the_top": at_the_top(conv),
                "observed_range": ([min(r["mean"] for r in fam_rows if "mean" in r),
                                    max(r["mean"] for r in fam_rows if "mean" in r)]
                                   if any("mean" in r for r in fam_rows) else None),
                "first_n_with_error_below": first_below,
                "approach": _approach(fam_rows, theory),
            }
        trust_by_n = []
        for n in sorted(rows_by_n):
            agg = rows_by_n[n]
            trust_by_n.append({
                "n": n, "families": agg["families"],
                "worst_error": round(max(agg["errors"]), 4),
                "median_error": round(statistics.median(agg["errors"]), 4),
                "median_spread": round(statistics.median(agg["spreads"]), 4),
                "median_abs_deviation": round(statistics.median(agg["abs_devs"]), 4),
            })
        first_below_all = {f"{tol:g}": _from_n_onward([(r["n"], r["worst_error"]) for r in trust_by_n], tol)
                           for tol in TOLERANCES}
        verdicts = {fam: v["verdict"] for fam, v in per_family.items()}
        trust = ("converges" if verdicts and all(v in ("IMPROVES_WITH_N", "FLAT_ACCURATE") for v in verdicts.values())
                 else "plateaus_on_some_families" if any(v == "PLATEAU_BIASED" for v in verdicts.values())
                 else "mixed")
        atlas[probe] = {
            "families": per_family,
            "trust_by_n": trust_by_n,
            "first_n_with_worst_error_below": first_below_all,
            "verdicts": verdicts,
            "high_n_trust": trust,
            "refusal_anchor": {
                fam: _refusal_summary(cells, fam, probe) for fam in refuse
            },
        }
    return {
        "contract": PROBE_ATLAS_CONTRACT,
        "tolerances": list(TOLERANCES),
        "measure_families": sorted(measure),
        "refuse_families": sorted(refuse),
        "probes": atlas,
        "structure_readings": _structure_readings(convergence),
        "structure_limits": _structure_limits(),
        "d_s_margins": _margin_bands(table),
        "reading": (
            "Per probe: error = |mean - theory| + seed spread at each N, per MEASURE family, and the "
            "worst error across families at each N. first_n_with_worst_error_below[t] is the smallest "
            "N at which every known geometry is measured within t; that N is the floor for a tolerance "
            "window of t on a campaign rung. high_n_trust says whether pushing N helps: a probe that "
            "plateaus on some family gives a precise wrong answer there and is not rescued by N."
        ),
    }


IMPROVES_BELOW = 0.6
WORSENS_ABOVE = 1.25


def trend_of(conv: dict) -> str | None:
    early, late = conv.get("early_median_drift"), conv.get("late_median_drift")
    if early is None or late is None:
        return None
    if late < IMPROVES_BELOW * early:
        return "improves with N"
    if late > WORSENS_ABOVE * early:
        return "worsens with N"
    return "steady"


def at_the_top(conv: dict) -> str | None:
    late, spread = conv.get("late_median_drift"), conv.get("late_median_spread")
    if late is None:
        return None
    if spread is not None and late <= spread:
        return "within its seeds' spread"
    if late < 0.0005:
        return "on the answer to 0.001"
    return f"off by {late:.3f}"


def _margin_bands(document: dict) -> dict:
    try:
        from graph_scale_dynamics.calibration import d_s_margin_bands
        return d_s_margin_bands(document)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _structure_limits() -> dict:
    try:
        from graph_scale_dynamics.calibration import structure_limits
        return structure_limits()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _structure_readings(families: dict) -> dict:
    try:
        from graph_scale_dynamics.research.structure_reading import calibration_readings
        return calibration_readings(families)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _from_n_onward(series: list[tuple[int, float]], tol: float) -> int | None:
    series = sorted(series)
    for i, (n, _err) in enumerate(series):
        if all(e <= tol for _, e in series[i:]):
            return n
    return None


def _approach(rows: list[dict], theory: float) -> str:
    devs = [r["deviation"] for r in rows if "deviation" in r]
    if len(devs) < 3:
        return "insufficient"
    late = devs[-3:]
    if all(d < 0 for d in late):
        return "from_below"
    if all(d > 0 for d in late):
        return "from_above"
    return "oscillating"


def _refusal_summary(cells, family: str, probe: str) -> dict:
    total = refused = confident = 0
    by_n = {}
    for (f, p, n), seeds in cells.items():
        if f != family or p != probe:
            continue
        r = sum(1 for s in seeds if s["refused"])
        total += len(seeds); refused += r; confident += len(seeds) - r
        by_n[str(n)] = {"refused": r, "confident": len(seeds) - r}
    return {"seeds": total, "refused": refused, "false_confidence": confident, "by_n": by_n}

def _guarded_asymptote(conv: dict, fam_rows: list[dict]) -> dict:
    asymptote = conv.get("asymptote")
    means = [r["mean"] for r in fam_rows if "mean" in r]
    out = {"asymptote": asymptote, "asymptote_gap": conv.get("asymptote_gap"),
           "omega": conv.get("omega"), "asymptote_refused": None}
    if asymptote is None or not means:
        return out
    low, high = min(means), max(means)
    margin = ASYMPTOTE_RANGE_MARGIN * max(high - low, 1e-9)
    if not (low - margin) <= float(asymptote) <= (high + margin):
        out["asymptote"] = None
        out["asymptote_gap"] = None
        out["asymptote_refused"] = {
            "value": round(float(asymptote), 4),
            "observed_range": [round(low, 4), round(high, 4)],
            "omega": conv.get("omega"),
            "reason": "the finite-size fit extrapolates outside the range of the "
                      "rungs it was fitted to, which makes it a fit artefact "
                      "rather than an asymptote; the flow is reported, the "
                      "limit is not",
        }
    return out
