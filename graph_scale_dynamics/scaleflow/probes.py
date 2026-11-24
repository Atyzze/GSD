from __future__ import annotations

from enum import Enum

from graph_scale_dynamics.scaleflow.observables import (
    BOX_COVERING_EXPONENT,
    DISTANCE_VOLUME_EXPONENT,
    OBSERVABLE_ALIASES,
    SPECTRAL_DIMENSION,
    WALK_DIMENSION,
)

PROBE_VOCABULARY_CONTRACT = "gsd-probes-1"
A_VERDICT_IS_RELIED_ON_FROM_NODES = 4096

D_S = OBSERVABLE_ALIASES[SPECTRAL_DIMENSION]
D_V = OBSERVABLE_ALIASES[DISTANCE_VOLUME_EXPONENT]
D_B = OBSERVABLE_ALIASES[BOX_COVERING_EXPONENT]
D_W = OBSERVABLE_ALIASES[WALK_DIMENSION]
PROBES: tuple[str, ...] = (D_S, D_V, D_B, D_W)

PROBE_CANONICAL: dict[str, str] = {
    D_S: SPECTRAL_DIMENSION,
    D_V: DISTANCE_VOLUME_EXPONENT,
    D_B: BOX_COVERING_EXPONENT,
    D_W: WALK_DIMENSION,
}


class RefusalCode(str, Enum):
    COMPONENT_BELOW_MEASURABLE_SIZE = "COMPONENT_BELOW_MEASURABLE_SIZE"
    NO_SCALING_WINDOW = "NO_SCALING_WINDOW"
    WINDOW_TOO_SHORT = "WINDOW_TOO_SHORT"
    EXPONENTIAL_GROWTH = "EXPONENTIAL_GROWTH"
    NO_DIFFUSIVE_WINDOW = "NO_DIFFUSIVE_WINDOW"
    WALK_SATURATED = "WALK_SATURATED"
    GROWTH_UNDECIDED = "GROWTH_UNDECIDED"
    GROWTH_UNEVEN = "GROWTH_UNEVEN"
    NOT_SETTLED = "NOT_SETTLED"
    UNPHYSICAL_FIT = "UNPHYSICAL_FIT"
    NOT_POWER_LAW = "NOT_POWER_LAW"
    NOT_MEASURED = "NOT_MEASURED"


class Bucket(str, Enum):
    CONVERGED = "CONVERGED"
    STILL_DRIFTING = "STILL_DRIFTING"
    INSIDE_NOISE_TOO_FEW_RUNGS = "INSIDE_NOISE_TOO_FEW_RUNGS"
    REFUSED_NO_SCALING_WINDOW = "REFUSED_NO_SCALING_WINDOW"
    REFUSED_NEVER_EQUILIBRATED = "REFUSED_NEVER_EQUILIBRATED"
    REFUSED_CHAINS_DISAGREED = "REFUSED_CHAINS_DISAGREED"
    REFUSED_NO_EFFECTIVE_SAMPLE = "REFUSED_NO_EFFECTIVE_SAMPLE"
    REFUSED_BELOW_CONNECTIVITY_FLOOR = "REFUSED_BELOW_CONNECTIVITY_FLOOR"
    REFUSED_MEAN_DEGREE_ABOVE_WINDOW = "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"
    REFUSED_MEAN_DEGREE_BELOW_WINDOW = "REFUSED_MEAN_DEGREE_BELOW_WINDOW"
    REFUSED_COMPUTE_BUDGET = "REFUSED_COMPUTE_BUDGET"
    UNRESOLVED_AT_TOP_RUNG = "UNRESOLVED_AT_TOP_RUNG"
    DRIFTING_MONOTONICALLY = "DRIFTING_MONOTONICALLY"
    DEGRADED_WITH_N = "DEGRADED_WITH_N"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


LIMIT_TERMINALS: frozenset[str] = frozenset({
    "REFUSED_MEAN_DEGREE_ABOVE_WINDOW", "REFUSED_COMPUTE_BUDGET",
})


NEVER_EQUILIBRATED_TERMINALS: frozenset[str] = frozenset({
    "FROZEN_OR_ABSORBING", "METASTABLE_OR_NONMIXING", "RELAXING_AT_CEILING",
})
NO_EFFECTIVE_SAMPLE_TERMINALS: frozenset[str] = frozenset({"INSUFFICIENT_EFFECTIVE_SAMPLES"})
CHAIN_DISAGREEMENT_VERDICTS: frozenset[str] = frozenset({"CHAINS_DISAGREED"})

_CODE_TO_BUCKET: dict[RefusalCode, Bucket] = {
    RefusalCode.COMPONENT_BELOW_MEASURABLE_SIZE: Bucket.REFUSED_BELOW_CONNECTIVITY_FLOOR,
    RefusalCode.NO_SCALING_WINDOW: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.WINDOW_TOO_SHORT: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.EXPONENTIAL_GROWTH: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.NO_DIFFUSIVE_WINDOW: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.WALK_SATURATED: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.GROWTH_UNDECIDED: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.GROWTH_UNEVEN: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.NOT_SETTLED: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.UNPHYSICAL_FIT: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.NOT_POWER_LAW: Bucket.REFUSED_NO_SCALING_WINDOW,
    RefusalCode.NOT_MEASURED: Bucket.NOT_ATTEMPTED,
}

UNBUCKETED_REFUSAL_CODES: frozenset = frozenset(set(RefusalCode) - set(_CODE_TO_BUCKET))


def refusal(code: RefusalCode, reason: str, **extra) -> dict:
    return {"valid": False, "refusal": code.value, "reason": reason, **extra}


def parse_refusal(value) -> RefusalCode | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("refusal")
    if raw is None:
        return None
    try:
        return RefusalCode(str(raw))
    except ValueError:
        return None


def bucket_for_rung(probe_entry, *, terminal_classification: str | None,
                    chains_verdict: str | None = None,
                    connectivity_floor_failed: bool = False) -> Bucket | None:
    if terminal_classification in LIMIT_TERMINALS:
        return Bucket(terminal_classification)
    if connectivity_floor_failed:
        return Bucket.REFUSED_BELOW_CONNECTIVITY_FLOOR
    if chains_verdict in CHAIN_DISAGREEMENT_VERDICTS:
        return Bucket.REFUSED_CHAINS_DISAGREED
    if terminal_classification in NEVER_EQUILIBRATED_TERMINALS:
        return Bucket.REFUSED_NEVER_EQUILIBRATED
    if terminal_classification in NO_EFFECTIVE_SAMPLE_TERMINALS:
        return Bucket.REFUSED_NO_EFFECTIVE_SAMPLE
    if probe_entry is None:
        return Bucket.NOT_ATTEMPTED
    if isinstance(probe_entry, dict) and probe_entry.get("valid"):
        return None
    code = parse_refusal(probe_entry)
    if code is None:
        return Bucket.NOT_ATTEMPTED
    try:
        return _CODE_TO_BUCKET[code]
    except KeyError:
        raise KeyError(
            f"refusal code {code.value!r} has no bucket: add it to "
            f"_CODE_TO_BUCKET in scaleflow/probes.py. Every RefusalCode must "
            f"resolve to a Bucket; tests/contract/test_refusal_bucket_totality.py "
            f"pins that and would have caught this before release."
        ) from None


def empty_bucket_counts() -> dict[str, int]:
    return {bucket.value: 0 for bucket in Bucket}
