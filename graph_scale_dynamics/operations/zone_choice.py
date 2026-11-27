from __future__ import annotations

from graph_scale_dynamics.operations import focus_regions as R
from graph_scale_dynamics.research import neighbourhood as N

CONTRACT = "gsd-zone-choice-1"
CONFIRMED, DENIED, UNMATCHED = "confirmed", "denied", "unmatched"
SHOWN = 5


def term_set(spec: dict) -> list[str]:
    return sorted(R.term_name(term) for term in (spec or {}).get("terms") or [])


def dynamics_of(spec: dict) -> str:
    return "zero temperature" if ((spec or {}).get("dynamics") or {}).get("zero_temperature") else "finite temperature"


def _centre(members: list[str], laws: dict[str, dict], radius: float) -> dict:
    far: dict[tuple[str, str], float] = {}
    for a in members:
        for b in members:
            if a < b:
                found = N.distance(laws[a]["spec"], laws[b]["spec"])
                far[(a, b)] = far[(b, a)] = float("inf") if found is None else float(found)

    def reading(law: str) -> dict:
        away = [far[(law, other)] for other in members if other != law]
        near = sorted(other for other in members if other != law and far[(law, other)] <= float(radius) + 1e-12)
        return {"law": law, "near": near, "mean": sum(away) / len(away) if away else 0.0,
                "widest": max(away) if away else 0.0}

    found = [reading(law) for law in members]
    found.sort(key=lambda r: (-len(r["near"]), r["mean"], -int(laws[r["law"]].get("score") or 0), r["law"]))
    return found[0]


def groups(laws: dict[str, dict], radius: float) -> list[dict]:
    by_signature: dict[tuple, list[str]] = {}
    for law in sorted(laws):
        entry = laws[law]
        if entry.get("verdict") != CONFIRMED or entry.get("control"):
            continue
        by_signature.setdefault(N.signature(entry["spec"]), []).append(law)
    out = []
    for members in by_signature.values():
        centre = _centre(members, laws, radius)
        spec = laws[centre["law"]]["spec"]
        out.append({"centre": centre["law"], "code": laws[centre["law"]].get("code") or centre["law"][:10],
                    "terms": term_set(spec), "dynamics": dynamics_of(spec), "laws": len(members),
                    "members": members, "near": len(centre["near"]) + 1, "near_laws": [centre["law"]] + centre["near"],
                    "mean": round(centre["mean"], 6), "widest": round(centre["widest"], 6),
                    "best": max(int(laws[m].get("score") or 0) for m in members)})
    out.sort(key=lambda g: (-g["near"], -g["laws"], g["mean"], -g["best"], g["centre"]))
    return out


def counts(laws: dict[str, dict]) -> dict[str, int]:
    out = {CONFIRMED: 0, DENIED: 0, UNMATCHED: 0, "controls": 0, "laws": len(laws)}
    for entry in laws.values():
        if entry.get("verdict") in out:
            out[entry["verdict"]] += 1
        if entry.get("control"):
            out["controls"] += 1
    return out


def _said(group: dict, radius: float) -> str:
    return (f"{group['near']} verified law{'' if group['near'] == 1 else 's'} within {radius:g} of {group['code']} "
            f"({group['laws']} of its term set: {', '.join(group['terms'])}, {group['dynamics']})")


def first(laws: dict[str, dict], *, radius: float) -> dict:
    found = groups(laws, radius)
    tally = counts(laws)
    zone = next((g for g in found if g["near"] >= 2), None)
    if zone is None:
        return {"contract": CONTRACT, "radius": float(radius), "chosen": None, "counts": tally,
                "groups": found[:SHOWN],
                "why": (f"no two verified laws of one term set lie within {radius:g} of each other "
                        f"({tally[CONFIRMED]} confirmed of {tally['laws']}): no zone to choose, the focus takes the "
                        "best free scoring law as before")}
    rest = [g for g in found if g is not zone]
    why = (f"the most verified laws of one term set nearest one centre: {_said(zone, radius)}, "
           f"mean distance {zone['mean']:.3f}, widest {zone['widest']:.3f}")
    if rest:
        why += f"; the next, {_said(rest[0], radius)}"
    if tally["controls"]:
        why += f"; {tally['controls']} standing control{'' if tally['controls'] == 1 else 's'} never chosen"
    return {"contract": CONTRACT, "radius": float(radius), "chosen": zone, "counts": tally, "groups": found[:SHOWN],
            "why": why}


__all__ = ["CONFIRMED", "CONTRACT", "DENIED", "UNMATCHED", "counts", "dynamics_of", "first", "groups", "term_set"]
