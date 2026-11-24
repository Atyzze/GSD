from __future__ import annotations

import math
from collections import Counter
from graph_scale_dynamics.research.refused_rungs import ladder_buckets, masked

LABEL = "PLATEAU_THEN_BREAK"
CONTRACT = "plateau-break-1"
FROM_N = 1024
MIN_SETTLED_STEPS = 2
SETTLE_SIGMAS = 2.0
BREAK_SIGMAS = 3.0


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def breaks(sizes, values, errors, mean_degrees=None) -> list[dict]:
    degrees = list(mean_degrees or [])
    points = []
    for i, n in enumerate(sizes or []):
        value = _number(values[i]) if i < len(values or []) else None
        error = _number(errors[i]) if i < len(errors or []) else None
        points.append((int(n), value, error, _number(degrees[i]) if i < len(degrees) else None))
    found, run = [], []
    for (n0, v0, e0, d0), (n1, v1, e1, d1) in zip(points, points[1:], strict=False):
        if n0 < FROM_N or None in (v0, v1, e0, e1):
            run = []
            continue
        sigma = math.hypot(e0, e1)
        z = abs(v1 - v0) / sigma if sigma > 0 else math.inf
        if z <= SETTLE_SIGMAS:
            run.append((n0, n1, v0, v1, d0, d1))
            continue
        if len(run) >= MIN_SETTLED_STEPS and z > BREAK_SIGMAS:
            held = [run[0][2]] + [step[3] for step in run]
            moved = [abs(b - a) / a for *_, a, b in run if a and b is not None]
            found.append({"plateau_from": run[0][0], "plateau_to": run[-1][1], "steps": len(run),
                          "plateau_value": round(sum(held) / len(held), 4),
                          "plateau_spread": round(max(held) - min(held), 4),
                          "break_at": n1, "from": round(v0, 4), "to": round(v1, 4), "jump": round(v1 - v0, 4),
                          "sigmas": round(z, 2), "direction": "up" if v1 > v0 else "down",
                          "mean_degree_step": (round((d1 - d0) / d0, 5) if d0 and d1 is not None else None),
                          "mean_degree_plateau_step_max": (round(max(moved), 5) if moved else None)})
        run = []
    return found


def reading(sizes, values, errors, mean_degrees=None) -> dict:
    found = breaks(sizes, values, errors, mean_degrees)
    return {"contract": CONTRACT, "label": LABEL if found else None, "breaks": found}


def toward(found: dict, implied_spectral_dimension) -> bool | None:
    implied = _number(implied_spectral_dimension)
    if implied is None:
        return None
    return (implied - float(found["plateau_value"])) * float(found["jump"]) > 0


def ladder(phenotype: dict) -> tuple[list, list, list, list]:
    base = [int(n) for n in (phenotype.get("base_sizes") or [])]
    extension = [int(n) for n in (phenotype.get("extension_sizes") or []) if not base or int(n) > base[-1]]
    cells = (phenotype.get("per_n") or {}, phenotype.get("extension_per_n") or {})

    def half(stored, rungs, cells, pick):
        column = list(stored or [])
        return column if len(column) == len(rungs) else [pick(cells.get(str(n)) or {}) for n in rungs]

    def probe(vector_key, ext_key, field):
        pick = (lambda cell: ((cell.get("probes") or {}).get("d_s") or {}).get(field))
        return (half((phenotype.get(vector_key) or {}).get("d_s"), base, cells[0], pick)
                + half((phenotype.get(ext_key) or {}).get("d_s"), extension, cells[1], pick))

    degree = (lambda cell: cell.get("mean_degree"))
    degrees = (half(phenotype.get("mean_degree_vector"), base, cells[0], degree)
               + half(phenotype.get("extension_mean_degree_vector"), extension, cells[1], degree))
    buckets = ladder_buckets(phenotype, "d_s", base, extension)
    return (base + extension, masked(probe("probe_vectors", "extension_probe_vectors", "value"), buckets),
            masked(probe("probe_se_vectors", "extension_probe_se_vectors", "se"), buckets), degrees)


def population(scored: list[dict]) -> dict:
    labeled = [r for r in scored if ((r.get("plateau_break") or {}).get("label"))]
    last = [(r["plateau_break"]["breaks"][-1]) for r in labeled]
    return {"laws": len(labeled), "by_break_rung": dict(sorted(Counter(str(b["break_at"]) for b in last).items(),
                                                               key=lambda kv: int(kv[0]))),
            "by_direction": dict(Counter(b["direction"] for b in last)),
            "rule": (f"d_s settled (within {SETTLE_SIGMAS:g} standard errors) for {MIN_SETTLED_STEPS}+ steps in a row "
                     f"from N={FROM_N:,}, then moved by more than {BREAK_SIGMAS:g}: marked, never gated")}


def record_section(phenotypes: list[dict], measurements: list[dict], limit: int = 50) -> dict:
    from graph_scale_dynamics.research.structure_reading import law_structure

    marked = []
    for item in phenotypes or []:
        found = breaks(*ladder(item.get("phenotype") or {}))
        if found:
            marked.append((str(item.get("candidate_id")), found))
    rows: dict[str, list] = {}
    wanted = {law for law, _ in marked}
    for row in measurements or []:
        if str(row.get("candidate_id")) in wanted:
            rows.setdefault(str(row.get("candidate_id")), []).append(row)
    laws, directions = [], Counter()
    for law, found in marked:
        implied = law_structure(rows.get(law) or []).get("implied_spectral_dimension") if rows.get(law) else None
        for one in found:
            one["toward_the_structure"] = toward(one, implied)
            directions[{True: "toward", False: "away", None: "no finite gap exponent"}[one["toward_the_structure"]]] += 1
        laws.append({"candidate_id": law, "implied_spectral_dimension": implied, "breaks": found})
    laws.sort(key=lambda r: (-max(b["steps"] for b in r["breaks"]), -max(b["break_at"] for b in r["breaks"])))
    return {"contract": CONTRACT, "laws_marked": len(laws),
            "by_break_rung": dict(sorted(Counter(str(b["break_at"]) for r in laws for b in r["breaks"]).items(),
                                         key=lambda kv: int(kv[0]))),
            "relative_to_the_structure": dict(directions), "laws": laws[:limit],
            "reading": ("a plateau of settled d_s steps from N=1,024 up, then a step of more than 3 standard errors; "
                        "toward the structure: the step went toward the spectral dimension the gap exponent of the chain from empty "
                        "implies. Marked, never gated (532's E)")}
