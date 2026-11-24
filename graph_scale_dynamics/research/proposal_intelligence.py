from __future__ import annotations

from collections import Counter
import hashlib
import json

from graph_scale_dynamics.research.hamiltonian_preflight import (
    equilibrium_coefficient_region, equilibrium_family, preflight_assessment,
)


SEARCH_SPACE_VERSION = "hamiltonian-search-2"
SCALING_PROFILES = ("unscaled", "mixed", "scaled")


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: object, length: int = 12) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()[:length]


def scaling_profile(spec: dict) -> str:
    scales = [str((term.get("coeff") or {}).get("scale") or "one")
              for term in (spec.get("terms") or [])]
    if not scales or all(scale == "one" for scale in scales):
        return "unscaled"
    if all(scale != "one" for scale in scales):
        return "scaled"
    return "mixed"


def scaling_signature(spec: dict) -> str:
    counts = Counter(str((term.get("coeff") or {}).get("scale") or "one")
                     for term in (spec.get("terms") or []))
    return "+".join(f"{name}:{counts[name]}" for name in sorted(counts)) or "one:0"


def operator_signature(spec: dict) -> str:
    terms = []
    for term in spec.get("terms") or []:
        terms.append({"op": term.get("op") or "unknown",
                      "params": term.get("params") or {}})
    terms.sort(key=_encoded)
    return _encoded(terms)


def candidate_family(spec: dict) -> tuple[str, str]:
    return equilibrium_family(spec)


def coefficient_region(spec: dict) -> tuple[str, str]:
    return equilibrium_coefficient_region(spec)


def proposal_coordinates(spec: dict) -> dict:
    family_id, family_label = candidate_family(spec)
    region_id, region_label = coefficient_region(spec)
    preflight = preflight_assessment(spec)
    return {
        "family_id": family_id,
        "family_label": family_label,
        "coefficient_region_id": region_id,
        "coefficient_region_label": region_label,
        "physical_equivalence_id": preflight["physical_equivalence_id"],
        "physical_classification": preflight["classification"],
        "preflight_allocation_multiplier": preflight["allocation_multiplier"],
        "preflight_warnings": preflight["warnings"],
        "scaling_profile": scaling_profile(spec),
        "scaling_signature": scaling_signature(spec),
        "operator_signature": operator_signature(spec),
        "term_count": len(spec.get("terms") or []),
    }
