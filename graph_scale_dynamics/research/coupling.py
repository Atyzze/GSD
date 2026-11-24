from __future__ import annotations

import math

from graph_scale_dynamics.dsl import dsl

REFERENCE_N = 16_384

COUPLING_STRATA = ("weak", "moderate", "strong", "extreme")

_STRATUM_BOUNDS: dict[str, tuple[float, float]] = {
    "weak": (0.02, 1.0),
    "moderate": (1.0, 10.0),
    "strong": (10.0, 200.0),
    "extreme": (200.0, 5_000.0),
}

DEFAULT_COUPLING_TARGETS: dict[str, float] = {
    "weak": 0.40,
    "moderate": 0.30,
    "strong": 0.20,
    "extreme": 0.10,
}

BETA_MIN = 0.05
BETA_MAX = 100.0
COEFFICIENT_BOUND = 1e3 * 0.98
COEFFICIENT_FLOOR = 1e-4


def term_strength(term: dict, beta: float, n: int = REFERENCE_N) -> float:
    try:
        return abs(float(beta) * float(dsl.coefficient(term, int(n))))
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0.0


def coupling_strength(spec: dict, n: int = REFERENCE_N) -> float:
    beta = float((spec.get("dynamics") or {}).get("beta", 1.0))
    strengths = [term_strength(term, beta, n) for term in (spec.get("terms") or [])]
    return max(strengths) if strengths else 0.0


def coupling_stratum(spec: dict, n: int = REFERENCE_N) -> str:
    return stratum_for_strength(coupling_strength(spec, n))


def stratum_for_strength(strength: float) -> str:
    value = abs(float(strength))
    if value < _STRATUM_BOUNDS["weak"][1]:
        return "weak"
    if value < _STRATUM_BOUNDS["moderate"][1]:
        return "moderate"
    if value < _STRATUM_BOUNDS["strong"][1]:
        return "strong"
    return "extreme"


def stratum_bounds(stratum: str) -> tuple[float, float]:
    return _STRATUM_BOUNDS.get(stratum, _STRATUM_BOUNDS["moderate"])


def sample_target_strength(rng, stratum: str) -> float:
    low, high = stratum_bounds(stratum)
    return math.exp(rng.uniform(math.log(low), math.log(high)))


def rescale_coupling(spec: dict, target_strength: float,
                     n: int = REFERENCE_N) -> dict:
    dynamics = spec.setdefault("dynamics", {})
    terms = spec.get("terms") or []
    if not terms:
        return spec
    current = coupling_strength(spec, n)
    if current <= 0.0 or not math.isfinite(current):
        return spec
    target = max(1e-6, float(target_strength))
    factor = target / current

    beta = float(dynamics.get("beta", 1.0))
    new_beta = min(BETA_MAX, max(BETA_MIN, beta * factor))
    residual = factor * beta / new_beta if new_beta > 0 else 1.0
    dynamics["beta"] = float(f"{new_beta:.6g}")

    if abs(residual - 1.0) > 1e-12:
        largest = max(abs(float(term["coeff"]["c0"])) for term in terms)
        cap = COEFFICIENT_BOUND / max(largest * residual, 1e-30)
        residual = residual * min(1.0, cap)
        for term in terms:
            scaled = float(term["coeff"]["c0"]) * residual
            if abs(scaled) < COEFFICIENT_FLOOR:
                scaled = math.copysign(COEFFICIENT_FLOOR, scaled or 1.0)
            term["coeff"]["c0"] = float(f"{scaled:.6g}")
    return spec


def sweeps_for_coupling(base_sweeps: int, strength: float) -> int:
    base = max(1, int(base_sweeps))
    if strength <= 1.0:
        return base
    factor = 1.0 + math.log10(min(strength, 1_000.0))
    return int(min(100_000, max(base, round(base * factor))))


def coverage(specs, n: int = REFERENCE_N) -> dict:
    counts = {stratum: 0 for stratum in COUPLING_STRATA}
    strengths: list[float] = []
    for spec in specs:
        strength = coupling_strength(spec, n)
        strengths.append(strength)
        counts[stratum_for_strength(strength)] += 1
    total = sum(counts.values())
    observed = sorted(value for value in strengths if value > 0)
    return {
        "reference_n": int(n),
        "total": total,
        "counts": counts,
        "fractions": {key: (value / total if total else 0.0)
                      for key, value in counts.items()},
        "unsampled_strata": [key for key, value in counts.items() if value == 0],
        "observed_strength": {
            "min": observed[0] if observed else None,
            "median": observed[len(observed) // 2] if observed else None,
            "max": observed[-1] if observed else None,
            "decades_spanned": (math.log10(observed[-1] / observed[0])
                                if len(observed) > 1 and observed[0] > 0 else 0.0),
        },
    }


def coupling_targets(spec: dict) -> dict[str, float]:
    raw = ((spec.get("proposer") or {}).get("coupling") or {}).get("targets")
    if not isinstance(raw, dict) or not raw:
        raw = DEFAULT_COUPLING_TARGETS
    targets = {stratum: max(0.0, float(raw.get(stratum, 0.0)))
               for stratum in COUPLING_STRATA}
    total = sum(targets.values())
    if total <= 0:
        return {stratum: 1.0 / len(COUPLING_STRATA) for stratum in COUPLING_STRATA}
    return {stratum: value / total for stratum, value in targets.items()}
