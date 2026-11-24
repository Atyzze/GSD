from __future__ import annotations

import math
from typing import Any

from graph_scale_dynamics.dsl.dsl import OPERATORS
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.domain.model import POLICY_RULE_VERSION
from graph_scale_dynamics.scheduling.term_selection import selection_problems
from graph_scale_dynamics.scheduling.rungs import RUNG_EXTENSION_CONTRACT, rung_extension_config


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and float(value) > 0)


def _fraction(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0)


def _nonnegative_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and float(value) >= 0)


def _target_weights(problems: list[str], value: Any, path: str, keys: set[str]) -> None:
    if not isinstance(value, dict) or not value:
        problems.append(f"{path} must be a non-empty object")
        return
    unknown = sorted(set(value) - keys)
    if unknown:
        problems.append(f"{path} contains unknown keys: {unknown}")
    numbers = [value.get(key, 0) for key in keys]
    if not all(_nonnegative_number(item) for item in numbers):
        problems.append(f"{path} values must be finite non-negative numbers")
    elif sum(float(item) for item in numbers) <= 0:
        problems.append(f"{path} must have positive total weight")


def _whitelist_problems(spec: dict, *, stored: bool) -> list[str]:
    whitelist = spec.get("operator_whitelist")
    if not isinstance(whitelist, list) or not whitelist:
        return ["operator_whitelist must be a non-empty list"]
    problems = []
    unknown = sorted(set(whitelist) - set(OPERATORS))
    if unknown:
        problems.append(f"operator_whitelist contains unknown operators: {unknown}")
    if len(whitelist) != len(set(whitelist)):
        problems.append("operator_whitelist must not contain duplicates")
    if not stored:
        problems.extend(selection_problems(spec))
    return problems


def _validate(spec: dict, *, stored: bool) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["campaign spec must be an object"]

    mode = spec.get("mode", "finite")
    if mode not in {"finite", "continuous"}:
        problems.append("mode must be finite or continuous")

    prescreen = spec.get("prescreen")
    if prescreen is not None:
        if not isinstance(prescreen, dict):
            problems.append("prescreen must be an object")
        else:
            if not isinstance(prescreen.get("admission_enabled"), bool):
                problems.append("prescreen.admission_enabled must be boolean")
            parallel = prescreen.get("parallel_candidates", 8)
            if not _positive_int(parallel):
                problems.append("prescreen.parallel_candidates must be a positive integer")
            short_circuit = prescreen.get("early_pilot_short_circuit", False)
            if not isinstance(short_circuit, bool):
                problems.append("prescreen.early_pilot_short_circuit must be boolean")

    runtime_budget = spec.get("runtime_budget")
    if runtime_budget is not None:
        if not isinstance(runtime_budget, dict):
            problems.append("runtime_budget must be an object")
        else:
            if runtime_budget.get("enforcement_contract") not in {None, "actual-spend-1"}:
                problems.append("runtime_budget.enforcement_contract must be actual-spend-1")
            rung_compute = runtime_budget.get("rung_compute")
            if rung_compute is not None:
                if not isinstance(rung_compute, dict):
                    problems.append("runtime_budget.rung_compute must be an object")
                else:
                    if rung_compute.get("contract") not in {None, "rung-simulation-core-1"}:
                        problems.append(
                            "runtime_budget.rung_compute.contract must be rung-simulation-core-1"
                        )
                    if "enabled" in rung_compute and not isinstance(rung_compute.get("enabled"), bool):
                        problems.append("runtime_budget.rung_compute.enabled must be boolean")
                    mapping = rung_compute.get("simulation_core_seconds_by_n")
                    if mapping is not None:
                        if not isinstance(mapping, dict) or not mapping:
                            problems.append(
                                "runtime_budget.rung_compute.simulation_core_seconds_by_n must be a non-empty object"
                            )
                        else:
                            for raw_n, seconds in mapping.items():
                                try:
                                    parsed_n = int(raw_n)
                                except (TypeError, ValueError):
                                    parsed_n = 0
                                if parsed_n <= 0 or str(parsed_n) != str(raw_n):
                                    problems.append(
                                        f"runtime_budget.rung_compute.simulation_core_seconds_by_n key {raw_n!r} must be a positive integer string"
                                    )
                                if not _positive_number(seconds):
                                    problems.append(
                                        f"runtime_budget.rung_compute.simulation_core_seconds_by_n[{raw_n!r}] must be positive"
                                    )
                    if ("max_extension_core_seconds" in rung_compute
                            and not _positive_number(rung_compute["max_extension_core_seconds"])):
                        problems.append(
                            "runtime_budget.rung_compute.max_extension_core_seconds must be positive"
                        )

    ladder = spec.get("ladder")
    if not isinstance(ladder, list) or not ladder:
        problems.append("ladder must be a non-empty list")
        ladder_values: list[int] = []
    else:
        ladder_values = []
        for index, value in enumerate(ladder):
            if not _positive_int(value):
                problems.append(f"ladder[{index}] must be a positive integer")
            else:
                ladder_values.append(int(value))
        if len(ladder_values) == len(ladder):
            if ladder_values != sorted(set(ladder_values)):
                problems.append("ladder must be strictly increasing with no duplicates")

    default_seeds = spec.get("default_seeds", 2)
    if not _positive_int(default_seeds):
        problems.append("default_seeds must be a positive integer")
    stage_seeds = spec.get("stage_seeds", {})
    if not isinstance(stage_seeds, dict):
        problems.append("stage_seeds must be an object keyed by ladder index")
    else:
        for key, value in stage_seeds.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                problems.append(f"stage_seeds key {key!r} must be an integer index")
                continue
            if str(index) != str(key) or index < 0 or (ladder_values and index >= len(ladder_values)):
                problems.append(f"stage_seeds key {key!r} is outside the ladder")
            if not _positive_int(value):
                problems.append(f"stage_seeds[{key!r}] must be a positive integer")

    budgets = spec.get("budgets")
    if not isinstance(budgets, dict):
        problems.append("budgets must be an object")
        budgets = {}
    extension = rung_extension_config(spec)
    extension_enabled = bool(extension.get("enabled"))
    max_n = budgets.get("max_n", max(ladder_values) if ladder_values else None)
    if not extension_enabled:
        if not _positive_int(max_n):
            problems.append("budgets.max_n must be a positive integer")
        elif ladder_values and max_n not in ladder_values:
            problems.append("budgets.max_n must be one of the declared ladder rungs")
    elif max_n is not None and not _positive_int(max_n):
        problems.append("budgets.max_n must be a positive integer")

    if extension_enabled:
        raw_extension = spec.get("rung_extension") or {}
        if raw_extension and raw_extension.get("contract", RUNG_EXTENSION_CONTRACT) != RUNG_EXTENSION_CONTRACT:
            problems.append(f"rung_extension.contract must be {RUNG_EXTENSION_CONTRACT}")
        factor = extension.get("factor")
        if not _positive_int(factor) or int(factor) < 2:
            problems.append("rung_extension.factor must be an integer >= 2")
        for key in ("hard_single_job_fraction_total", "headroom_fraction_total"):
            if not _fraction(extension.get(key)) or float(extension.get(key)) <= 0:
                problems.append(f"rung_extension.{key} must lie in (0,1]")
        for key in ("minimum_headroom_bytes", "simulation_fallback_bytes_per_node",
                    "analysis_fallback_bytes_per_node", "simulation_base_bytes", "analysis_base_bytes"):
            if not _positive_int(extension.get(key)):
                problems.append(f"rung_extension.{key} must be a positive integer")
        if not _positive_number(extension.get("prediction_safety_multiplier")):
            problems.append("rung_extension.prediction_safety_multiplier must be positive")
    if "wall_seconds" in budgets and budgets["wall_seconds"] is None:
        budgets = {key: value for key, value in budgets.items() if key != "wall_seconds"}
    if "wall_seconds" in budgets and not _positive_number(budgets["wall_seconds"]):
        problems.append("budgets.wall_seconds must be a positive finite number")

    problems.extend(_whitelist_problems(spec, stored=stored))
    if not _positive_int(spec.get("complexity_budget")):
        problems.append("complexity_budget must be a positive integer")
    if "max_active_candidates" in spec and not _positive_int(spec["max_active_candidates"]):
        problems.append("max_active_candidates must be a positive integer")

    analysis_version = spec.get("analysis_version")
    if analysis_version != ANALYSIS_VERSION:
        problems.append("analysis_version must be " + ANALYSIS_VERSION)

    policy = spec.get("policy")
    if not isinstance(policy, dict):
        problems.append("policy must be an object")
        policy = {}
    elif policy.get("rule_version") != POLICY_RULE_VERSION:
        problems.append(f"policy.rule_version must be {POLICY_RULE_VERSION}")
    if policy.get("rule_version") == POLICY_RULE_VERSION:
        from graph_scale_dynamics.scheduling.base_block import validate_base_block
        from graph_scale_dynamics.scheduling.limits import validate_limits
        problems.extend(validate_base_block(spec))
        problems.extend(validate_limits(spec))
        if not bool((spec.get("base_block") or {}).get("no_scientific_selection_until_terminal", False)):
            problems.append(f"{policy.get('rule_version')} requires base_block.no_scientific_selection_until_terminal")
    adaptive_seed_screening = policy.get("adaptive_seed_screening")
    if adaptive_seed_screening is not None:
        if not isinstance(adaptive_seed_screening, dict):
            problems.append("policy.adaptive_seed_screening must be an object")
        else:
            if not isinstance(adaptive_seed_screening.get("enabled"), bool):
                problems.append("policy.adaptive_seed_screening.enabled must be boolean")
            screen_rungs = adaptive_seed_screening.get("screen_rungs", 2)
            refinement_seeds = adaptive_seed_screening.get("refinement_seeds", 2)
            if not _positive_int(screen_rungs):
                problems.append("policy.adaptive_seed_screening.screen_rungs must be a positive integer")
            elif ladder_values and int(screen_rungs) > len(ladder_values):
                problems.append("policy.adaptive_seed_screening.screen_rungs exceeds the declared ladder")
            if not _positive_int(refinement_seeds):
                problems.append("policy.adaptive_seed_screening.refinement_seeds must be a positive integer")
            if (policy.get("rule_version") in {"policy-contract-14", "policy-contract-15"}
                    and _positive_int(refinement_seeds)):
                first_two = [int((spec.get("stage_seeds") or {}).get(str(i), spec.get("default_seeds", 2)))
                             for i in range(min(2, len(ladder_values)))]
                if first_two and any(seed_count != 1 for seed_count in first_two):
                    problems.append(f"{policy.get('rule_version')} requires one seed on each adaptive screening rung")
                if int(refinement_seeds) < 2:
                    problems.append(f"{policy.get('rule_version')} adaptive refinement_seeds must be at least 2")

    degeneracy_confirmation = policy.get("degeneracy_confirmation")
    if degeneracy_confirmation is not None:
        if not isinstance(degeneracy_confirmation, dict):
            problems.append("policy.degeneracy_confirmation must be an object")
        else:
            if not isinstance(degeneracy_confirmation.get("enabled"), bool):
                problems.append("policy.degeneracy_confirmation.enabled must be boolean")
            tolerance = degeneracy_confirmation.get("exact_tolerance", 1e-12)
            if (not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool)
                    or not math.isfinite(float(tolerance)) or float(tolerance) < 0):
                problems.append("policy.degeneracy_confirmation.exact_tolerance must be finite and >= 0")
            seeds = degeneracy_confirmation.get("confirmation_seeds", 1)
            if not _positive_int(seeds):
                problems.append("policy.degeneracy_confirmation.confirmation_seeds must be a positive integer")
    for key in ("min_connected_fraction", "max_density", "min_acceptance",
                "max_mean_degree_fraction"):
        if key in policy and not _fraction(policy[key]):
            problems.append(f"policy.{key} must lie in [0,1]")
    for key in ("min_effective_samples", "max_sweeps_multiplier", "max_seeds_per_rung",
                "equilibration_rejection_min_rungs"):
        if key in policy and not _positive_int(policy[key]):
            problems.append(f"policy.{key} must be a positive integer")
    initial = policy.get("initial_sweeps_multiplier")
    if initial is not None:
        cap_value = policy.get("max_sweeps_multiplier", 64)
        cap_known = _positive_int(cap_value)
        if _positive_int(initial):
            if cap_known and int(initial) > int(cap_value):
                problems.append("policy.initial_sweeps_multiplier exceeds max_sweeps_multiplier")
        elif isinstance(initial, dict):
            for rung_key, value in initial.items():
                if not str(rung_key).isdigit() or not _positive_int(value):
                    problems.append(
                        "policy.initial_sweeps_multiplier map entries must be "
                        "positive-integer N keys to positive-integer multipliers")
                elif cap_known and int(value) > int(cap_value):
                    problems.append(
                        f"policy.initial_sweeps_multiplier[{rung_key}] exceeds "
                        "max_sweeps_multiplier")
                elif ladder_values and int(rung_key) not in {int(x) for x in ladder_values}:
                    problems.append(
                        f"policy.initial_sweeps_multiplier[{rung_key}] names an N "
                        "outside the declared ladder")
        else:
            problems.append("policy.initial_sweeps_multiplier must be a positive "
                            "integer or a map of N to positive integers")
    eq_reject_rungs = policy.get("equilibration_rejection_min_rungs")
    if (_positive_int(eq_reject_rungs) and ladder_values
            and int(eq_reject_rungs) > len(ladder_values)):
        problems.append("policy.equilibration_rejection_min_rungs exceeds the declared ladder")

    convergence = policy.get("convergence", {})
    if not isinstance(convergence, dict):
        problems.append("policy.convergence must be an object")
        convergence = {}
    min_rungs = convergence.get("min_rungs_for_fits")
    usable_rungs = len(ladder_values)
    if min_rungs is not None:
        if not _positive_int(min_rungs):
            problems.append("policy.convergence.min_rungs_for_fits must be a positive integer")
        elif usable_rungs and min_rungs > usable_rungs:
            problems.append("policy.convergence.min_rungs_for_fits exceeds the declared ladder")

    cost_awareness = policy.get("cost_awareness", {})
    if not isinstance(cost_awareness, dict):
        problems.append("policy.cost_awareness must be an object")
    else:
        for key in ("max_next_action_core_seconds", "max_candidate_core_seconds",
                    "min_utility_per_core_hour"):
            if key in cost_awareness and not _positive_number(cost_awareness[key]):
                problems.append(f"policy.cost_awareness.{key} must be a positive finite number")
    for key in ("equilibration_connected_delta_max", "equilibration_two_core_delta_max",
                "equilibration_cycle_density_delta_max",
                "equilibration_component_count_delta_max"):
        if key in policy and not _fraction(policy[key]):
            problems.append(f"policy.{key} must lie in [0,1]")

    proposer = spec.get("proposer")
    search_policy = spec.get("search_policy")
    if isinstance(search_policy, dict) or (proposer is not None and mode in {"finite", "continuous"}):
        from graph_scale_dynamics.scheduling.search_policy import validate_search_policy
        problems.extend(validate_search_policy(spec))
    if proposer is not None:
        if not isinstance(proposer, dict):
            problems.append("proposer must be an object")
        else:
            if not _positive_int(proposer.get("pool_min", 1)):
                problems.append("proposer.pool_min must be a positive integer")
            weights = proposer.get("weights", {})
            from graph_scale_dynamics.scheduling.search_policy import kind_of
            declared = kind_of(spec)
            if declared is not None and not declared.steerable:
                pass
            elif not isinstance(weights, dict) or not weights:
                problems.append("proposer.weights must be a non-empty object")
            else:
                values = list(weights.values())
                if not all(_nonnegative_number(v) for v in values):
                    problems.append("proposer.weights must be finite non-negative numbers")
                elif sum(float(v) for v in values) <= 0:
                    problems.append("proposer.weights must have positive total weight")

            family = proposer.get("family_memory")
            if family is not None:
                if not isinstance(family, dict):
                    problems.append("proposer.family_memory must be an object")
                else:
                    if "mode" in family and family["mode"] not in {"off", "shadow", "active"}:
                        problems.append("proposer.family_memory.mode must be off, shadow, or active")
                    for key in ("exhaustion_min_candidates", "saturation_min_candidates",
                                "coefficient_region_min_candidates", "recent_window",
                                "candidate_pool_multiplier"):
                        if key in family and not _positive_int(family[key]):
                            problems.append(f"proposer.family_memory.{key} must be a positive integer")
                    for key in ("exhaustion_reject_rate", "dominant_phenotype_fraction",
                                "saturation_reject_rate", "coefficient_region_reject_rate",
                                "recent_family_share_soft_cap", "exploration_floor",
                                "exploration_override_fraction", "batch_family_decay",
                                "batch_region_decay"):
                        if key in family and not _fraction(family[key]):
                            problems.append(f"proposer.family_memory.{key} must lie in [0,1]")
                    for key in ("unseen_region_boost", "saturated_region_multiplier",
                                "positive_region_multiplier"):
                        if key in family and not _positive_number(family[key]):
                            problems.append(f"proposer.family_memory.{key} must be a positive finite number")

            cartography = proposer.get("cartography")
            if cartography is not None:
                if not isinstance(cartography, dict):
                    problems.append("proposer.cartography must be an object")
                else:
                    if not isinstance(cartography.get("enabled", False), bool):
                        problems.append("proposer.cartography.enabled must be boolean")
                    source_campaign_id = cartography.get("source_campaign_id")
                    if cartography.get("enabled", False) and (
                            not isinstance(source_campaign_id, str) or not source_campaign_id.strip()):
                        problems.append("enabled proposer.cartography requires source_campaign_id")
                    if cartography.get("metric", "d_s") != "d_s":
                        problems.append("proposer.cartography.metric currently supports only d_s")
                    checkpoint_n = cartography.get("checkpoint_n")
                    if checkpoint_n is not None and not _positive_int(checkpoint_n):
                        problems.append("proposer.cartography.checkpoint_n must be a positive integer or null")
                    for key in ("min_checkpoint_candidates", "pool_multiplier", "max_anchor_count",
                                "k_neighbors", "min_common_rungs", "resonance_max_candidates"):
                        if key in cartography and not _positive_int(cartography[key]):
                            problems.append(f"proposer.cartography.{key} must be a positive integer")
                    if "min_checkpoint_fraction" in cartography and not _fraction(cartography["min_checkpoint_fraction"]):
                        problems.append("proposer.cartography.min_checkpoint_fraction must lie in [0,1]")
                    for key in ("local_jitter_sigma", "edge_jitter_sigma"):
                        if key in cartography and not _positive_number(cartography[key]):
                            problems.append(f"proposer.cartography.{key} must be a positive finite number")
                    fractions = [cartography.get(key, default) for key, default in (
                        ("boundary_fraction", 0.60), ("flow_edge_fraction", 0.25),
                        ("resonance_fraction", 0.15))]
                    if not all(_fraction(value) for value in fractions):
                        problems.append("proposer.cartography probe fractions must each lie in [0,1]")
                    elif sum(float(value) for value in fractions) <= 0:
                        problems.append("proposer.cartography probe fractions must have positive total weight")

            operator_multipliers = proposer.get("operator_multipliers")
            if operator_multipliers is not None:
                if not isinstance(operator_multipliers, dict):
                    problems.append("proposer.operator_multipliers must be an object")
                elif not all(_positive_number(value) for value in operator_multipliers.values()):
                    problems.append("proposer.operator_multipliers values must be positive finite numbers")

            term_weights = proposer.get("term_count_weights")
            if term_weights is not None:
                if not isinstance(term_weights, dict):
                    problems.append("proposer.term_count_weights must be an object")
                elif term_weights:
                    parsed = []
                    for key, value in term_weights.items():
                        try:
                            count = int(key)
                        except (TypeError, ValueError):
                            count = 0
                        if str(count) != str(key) or count < 1:
                            problems.append(f"proposer.term_count_weights key {key!r} must be a positive integer string")
                        parsed.append(value)
                    if not all(_nonnegative_number(value) for value in parsed):
                        problems.append("proposer.term_count_weights values must be finite non-negative numbers")
                    elif sum(float(value) for value in parsed) <= 0:
                        problems.append("proposer.term_count_weights must have positive total weight")

            scaling_profiles = proposer.get("scaling_profiles")
            if scaling_profiles is not None:
                if not isinstance(scaling_profiles, dict):
                    problems.append("proposer.scaling_profiles must be an object")
                elif scaling_profiles.get("targets") not in (None, {}):
                    _target_weights(problems, scaling_profiles.get("targets"),
                                    "proposer.scaling_profiles.targets",
                                    {"unscaled", "mixed", "scaled"})

            coupling = proposer.get("coupling")
            if coupling is not None:
                if not isinstance(coupling, dict):
                    problems.append("proposer.coupling must be an object")
                elif coupling.get("targets") not in (None, {}):
                    _target_weights(problems, coupling.get("targets"),
                                    "proposer.coupling.targets",
                                    {"weak", "moderate", "strong", "extreme"})

    if mode == "continuous" and proposer is None:
        problems.append("continuous discovery requires a proposer configuration")
    return problems


def validate_campaign(spec: dict, *, stored: bool = False) -> list[str]:
    return _validate(spec, stored=stored)
