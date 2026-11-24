from __future__ import annotations

import math

LIMITS_CONTRACT = "gsd-search-limits-1"

DEFAULT_LIMITS = {
    "contract": LIMITS_CONTRACT,
    "mean_degree_window": {"min": 0.0, "max": 16.0},
    "connectivity_floor": 0.90,
    "mean_degree_cap_armed_from_n": 0,
}

REFUSAL_ABOVE_WINDOW = "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
REFUSAL_BELOW_WINDOW = "REFUSED_MEAN_DEGREE_BELOW_WINDOW"


def _finite(value, default):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) else default


def limits(spec: dict) -> dict:
    raw = dict((spec or {}).get("limits") or {})
    window = dict(raw.get("mean_degree_window") or {})
    return {
        "contract": str(raw.get("contract") or LIMITS_CONTRACT),
        "mean_degree_window": {
            "min": _finite(window.get("min"), DEFAULT_LIMITS["mean_degree_window"]["min"]),
            "max": _finite(window.get("max"), DEFAULT_LIMITS["mean_degree_window"]["max"]),
        },
        "connectivity_floor": _finite(raw.get("connectivity_floor"),
                                      DEFAULT_LIMITS["connectivity_floor"]),
        "mean_degree_cap_armed_from_n": _finite(
            raw.get("mean_degree_cap_armed_from_n"),
            DEFAULT_LIMITS["mean_degree_cap_armed_from_n"]),
    }


def declares_default_limits(spec: dict) -> bool:
    return limits(spec) == limits({})


def mean_degree_window(spec: dict) -> tuple[float, float]:
    window = limits(spec)["mean_degree_window"]
    return float(window["min"]), float(window["max"])


def connectivity_floor(spec: dict) -> float:
    return float(limits(spec)["connectivity_floor"])


def mean_degree_cap_armed(spec: dict, n) -> bool:
    try:
        armed_from = float(limits(spec)["mean_degree_cap_armed_from_n"])
    except (TypeError, ValueError):
        return True
    if armed_from <= 0 or n is None:
        return True
    try:
        return float(n) >= armed_from
    except (TypeError, ValueError):
        return True


def work_budget(spec: dict, n=None) -> int:
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(spec)
    return int(policy.work_budget(int(n) if n is not None else int(policy.base_sizes[-1])))


def work_unit(spec: dict) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scaleflow.one_shot import WORK_UNIT_CONTRACT
    policy = Policy.from_spec(spec)
    return {"contract": WORK_UNIT_CONTRACT, "weights": policy.work_weights(),
            "seconds_a_unit": float(policy.seconds_a_unit)}


def estimated_seconds(spec: dict, n, units=None) -> float | None:
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(spec)
    if not policy.work_budgets or not policy.seconds_a_unit:
        return None
    value = policy.work_budget(int(n)) if units is None else units
    return float(value) * float(policy.seconds_a_unit)


def units_for_seconds(spec: dict, seconds: float) -> int:
    from graph_scale_dynamics.decisions.engine import Policy
    unit = float(Policy.from_spec(spec).seconds_a_unit)
    if unit <= 0:
        raise ValueError("engine.policy.seconds_a_unit is not set, so no budget can be written from seconds")
    return int(float(seconds) / unit)


def policy_problems(policy) -> list[str]:
    from graph_scale_dynamics.scaleflow.one_shot import WORK_PARTS
    problems = []
    bad = [int(n) for n, units in policy.work_budgets
           if isinstance(units, bool) or not isinstance(units, int) or units < 1]
    if bad:
        problems.append("engine.policy.work_budgets must give every rung a whole number of units of work, at least "
                        "1; not " + ", ".join(f"{n:,}" for n in bad))
    weights = dict(policy.work_unit)
    if set(weights) != set(WORK_PARTS) or any(isinstance(weights[name], bool) or not isinstance(weights[name], int)
                                             or weights[name] < 0 for name in weights):
        problems.append("engine.policy.work_unit weighs each of " + ", ".join(WORK_PARTS)
                        + " by a whole number of at least 0")
    if not isinstance(policy.seeds, int) or isinstance(policy.seeds, bool) or policy.seeds < 1:
        problems.append("engine.policy.seeds must be a whole number >= 1")
    share = _finite(policy.audit_fraction, None)
    if share is None or not 0.0 <= share <= 1.0:
        problems.append("engine.policy.audit_fraction must be a share in [0, 1]")
    batch = policy.learn_in_batches_of
    if isinstance(batch, bool) or not isinstance(batch, int) or batch < 1:
        problems.append("engine.policy.learn_in_batches_of must be a whole number of laws, at least 1")
    return problems


def validate_limits(spec: dict) -> list[str]:
    problems: list[str] = []
    raw = (spec or {}).get("limits")
    if raw is None:
        return ["limits block is required (mean_degree_window, connectivity_floor)"]
    if not isinstance(raw, dict):
        return ["limits must be an object"]
    window = raw.get("mean_degree_window")
    if not isinstance(window, dict):
        problems.append("limits.mean_degree_window must be an object with min and max")
    else:
        lo = _finite(window.get("min"), None)
        hi = _finite(window.get("max"), None)
        if lo is None or lo < 0:
            problems.append("limits.mean_degree_window.min must be a finite number >= 0")
        if hi is None or hi <= 0:
            problems.append("limits.mean_degree_window.max must be a finite number > 0")
        if lo is not None and hi is not None and lo >= hi:
            problems.append("limits.mean_degree_window.min must be below max")
    floor = _finite(raw.get("connectivity_floor"), None)
    if floor is None or not 0.0 < floor <= 1.0:
        problems.append("limits.connectivity_floor must be a number in (0, 1]")
    from graph_scale_dynamics.decisions.engine import Policy
    try:
        policy = Policy.from_spec(spec)
    except (TypeError, ValueError, KeyError) as exc:
        problems.append(f"engine.policy cannot be read by the engine: {exc}")
        return problems
    declared = {int(n) for n, _units in policy.work_budgets}
    missing = [int(n) for n in policy.ladder() if int(n) not in declared]
    if missing:
        problems.append("engine.policy.work_budgets has no budget for rung(s) "
                        + ", ".join(f"{n:,}" for n in missing) + " of the ladder; declare one for each")
    problems.extend(policy_problems(policy))
    return problems


def describe(spec: dict) -> str:
    from graph_scale_dynamics.decisions.engine import Policy
    eff = limits(spec)
    lo, hi = eff["mean_degree_window"]["min"], eff["mean_degree_window"]["max"]
    policy = Policy.from_spec(spec)
    budgets = ", ".join(f"N={n} {policy.work_budget(n):,}" for n in policy.ladder())
    return (f"search limits ({eff['contract']}): mean degree window [{lo:g}, {hi:g}] (cap enforced during "
            f"sampling, floor at rung end), connectivity floor {eff['connectivity_floor']:g}; a seed's simulation "
            f"ends between chunks when the next would not fit its rung's budget in units of work ({budgets}), "
            "its graphs read and its law decided as any other; no clock ends it.")
