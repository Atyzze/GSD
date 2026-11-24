from __future__ import annotations

BASE_BLOCK_CONTRACT = "rung-phenotype-3"

DEFAULT_BASE_SIZES = (64, 256, 1024, 4096, 16384)
MIN_BASE_RUNGS = 3
MIN_CONTINUATION_BASE_RUNGS = 1


def _min_rungs_for(spec: dict) -> int:
    return MIN_CONTINUATION_BASE_RUNGS if str((spec or {}).get("mode")) == "continuation" else MIN_BASE_RUNGS
SEARCH_POLICY_CONTRACT = "base-block-breadth-2"


MIN_MEASUREMENT_SEEDS = 3

MAX_MEASUREMENT_SEEDS = 8


def is_base_block_campaign(spec: dict) -> bool:
    block = (spec or {}).get("base_block") or {}
    return str(block.get("contract") or "") == BASE_BLOCK_CONTRACT


def measurement_seeds(spec: dict) -> int:
    block = (spec or {}).get("base_block") or {}
    try:
        seeds = int(block.get("measurement_seeds_per_size", MIN_MEASUREMENT_SEEDS))
    except (TypeError, ValueError):
        return MIN_MEASUREMENT_SEEDS
    return max(MIN_MEASUREMENT_SEEDS, min(seeds, MAX_MEASUREMENT_SEEDS))


LIVE_SIMULATE_STATUSES = frozenset({"queued", "leased"})
LIVE_ANALYSIS_STATUSES = frozenset({"queued", "leased"})


def snapshot_base_sizes(snapshot: dict) -> tuple[int, ...]:
    spec = ((snapshot or {}).get("campaign") or {}).get("spec") or {}
    try:
        sizes = tuple(base_sizes(spec))
    except ValueError:
        sizes = ()
    return sizes or DEFAULT_BASE_SIZES


def base_sizes(spec: dict) -> tuple[int, ...]:
    if not is_base_block_campaign(spec):
        return tuple()
    raw = (spec.get("base_block") or {}).get("sizes")
    if raw is None:
        return DEFAULT_BASE_SIZES
    sizes = tuple(int(n) for n in raw)
    floor = _min_rungs_for(spec)
    if len(sizes) < floor or list(sizes) != sorted(set(sizes)):
        raise ValueError(f"base_block.sizes must be at least {floor} strictly increasing rungs, got {sizes}")
    return sizes


STAGE_GATE = "stage_gate"
STAGE_GATE_CONTRACT = "base-block-stage-gate-1"


def validate_stage_gate(spec: dict) -> list[str]:
    block = (spec or {}).get("base_block") or {}
    raw = block.get(STAGE_GATE)
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["base_block.stage_gate must be an object"]
    problems: list[str] = []
    sizes = [int(n) for n in (block.get("sizes") or [])]
    values = {}
    for key in ("withhold_from_n", "until_verdict_at_n"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            problems.append(f"base_block.stage_gate.{key} must be a positive integer rung size")
        elif sizes and value not in sizes:
            problems.append(f"base_block.stage_gate.{key}={value} is not one of the base sizes {sizes}")
        else:
            values[key] = int(value)
    if len(values) == 2:
        if values["until_verdict_at_n"] >= values["withhold_from_n"]:
            problems.append("base_block.stage_gate.until_verdict_at_n must be below withhold_from_n: "
                            "a rung cannot wait for a verdict at or above itself")
        if sizes and values["withhold_from_n"] == sizes[0]:
            problems.append("base_block.stage_gate.withhold_from_n is the first rung; a law "
                            "with every rung withheld never starts")
    contract = raw.get("contract")
    if contract is not None and str(contract) != STAGE_GATE_CONTRACT:
        problems.append(f"base_block.stage_gate.contract must be {STAGE_GATE_CONTRACT}")
    return problems


def extension_sizes(spec: dict) -> tuple[int, ...]:
    if not is_base_block_campaign(spec):
        return tuple()
    raw = (spec or {}).get("extension_ladder")
    if not raw:
        return tuple()
    sizes = tuple(int(n) for n in raw)
    if list(sizes) != sorted(set(sizes)):
        raise ValueError(f"extension_ladder must be strictly increasing, got {sizes}")
    base = base_sizes(spec)
    if base and sizes[0] <= base[-1]:
        raise ValueError("extension_ladder must begin strictly above the base block")
    return sizes


def anchor_n(spec: dict) -> int | None:
    base = base_sizes(spec)
    return int(base[-1]) if base else None


def is_extension_rung(spec: dict, n) -> bool:
    anchor = anchor_n(spec)
    return anchor is not None and int(n) > anchor


def validate_base_block(spec: dict) -> list[str]:
    problems: list[str] = []
    block = spec.get("base_block")
    if not isinstance(block, dict):
        return ["base_block must be an object"]
    if str(block.get("contract") or "") != BASE_BLOCK_CONTRACT:
        problems.append(f"base_block.contract must be {BASE_BLOCK_CONTRACT}")
    raw = block.get("sizes")
    if not isinstance(raw, list) or not raw:
        problems.append("base_block.sizes must be a non-empty list")
        return problems
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in raw):
        problems.append("base_block.sizes must be positive integers")
        return problems
    sizes = [int(v) for v in raw]
    if sizes != sorted(set(sizes)):
        problems.append("base_block.sizes must be strictly increasing")
    floor = _min_rungs_for(spec)
    if len(sizes) < floor:
        problems.append(f"base_block.sizes needs at least {floor} rungs"
                        + (" (the score needs three differences)" if floor == MIN_BASE_RUNGS else ""))
    ladder = [int(v) for v in (spec.get("ladder") or []) if isinstance(v, int) and not isinstance(v, bool)]
    if ladder and ladder[:len(sizes)] != sizes:
        problems.append("base_block.sizes must be the leading prefix of the ladder")
    raw_extension = spec.get("extension_ladder")
    if raw_extension is None:
        if ladder and len(ladder) != len(sizes):
            problems.append("the ladder must be exactly the base block unless "
                            "extension_ladder declares the rungs above it")
    elif not isinstance(raw_extension, list) or not raw_extension:
        problems.append("extension_ladder must be a non-empty list when present")
    elif not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in raw_extension):
        problems.append("extension_ladder must be positive integers")
    else:
        extension = [int(v) for v in raw_extension]
        if extension != sorted(set(extension)):
            problems.append("extension_ladder must be strictly increasing")
        elif sizes and extension[0] <= sizes[-1]:
            problems.append("extension_ladder must begin strictly above the base block; "
                            "a rung at or below the anchor is survey work, not depth")
        if ladder and ladder != sizes + extension:
            problems.append("the ladder must be base_block.sizes followed by extension_ladder")
    seeds = block.get("measurement_seeds_per_size", 0) or 0
    if not isinstance(seeds, int) or isinstance(seeds, bool) or seeds < 1:
        problems.append("base_block.measurement_seeds_per_size must be a positive integer")
    elif seeds < MIN_MEASUREMENT_SEEDS:
        problems.append(
            f"base_block.measurement_seeds_per_size must be at least {MIN_MEASUREMENT_SEEDS}; "
            "with fewer there is no repeat to measure reproducibility from, so every "
            "convergence verdict rests on a within-run error bar measured as "
            "roughly eight times too small at the median")
    elif seeds > MAX_MEASUREMENT_SEEDS:
        problems.append(
            f"base_block.measurement_seeds_per_size must be at most {MAX_MEASUREMENT_SEEDS}; "
            "every extra seed multiplies the cost of every rung of every law")
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    if not bool(block.get("concurrent", False)) and not is_engine_campaign(spec):
        problems.append("base_block.concurrent must be true (every rung is admitted at once, "
                        "or held by base_block.stage_gate until a lower verdict lands)")
    problems.extend(validate_stage_gate(spec))
    return problems
