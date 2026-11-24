from __future__ import annotations


def engine_ladder(spec: dict, *, base_sizes, deep_sizes, seeds: int, budgets: dict,
                  audit_fraction: float = 1.0) -> dict:
    base_sizes, deep_sizes = [int(n) for n in base_sizes], [int(n) for n in deep_sizes]
    ladder = base_sizes + deep_sizes
    policy = dict(((spec.get("engine") or {}).get("policy")) or {})
    policy.update(base_sizes=base_sizes, deep_sizes=deep_sizes, seeds=int(seeds), audit_fraction=float(audit_fraction),
                  work_budgets=[[n, int(budgets[n])] for n in ladder])
    spec["engine"] = dict(spec.get("engine") or {}, policy=policy)
    spec["ladder"] = ladder
    if deep_sizes:
        spec["extension_ladder"] = deep_sizes
    else:
        spec.pop("extension_ladder", None)
    policy_block = spec.get("policy") or {}
    if isinstance(policy_block.get("initial_sweeps_multiplier"), dict):
        policy_block["initial_sweeps_multiplier"] = {
            k: v for k, v in policy_block["initial_sweeps_multiplier"].items() if int(k) in ladder}
    convergence = policy_block.get("convergence") or {}
    if int(convergence.get("min_rungs_for_fits") or 0) > len(ladder):
        convergence["min_rungs_for_fits"] = len(ladder)
    if int(policy_block.get("equilibration_rejection_min_rungs") or 0) > len(ladder):
        policy_block["equilibration_rejection_min_rungs"] = len(ladder)
    spec["base_block"] = dict(spec.get("base_block") or {}, sizes=base_sizes, measurement_seeds_per_size=int(seeds))
    spec["default_seeds"] = int(seeds)
    spec["stage_seeds"] = {str(i): int(seeds) for i in range(len(ladder))}
    spec.setdefault("budgets", {})["max_n"] = ladder[-1]
    return spec
