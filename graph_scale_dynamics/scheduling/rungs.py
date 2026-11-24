from __future__ import annotations

from copy import deepcopy

RUNG_EXTENSION_CONTRACT = "factor-four-memory-4"
DEFAULT_AGGREGATE_HEADROOM_FRACTION = 0.20
DEFAULT_FACTOR = 4


def rung_extension_config(spec: dict) -> dict:
    explicit = spec.get("rung_extension")
    raw = deepcopy(explicit or {})
    raw["contract"] = raw.get("contract") or RUNG_EXTENSION_CONTRACT
    raw.setdefault("enabled", bool(explicit and explicit.get("enabled", False)))
    raw.setdefault("factor", DEFAULT_FACTOR)
    raw.setdefault("hard_single_job_fraction_total", 0.60)
    stored_headroom = raw.get("headroom_fraction_total")
    if raw["contract"] == RUNG_EXTENSION_CONTRACT:
        requested_headroom = (DEFAULT_AGGREGATE_HEADROOM_FRACTION
                              if stored_headroom is None else float(stored_headroom))
        raw["headroom_fraction_total"] = max(
            DEFAULT_AGGREGATE_HEADROOM_FRACTION, requested_headroom
        )
    else:
        raw.setdefault("headroom_fraction_total", DEFAULT_AGGREGATE_HEADROOM_FRACTION)
    raw.setdefault("minimum_headroom_bytes", 2 * 1024 ** 3)
    raw.setdefault("simulation_fallback_bytes_per_node", 3750)
    raw.setdefault("simulation_base_bytes", 256 * 1024 ** 2)
    raw.setdefault("analysis_fallback_bytes_per_node", 2048)
    raw.setdefault("analysis_base_bytes", 768 * 1024 ** 2)
    raw.setdefault("process_intercept_floor_bytes", 896 * 1024 ** 2)
    raw.setdefault("prediction_safety_multiplier", 1.35)
    raw.setdefault("continue_confirmed_stress", True)
    return raw


def extension_enabled(spec: dict) -> bool:
    cfg = rung_extension_config(spec)
    return bool(cfg.get("enabled")) and int(cfg.get("factor", DEFAULT_FACTOR)) >= 2


def declared_ladder(spec: dict) -> list[int]:
    return sorted({int(n) for n in (spec.get("ladder") or []) if int(n) > 0})


def next_unmeasured_rung(spec: dict, measured: dict | set | list | tuple) -> int | None:
    measured_ns = {int(n) for n in (measured.keys() if isinstance(measured, dict) else measured)}
    ladder = declared_ladder(spec)
    for n in ladder:
        if n not in measured_ns:
            return n
    if not extension_enabled(spec) or not ladder:
        return None
    factor = int(rung_extension_config(spec)["factor"])
    latest = max([*ladder, *measured_ns] or ladder)
    return latest * factor


def stage_seed_count(spec: dict, n: int) -> int:
    ladder = declared_ladder(spec)
    n = int(n)
    if n in ladder:
        index = ladder.index(n)
        return int((spec.get("stage_seeds") or {}).get(str(index), spec.get("default_seeds", 2)))
    cfg = rung_extension_config(spec)
    return int(cfg.get("seeds_per_rung", spec.get("default_seeds", 2)))


def max_seed_attempts_for_rung(spec: dict, n: int) -> int:
    policy = spec.get("policy") or {}
    target_valid = max(1, int(policy.get("max_seeds_per_rung", stage_seed_count(spec, n))))
    return max(target_valid, int(policy.get("max_seed_attempts_per_rung", max(2, target_valid * 2))))
