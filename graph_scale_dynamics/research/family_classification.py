from __future__ import annotations

import math

from graph_scale_dynamics.measurements.calibration import (
    CALIBRATION_FAMILIES, ladder_tolerance)

CLASSIFICATION_CONTRACT = "gsd-family-classification-1"

PROBES = ("d_s", "d_V", "d_B", "d_w")

MIN_COMPARABLE_PROBES = 2

MATCH_DISTANCE = 1.0
CONSISTENT_DISTANCE = 2.0

DEFAULT_TOLERANCE = 0.45


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _families() -> tuple[dict, ...]:
    return CALIBRATION_FAMILIES


def _distance(law_probes: dict, family_name: str, theory: dict, n: int,
              anchors: dict | None = None) -> tuple[float | None, int, dict]:
    from graph_scale_dynamics.research.measured_anchors import anchor_at, anchor_distance

    terms: dict[str, dict] = {}
    total = 0.0
    used = 0
    for probe in PROBES:
        expected = _finite(theory.get(probe))
        measured = _finite(law_probes.get(probe))
        if expected is None or measured is None:
            continue
        tolerance = ladder_tolerance(family_name, probe, n) or DEFAULT_TOLERANCE
        theory_gap = abs(measured - expected) / tolerance
        term = {"measured": round(measured, 4), "theory": round(expected, 4),
                "tolerance": tolerance, "distance_to_theory": round(theory_gap, 3)}
        anchor = anchor_at(anchors, family_name, n, probe) if anchors else None
        if anchor:
            gap = anchor_distance(measured, anchor)
            term.update({"anchor_mean": anchor["mean"], "anchor_spread": anchor["spread"],
                         "anchor_n": anchor["n"], "distance_to_anchor": round(gap, 3),
                         "basis": "measured"})
        elif anchors:
            terms[probe] = {**term, "basis": "unmeasured_at_rung", "distance": None}
            continue
        else:
            gap = theory_gap
            term["basis"] = "theory"
        term["distance"] = round(gap, 3)
        terms[probe] = term
        total += gap
        used += 1
    if used < MIN_COMPARABLE_PROBES:
        return None, used, terms
    return total / used, used, terms


def classify_law(probe_values: dict, *, n: int, mean_degree=None,
                 refused_probes: tuple[str, ...] = (), anchors: dict | None = None) -> dict:
    size = int(n)
    ranked = []
    for family in _families():
        theory = dict(family.get("theory") or {})
        name = family["name"]
        if family.get("expectation") == "REFUSE":
            gated = dict(family.get("refusal_gated_from") or {})
            comparable = [p for p in PROBES if p in gated and size >= gated[p]]
            if not comparable:
                continue
            agree = sum(1 for p in comparable if p in refused_probes)
            ranked.append({
                "family": name, "expectation": "REFUSE",
                "match": "refusal_pattern",
                "refusal_agreement": round(agree / len(comparable), 3),
                "probes_compared": len(comparable),
                "distance": None,
                "why": family.get("why"),
            })
            continue
        distance, used, terms = _distance(probe_values, name, theory, size, anchors)
        if distance is None:
            continue
        ranked.append({
            "family": name, "expectation": "MEASURE",
            "match": ("match" if distance <= MATCH_DISTANCE else
                      "consistent" if distance <= CONSISTENT_DISTANCE else "far"),
            "distance": round(distance, 3),
            "probes_compared": used,
            "per_probe": terms,
            "why": family.get("why"),
        })
    measured = [r for r in ranked if r["expectation"] == "MEASURE"]
    refusing = [r for r in ranked if r["expectation"] == "REFUSE"]
    measured.sort(key=lambda r: (r["distance"] / max(1, r["probes_compared"]) ** 0.5,
                                 -r["probes_compared"]))
    refusing.sort(key=lambda r: -r["refusal_agreement"])
    best = measured[0] if measured and measured[0]["match"] in ("match", "consistent") else None
    best_refusal = refusing[0] if refusing and refusing[0]["refusal_agreement"] >= 0.75 else None
    return {
        "contract": CLASSIFICATION_CONTRACT,
        "n": size,
        "basis": "measured" if anchors else "theory",
        "nearest_geometry": best,
        "nearest_refusal_family": best_refusal,
        "verdict": (
            "resembles " + best["family"] if best and best["match"] == "match" else
            "consistent with " + best["family"] if best else
            "refuses like " + best_refusal["family"] if best_refusal else
            "resembles nothing in the calibration table"),
        "geometries": measured,
        "refusal_families": refusing,
        "reading": (
            "Distances are in units of the family's own measured tolerance band at "
            "this N, so a distance of 1 means 'as far from theory as the instrument "
            "is already known to be on this family'. Reporting only; nothing gates "
            "on this."),
    }


def family_separations(n: int) -> dict:
    measured = [f for f in CALIBRATION_FAMILIES if f.get("theory")]
    pairs = []
    for i, left in enumerate(measured):
        for right in measured[i + 1:]:
            shared = [p for p in PROBES
                      if _finite(left["theory"].get(p)) is not None
                      and _finite(right["theory"].get(p)) is not None]
            if not shared:
                continue
            gaps = {}
            for probe in shared:
                gap = abs(float(left["theory"][probe]) - float(right["theory"][probe]))
                tolerance = (ladder_tolerance(left["name"], probe, n)
                             or ladder_tolerance(right["name"], probe, n))
                gaps[probe] = {
                    "gap": round(gap, 4),
                    "tolerance": tolerance,
                    "resolved": bool(tolerance is not None and gap > tolerance),
                }
            pairs.append({"a": left["name"], "b": right["name"], "per_probe": gaps,
                          "resolved_on": sorted(p for p, g in gaps.items() if g["resolved"])})
    resolvable = [p for p in pairs if p["resolved_on"]]
    return {
        "n": int(n),
        "pairs_compared": len(pairs),
        "pairs_the_instrument_can_separate": len(resolvable),
        "unresolved_pairs": [{"a": p["a"], "b": p["b"]} for p in pairs
                             if not p["resolved_on"]][:12],
        "reading": (
            f"at N={n} the instrument can tell apart {len(resolvable)} of "
            f"{len(pairs)} pairs of known objects on at least one probe. A placement "
            "is only as fine as this number: two families it cannot separate "
            "here bound how fine a distinction any law can support"),
    }
