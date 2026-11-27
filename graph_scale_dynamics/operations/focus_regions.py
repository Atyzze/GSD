from __future__ import annotations

from graph_scale_dynamics.domain.model import utc_now

PREFIX = "Z"


def term_name(term: dict) -> str:
    params = term.get("params") or {}
    coeff = term.get("coeff") or {}
    name = str(term["op"]) + "".join(f" {key}={float(params[key]):g}" for key in sorted(params))
    return name if str(coeff.get("scale") or "one") == "one" else f"{name} ({coeff['scale']})"


def axis_values(spec: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for term in (spec or {}).get("terms") or []:
        coeff = term.get("coeff") or {}
        name = term_name(term)
        out[f"coupling {name}"] = float(coeff.get("c0") or 0.0)
        if "p" in coeff:
            out[f"power {name}"] = float(coeff["p"])
    dynamics = (spec or {}).get("dynamics") or {}
    out["beta"] = float(dynamics.get("beta") or 0.0)
    out["locality"] = float(dynamics.get("locality") or 0.0)
    out["swap share"] = float((dynamics.get("move_mix") or {}).get("swap") or 0.0)
    out["zero temperature"] = 1.0 if dynamics.get("zero_temperature") else 0.0
    return out


def ranges(specs: list[dict]) -> dict[str, list[float]]:
    values = [axis_values(spec) for spec in specs]
    axes = sorted(set().union(*values)) if values else []
    return {axis: [min(v.get(axis, 0.0) for v in values), max(v.get(axis, 0.0) for v in values)] for axis in axes}


def joined(a: dict, b: dict) -> dict[str, list[float]]:
    zero = [0.0, 0.0]
    return {axis: [min(a.get(axis, zero)[0], b.get(axis, zero)[0]), max(a.get(axis, zero)[1], b.get(axis, zero)[1])]
            for axis in sorted(set(a) | set(b))}


def overlap(a: dict, b: dict) -> bool:
    zero = [0.0, 0.0]
    for axis in set(a) | set(b):
        lo_a, hi_a = a.get(axis, zero)
        lo_b, hi_b = b.get(axis, zero)
        if hi_a < lo_b or hi_b < lo_a:
            return False
    return True


def place(state: dict, entry: dict, specs: list[dict]) -> dict:
    regions = state.setdefault("regions", [])
    places = state.setdefault("region_of", {})
    found = ranges(specs)
    for region in regions:
        if region["kind"] == entry.get("kind") and overlap(region["ranges"], found):
            region["ranges"] = joined(region["ranges"], found)
            region["laws"].append(entry["law"])
            region["labels"].append(entry.get("label"))
            region["members"] += len(specs)
            region["boundaries"] += list((entry.get("boundaries") or {}).values())
            region["joined"].append({"label": entry.get("label"), "at": utc_now()})
            places[entry["law"]] = region["number"]
            return region
    number = int(state.get("region_count") or 0) + 1
    state["region_count"] = number
    region = {"number": number, "name": f"{PREFIX}{number}", "kind": entry.get("kind"), "laws": [entry["law"]],
              "labels": [entry.get("label")], "members": len(specs), "ranges": found,
              "alike_to": entry.get("alike_to"), "confirmed_at": entry.get("confirmed_at"),
              "boundaries": list((entry.get("boundaries") or {}).values()),
              "joined": [], "mapped_utc": utc_now()}
    regions.append(region)
    places[entry["law"]] = number
    return region


def name_of(state: dict, law: str) -> str | None:
    number = (state.get("region_of") or {}).get(law)
    return None if number is None else f"{PREFIX}{number}"


def touching(regions: list[dict]) -> list[dict]:
    out = []
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            if a["kind"] != b["kind"] and overlap(a["ranges"], b["ranges"]):
                out.append({"regions": [a["name"], b["name"]], "kinds": [a["kind"], b["kind"]]})
    return out
