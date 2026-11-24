from __future__ import annotations

import math
from copy import deepcopy

from graph_scale_dynamics.research import perturb as P

CONTRACT = "gsd-neighbourhood-1"
STEP = 0.1
HALVINGS = 4
MIN_DISTANCE = 1e-3
TOP = 10
FIGURES = 12


def signature(spec: dict) -> tuple:
    dynamics = (spec or {}).get("dynamics") or {}
    terms = tuple((term.get("op"), tuple(sorted((term.get("params") or {}).items())),
                   (term.get("coeff") or {}).get("scale"), "p" in (term.get("coeff") or {}))
                  for term in (spec or {}).get("terms") or [])
    return (terms, str(dynamics.get("kind")), bool(dynamics.get("zero_temperature")),
            str(dynamics.get("local_move") or ""), tuple(P.label(path) for path in P.parameters(spec or {})))


def values(spec: dict) -> list[float]:
    return [P.value_of(spec, path) for path in P.parameters(spec)]


def distance(a: dict, b: dict) -> float | None:
    if signature(a) != signature(b):
        return None
    pairs = list(zip(values(a), values(b), strict=True))
    if not pairs:
        return None
    return math.sqrt(sum(((x - y) / max(abs(x), abs(y), 1e-12)) ** 2 for x, y in pairs) / len(pairs))


def _round(value: float) -> float:
    return float(f"{value:.{FIGURES}g}")


def alone(spec: dict, step: float = STEP) -> list[dict]:
    out = []
    for path in P.parameters(spec):
        was = P.value_of(spec, path)
        for sign in (1.0, -1.0):
            now = _round(was * (1.0 + sign * float(step)))
            if path[-1] in P.SHARES and not 0.0 < now < 1.0:
                continue
            child = deepcopy(spec)
            P._set(child, path, now)
            out.append({"spec": child, "parameter": P.label(path), "step": sign * float(step), "from": was, "to": now})
    return out


def between(holder: dict, partner: dict, at: float) -> dict | None:
    if signature(holder) != signature(partner):
        return None
    child = deepcopy(holder)
    for path in P.parameters(holder):
        a, b = P.value_of(holder, path), P.value_of(partner, path)
        P._set(child, path, _round(a + float(at) * (b - a)))
    return child


def valid(spec: dict, *, complexity_budget: int, whitelist) -> str | None:
    return P.problem_of(spec, complexity_budget=complexity_budget, whitelist=whitelist)


def next_point(line: dict) -> float | None:
    if line.get("done") or int(line.get("halvings") or 0) >= int(line.get("most", HALVINGS)):
        return None
    return round((float(line["lo"]) + float(line["hi"])) / 2.0, 12)


def narrowed(line: dict, at: float, kind: str | None) -> dict:
    out = dict(line, halvings=int(line.get("halvings") or 0) + 1)
    if kind is None:
        return dict(out, done=True, why=f"the point at {at:g} read no kind")
    if kind == line["lo_kind"]:
        out["lo"] = float(at)
    else:
        out["hi"], out["hi_kind"] = float(at), kind
    if int(out["halvings"]) >= int(out.get("most", HALVINGS)):
        out["done"] = True
    return out


def nearest_of_another_kind(holder: dict, kind: str | None, others: list[dict]) -> dict | None:
    if kind is None:
        return None
    found = []
    for other in others:
        if other.get("kind_at_4096") in (None, kind):
            continue
        gap = distance(holder, other["spec"])
        if gap is not None and gap >= MIN_DISTANCE:
            found.append((gap, str(other["candidate_id"]), other))
    if not found:
        return None
    gap, _law, other = min(found, key=lambda item: (item[0], item[1]))
    return dict(other, distance=round(gap, 6))
