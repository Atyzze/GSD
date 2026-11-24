from __future__ import annotations

import hashlib
import random
from copy import deepcopy

CONTRACT = "gsd-perturb-1"
RADII = (1e-9, 1e-3, 1e-2, 1e-1)
PER_RADIUS = 4
SIGNIFICANT_FIGURES = 12
TRIES = 50
SHARES = ("locality", "swap")


def stream(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16))


def parameters(spec: dict) -> list[tuple]:
    out: list[tuple] = []
    for index, term in enumerate(spec.get("terms") or []):
        out.append(("terms", index, "c0"))
        if (term.get("coeff") or {}).get("scale") == "power":
            out.append(("terms", index, "p"))
    dynamics = spec.get("dynamics") or {}
    if not dynamics.get("zero_temperature"):
        out.append(("dynamics", "beta"))
    if float(dynamics.get("locality") or 0.0) > 0.0:
        out.append(("dynamics", "locality"))
    if float((dynamics.get("move_mix") or {}).get("swap") or 0.0) > 0.0:
        out.append(("dynamics", "swap"))
    return out


def value_of(spec: dict, path: tuple) -> float:
    if path[0] == "terms":
        return float(spec["terms"][path[1]]["coeff"][path[2]])
    if path[1] == "swap":
        return float(spec["dynamics"]["move_mix"]["swap"])
    return float(spec["dynamics"][path[1]])


def _set(spec: dict, path: tuple, value: float) -> None:
    if path[0] == "terms":
        spec["terms"][path[1]]["coeff"][path[2]] = value
    elif path[1] == "swap":
        rest = (1.0 - value) / 2.0
        spec["dynamics"]["move_mix"] = {"add": rest, "delete": rest, "swap": value}
    else:
        spec["dynamics"][path[1]] = value


def _round(value: float) -> float:
    return float(f"{value:.{SIGNIFICANT_FIGURES}g}")


def moved(value: float, radius: float, rng: random.Random, *, share: bool) -> float:
    size = float(radius) * rng.uniform(0.5, 1.0)
    sign = -1.0 if rng.random() < 0.5 else 1.0
    out = _round(value * (1.0 + sign * size))
    if share and not 0.0 < out < 1.0:
        out = _round(value * (1.0 - sign * size))
    return out


def label(path: tuple) -> str:
    return f"term {path[1] + 1} {path[2]}" if path[0] == "terms" else str(path[1])


def variant(spec: dict, radius: float, rng: random.Random) -> tuple[dict, list[dict]]:
    child = deepcopy(spec)
    changes = []
    for path in parameters(spec):
        was = value_of(spec, path)
        now = moved(was, radius, rng, share=path[-1] in SHARES)
        _set(child, path, now)
        changes.append({"parameter": label(path), "from": was, "to": now,
                        "relative": round((now - was) / was, 15) if was else None})
    return child, changes


def problem_of(spec: dict, *, complexity_budget: int, whitelist: list[str] | None) -> str | None:
    from graph_scale_dynamics.dsl.dsl import validate
    from graph_scale_dynamics.services.proposer.blind import SAMPLER_631, validity_problem
    problems = validate(spec, complexity_budget=complexity_budget, operator_whitelist=whitelist)
    if problems:
        return problems[0]
    return validity_problem(spec, complexity_budget=complexity_budget, sampler=SAMPLER_631)


def variants(spec: dict, holder: str, *, salt: str, complexity_budget: int, whitelist: list[str] | None,
             radii=RADII, per_radius: int = PER_RADIUS) -> list[dict]:
    from graph_scale_dynamics.dsl.dsl import fingerprint, normalize
    seen = {fingerprint(spec)}
    out = []
    for radius in radii:
        for index in range(int(per_radius)):
            refused = []
            for attempt in range(TRIES):
                child, changes = variant(spec, radius, stream(salt, holder, f"{radius:g}", index, attempt))
                problem = problem_of(child, complexity_budget=complexity_budget, whitelist=whitelist)
                identity = fingerprint(child)
                if problem is None and identity not in seen:
                    seen.add(identity)
                    out.append({"radius": float(radius), "index": index + 1, "spec": normalize(child),
                                "candidate_id": identity, "changes": changes, "refused": refused})
                    break
                refused.append(problem or "the same law again")
            else:
                raise ValueError(f"no valid variant {index + 1} of {holder[:10]} at radius {radius:g} in {TRIES} draws")
    return out


__all__ = ["CONTRACT", "PER_RADIUS", "RADII", "SIGNIFICANT_FIGURES", "label", "moved", "parameters", "problem_of",
           "stream", "value_of", "variant", "variants"]
