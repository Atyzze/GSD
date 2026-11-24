from __future__ import annotations

from collections import Counter
from typing import Iterable

from graph_scale_dynamics.research.hamiltonian_preflight import preflight_assessment
from graph_scale_dynamics.research.proposal_intelligence import (
    candidate_family, coefficient_region, scaling_profile,
)

FAMILY_MEMORY_VERSION = "family-memory-3"

POSITIVE_STATES = frozenset({
    "PROMOTED", "ROBUSTNESS_ACTIVE", "HOLDOUT_READY", "HOLDOUT_RUNNING",
    "CONFIRMED_CANDIDATE",
})

def decision_phenotype(decision: dict | None, state: str) -> str:
    if decision and decision.get("rule"):
        return f"engine:{decision.get('action') or 'unknown'}:{decision['rule']}"
    if state.startswith("REJECTED"):
        return "terminal:" + state.lower()
    return state.lower()


def _outcome_bucket(state: str) -> str:
    if state.startswith("REJECTED") or state == "PARKED":
        return "reject"
    if state in POSITIVE_STATES:
        return "positive"
    if state in {"PROPOSED", "REJECTED_STATIC", "QUARANTINE"}:
        return "other"
    return "active"


def build_family_memory(candidates: Iterable[dict], decisions_by_candidate: dict[str, dict],
                        config: dict | None = None) -> dict[str, dict]:
    cfg = {
        "exhaustion_min_candidates": 6,
        "exhaustion_reject_rate": 0.80,
        "dominant_phenotype_fraction": 0.65,
        "saturation_min_candidates": 12,
        "saturation_reject_rate": 0.90,
        "coefficient_region_min_candidates": 4,
        "coefficient_region_reject_rate": 0.90,
        "recent_window": 64,
        "recent_family_share_soft_cap": 0.20,
        "exploration_floor": 0.08,
        "unseen_region_boost": 1.35,
    } | (config or {})
    ordered = sorted(list(candidates), key=lambda row: str(row.get("created_utc") or ""))
    recent_window = max(1, int(cfg["recent_window"]))
    recent_ids = {row.get("candidate_id") for row in ordered[-recent_window:]}
    recent_total = max(1, min(recent_window, len(ordered)))
    families: dict[str, dict] = {}
    for candidate in ordered:
        family_id, family_label = candidate_family(candidate["spec"])
        region_id, region_label = coefficient_region(candidate["spec"])
        row = families.setdefault(family_id, {
            "family_id": family_id, "family_label": family_label,
            "candidates": 0, "terminal_rejects": 0, "parked": 0,
            "positive": 0, "active": 0, "phenotypes": Counter(),
            "scaling_profiles": Counter(), "regions": {}, "recent_candidates": 0,
        })
        row["candidates"] += 1
        row["recent_candidates"] += int(candidate.get("candidate_id") in recent_ids)
        row["scaling_profiles"][scaling_profile(candidate["spec"])] += 1
        state = str(candidate["state"])
        latest = decisions_by_candidate.get(candidate["candidate_id"])
        row["phenotypes"][decision_phenotype(latest, state)] += 1
        bucket = _outcome_bucket(state)
        if state.startswith("REJECTED"):
            row["terminal_rejects"] += 1
        elif state == "PARKED":
            row["parked"] += 1
        elif bucket == "positive":
            row["positive"] += 1
        elif bucket == "active":
            row["active"] += 1
        region = row["regions"].setdefault(region_id, {
            "coefficient_region_id": region_id,
            "coefficient_region_label": region_label,
            "candidates": 0, "rejects": 0, "positive": 0, "active": 0,
        })
        region["candidates"] += 1
        region["rejects"] += int(bucket == "reject")
        region["positive"] += int(bucket == "positive")
        region["active"] += int(bucket == "active")

    for row in families.values():
        evaluated = max(1, row["terminal_rejects"] + row["parked"] + row["positive"])
        reject_rate = (row["terminal_rejects"] + row["parked"]) / evaluated
        dominant_name, dominant_count = row["phenotypes"].most_common(1)[0]
        dominant_fraction = dominant_count / max(1, row["candidates"])
        exhausted = (
            row["candidates"] >= int(cfg["exhaustion_min_candidates"])
            and reject_rate >= float(cfg["exhaustion_reject_rate"])
            and dominant_fraction >= float(cfg["dominant_phenotype_fraction"])
            and row["positive"] == 0
        )
        saturated = (
            row["candidates"] >= int(cfg["saturation_min_candidates"])
            and reject_rate >= float(cfg["saturation_reject_rate"])
            and row["positive"] == 0
        )
        if row["positive"]:
            category, base_weight = "promising", 2.0
        elif exhausted:
            category, base_weight = "exhausted", 0.12
        elif saturated:
            category, base_weight = "saturated", 0.25
        elif row["active"]:
            category, base_weight = "active", 1.25
        else:
            category, base_weight = "uncertain", 1.0
        recent_share = row["recent_candidates"] / recent_total
        cap = max(0.01, float(cfg["recent_family_share_soft_cap"]))
        crowding_multiplier = 1.0 if recent_share <= cap else max(0.25, cap / recent_share)
        allocation_weight = max(float(cfg["exploration_floor"]), base_weight * crowding_multiplier)
        for region in row["regions"].values():
            region_eval = max(1, region["rejects"] + region["positive"])
            region["reject_rate"] = region["rejects"] / region_eval
            region["saturated"] = (
                region["candidates"] >= int(cfg["coefficient_region_min_candidates"])
                and region["reject_rate"] >= float(cfg["coefficient_region_reject_rate"])
                and region["positive"] == 0
            )
        row.update({
            "reject_rate": reject_rate,
            "dominant_phenotype": dominant_name,
            "dominant_phenotype_fraction": dominant_fraction,
            "exhausted": exhausted, "saturated": saturated, "category": category,
            "recent_share": recent_share, "crowding_multiplier": crowding_multiplier,
            "allocation_weight": allocation_weight,
            "score": allocation_weight,
            "phenotypes": dict(row["phenotypes"]),
            "scaling_profiles": dict(row["scaling_profiles"]),
            "config": cfg,
        })
    return families


def proposal_assessment(spec: dict, family_memory: dict[str, dict],
                        config: dict | None = None) -> dict:
    cfg = {
        "exploration_floor": 0.08,
        "unseen_region_boost": 1.35,
        "saturated_region_multiplier": 0.25,
        "positive_region_multiplier": 1.75,
        "exploration_override_fraction": 1.0,
    } | (config or {})
    family_id, family_label = candidate_family(spec)
    region_id, region_label = coefficient_region(spec)
    profile = scaling_profile(spec)
    preflight = preflight_assessment(spec)
    preflight_multiplier = float(preflight.get("allocation_multiplier") or 1.0)
    memory = family_memory.get(family_id)
    if memory is None:
        weight = max(float(cfg["exploration_floor"]), 1.5 * preflight_multiplier)
        return {
            "version": FAMILY_MEMORY_VERSION, "family_id": family_id,
            "family_label": family_label, "coefficient_region_id": region_id,
            "coefficient_region_label": region_label, "scaling_profile": profile,
            "physical_equivalence_id": preflight["physical_equivalence_id"],
            "physical_classification": preflight["classification"],
            "preflight": preflight,
            "score": weight, "allocation_weight": weight, "category": "novel",
            "exhausted": False, "saturated": False, "region_saturated": False,
            "would_admit": True, "exploration_floor": float(cfg["exploration_floor"]),
            "reasons": ["structural Hamiltonian family is unseen", *preflight["warnings"]],
        }
    reasons = [
        f"family has {memory['candidates']} candidates",
        f"terminal/park rejection rate {memory['reject_rate']:.3f}",
        f"family category {memory['category']}",
        f"recent proposal share {memory['recent_share']:.3f}",
    ]
    weight = float(memory.get("allocation_weight", 1.0)) * preflight_multiplier
    reasons.extend(preflight["warnings"])
    region = (memory.get("regions") or {}).get(region_id)
    region_saturated = bool(region and region.get("saturated"))
    if region is None:
        weight *= float(cfg["unseen_region_boost"])
        reasons.append("coefficient neighbourhood is unseen inside this family")
    elif region.get("positive"):
        weight *= float(cfg["positive_region_multiplier"])
        reasons.append("coefficient neighbourhood has positive downstream evidence")
    elif region_saturated:
        weight *= float(cfg["saturated_region_multiplier"])
        reasons.append("coefficient neighbourhood repeatedly rejected; strongly downweighted")
    if memory.get("exhausted"):
        reasons.append("homogeneous family exhaustion detected; exploration floor retained")
    elif memory.get("saturated"):
        reasons.append("broad no-yield family saturation detected; new regions remain explorable")
    elif memory.get("positive"):
        reasons.append("family has positive downstream evidence")
    elif memory.get("active"):
        reasons.append("family still has active members")
    weight = max(float(cfg["exploration_floor"]), weight)
    return {
        "version": FAMILY_MEMORY_VERSION, "family_id": family_id,
        "family_label": family_label, "coefficient_region_id": region_id,
        "coefficient_region_label": region_label, "scaling_profile": profile,
        "physical_equivalence_id": preflight["physical_equivalence_id"],
        "physical_classification": preflight["classification"],
        "preflight": preflight,
        "score": weight, "allocation_weight": weight,
        "category": memory.get("category", "uncertain"),
        "exhausted": bool(memory.get("exhausted")),
        "saturated": bool(memory.get("saturated")),
        "region_saturated": region_saturated,
        "would_admit": True,
        "exploration_floor": float(cfg["exploration_floor"]),
        "reasons": reasons,
    }
