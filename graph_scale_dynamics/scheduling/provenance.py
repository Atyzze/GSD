from __future__ import annotations

from copy import deepcopy
from typing import Any

from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.scheduling.limits import declares_default_limits
from graph_scale_dynamics.scheduling.limits import limits as effective_limits
from graph_scale_dynamics.scheduling.rungs import rung_extension_config

CAMPAIGN_PROVENANCE_CONTRACT = "immutable-campaign-1"
SEARCH_POLICY_CONTRACT = "four-rung-breadth-1"
RESOURCE_POLICY_CONTRACT = "bounded-resource-selection-7"


def freeze_campaign_spec(spec: dict) -> dict:
    frozen = deepcopy(spec)
    mode = str(frozen.get("mode") or "finite")

    policy = frozen.setdefault("policy", {})
    convergence = policy.setdefault("convergence", {})
    if mode == "continuous":
        convergence.setdefault("min_rungs_for_fits", 5)
        convergence.setdefault("promotion_min_latest_connected_fraction", 0.65)
        convergence.setdefault("promotion_min_component_theta", 0.95)
        convergence.setdefault("promotion_max_recent_connected_drop", 0.25)
        policy.setdefault("cost_awareness", {
            "enabled": True,
            "max_next_action_core_seconds": 10_800,
            "max_candidate_core_seconds": 21_600,
            "min_utility_per_core_hour": 0.05,
        })

    auto_extend = bool((frozen.get("rung_extension") or {}).get("enabled"))
    if auto_extend:
        frozen["rung_extension"] = rung_extension_config(frozen)


    frozen.setdefault("resource_governor", {
        "enabled": True,
        "contract": "resource-governor-2",
        "headroom_fraction": 0.10,
        "max_temperature_celsius": 90.0,
        "step_hold_seconds": 6.0,
        "step_wait_seconds": 45.0,
        "runtime_adjust_seconds": 5.0,
        "interpretation": "operational concurrency calibration only; never scientific selection",
    })
    frozen["campaign_provenance_contract"] = CAMPAIGN_PROVENANCE_CONTRACT
    frozen["search_policy_contract"] = SEARCH_POLICY_CONTRACT
    frozen["resource_policy_contract"] = RESOURCE_POLICY_CONTRACT
    return frozen


def science_contract_payload(spec: dict) -> dict[str, Any]:
    policy = deepcopy(spec.get("policy") or {})
    policy.pop("cost_awareness", None)
    return {
        "analysis_version": spec.get("analysis_version"),
        "search_space_version": spec.get("search_space_version"),
        "operator_whitelist": spec.get("operator_whitelist"),
        "complexity_budget": spec.get("complexity_budget"),
        "scientific_policy": policy,
        "confirmation_science": {},
    }


POST_HASH_LIMIT_FIELDS = ("mean_degree_cap_armed_from_n",)


def search_policy_payload(spec: dict) -> dict[str, Any]:
    policy = deepcopy(spec.get("policy") or {})
    policy.pop("cost_awareness", None)
    payload = {
        "search_policy_contract": spec.get("search_policy_contract"),
        "mode": spec.get("mode"),
        "ladder": spec.get("ladder"),
        "stage_seeds": spec.get("stage_seeds"),
        "default_seeds": spec.get("default_seeds"),
        "prescreen": spec.get("prescreen"),
        "max_active_candidates": spec.get("max_active_candidates"),
        "proposer": spec.get("proposer"),
        "search_policy": spec.get("search_policy"),
        "policy": policy,
        "confirmation_selection": {},
    }
    depth = spec.get("depth_continuation")
    if depth is not None:
        payload["depth_continuation"] = depth

    if not declares_default_limits(spec):
        from graph_scale_dynamics.scheduling.limits import DEFAULT_LIMITS
        block = effective_limits(spec)
        payload["limits"] = {
            k: v for k, v in block.items()
            if k not in POST_HASH_LIMIT_FIELDS or v != DEFAULT_LIMITS.get(k)}

    extension_ladder = spec.get("extension_ladder")
    if extension_ladder:
        payload["extension_ladder"] = [int(n) for n in extension_ladder]
    return payload


def resource_policy_payload(spec: dict) -> dict[str, Any]:
    policy = spec.get("policy") or {}
    return {
        "resource_policy_contract": spec.get("resource_policy_contract"),
        "budgets": spec.get("budgets"),
        "runtime_budget": spec.get("runtime_budget"),
        "rung_extension": spec.get("rung_extension"),
        "cost_awareness": policy.get("cost_awareness"),
        "confirmation_cost_awareness": None,
        "confirmation_deep_extension": None,
        "resource_governor": spec.get("resource_governor"),
        "frontier_probe": None,
    }


def policy_hashes(spec: dict) -> dict[str, str]:
    return {
        "science_contract_hash": content_hash(science_contract_payload(spec)),
        "search_policy_hash": content_hash(search_policy_payload(spec)),
        "resource_policy_hash": content_hash(resource_policy_payload(spec)),
    }


def experiment_config_hash(spec: dict, search_seed: int) -> str:
    return content_hash({
        "contract": CAMPAIGN_PROVENANCE_CONTRACT,
        "spec": spec,
        "search_seed": int(search_seed),
    })


def provenance_mismatches(campaign: dict) -> list[str]:
    spec = campaign.get("spec") or {}
    expected = policy_hashes(spec)
    problems: list[str] = []
    for key, value in expected.items():
        stored = str(campaign.get(key) or "")
        if stored == value:
            continue
        problems.append(f"{key}: stored={stored or '<missing>'} derived={value}")

    stored_search_contract = str(spec.get("search_policy_contract") or "")
    if stored_search_contract != SEARCH_POLICY_CONTRACT:
        problems.append(
            "search_policy_contract: stored="
            f"{stored_search_contract or '<missing>'} runtime={SEARCH_POLICY_CONTRACT}"
        )
    stored_resource_contract = str(spec.get("resource_policy_contract") or "")
    if stored_resource_contract != RESOURCE_POLICY_CONTRACT:
        problems.append(
            "resource_policy_contract: stored="
            f"{stored_resource_contract or '<missing>'} runtime={RESOURCE_POLICY_CONTRACT}"
        )
    seed = campaign.get("search_seed")
    if seed is None:
        problems.append("search_seed is missing")
    else:
        experiment = experiment_config_hash(spec, int(seed))
        if str(campaign.get("experiment_config_hash") or "") != experiment:
            problems.append(
                "experiment_config_hash: stored="
                f"{campaign.get('experiment_config_hash') or '<missing>'} derived={experiment}"
            )
    return problems
