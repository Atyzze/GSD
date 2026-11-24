from __future__ import annotations

import os

DEV_MODE_CONTRACT = "gsd-dev-mode-1"

ENV_VAR = "GSD_DEV_MODE"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

RELAXATIONS: dict[str, str] = {
    "science_freeze_advisory": (
        "The science-sensitive source freeze reports drift instead of failing. "
        "Gives up: proof that a release did not silently move estimator, "
        "ladder, flow, or calibration behaviour."
    ),
    "mutable_policy_epochs": (
        "Policy thresholds may change without minting a new epoch. Gives up: "
        "the guarantee that every decision can name the exact policy revision "
        "that produced it."
    ),
    "schema_rebuild_permitted": (
        "The workspace schema may be dropped and rebuilt in place. Gives up: "
        "continuity of stored evidence across the rebuild."
    ),
}

NEVER_RELAXED: dict[str, str] = {
    "no_scientific_selection_until_terminal": (
        "Selection before a candidate is terminal biases the prefix-versus-"
        "next-rung comparison that every prevalence claim rests on."
    ),
    "unfiltered_fraction": (
        "The unfiltered sample is the only population a filter's false-stop "
        "rate can be estimated from. Shrinking it destroys the measurement "
        "that justifies filtering at all."
    ),
    "connectivity_floor_armed_from_n": (
        "The arming rung exists because the audit found the floor rule firing "
        "at N=64 on laws fully connected by N=16384. A giant component is a "
        "property a graph has to be large enough to have."
    ),
}


def enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() in _TRUTHY


def relaxation_active(name: str) -> bool:
    if name not in RELAXATIONS:
        raise KeyError(f"unknown relaxation: {name!r}")
    return enabled()


def provenance() -> dict:
    active = enabled()
    return {
        "contract": DEV_MODE_CONTRACT,
        "development_mode": active,
        "certified_run": not active,
        "relaxations": sorted(RELAXATIONS) if active else [],
        "warning": (
            "Produced with development-mode safeguards relaxed. Not a certified "
            "run: the science freeze was advisory and policy epochs were mutable, "
            "so numbers from this run must not be cited as reproducible evidence."
        ) if active else None,
    }


def stamp(payload: dict) -> dict:
    return dict(payload, run_mode=provenance())


def banner() -> str | None:
    if not enabled():
        return None
    return (
        "DEVELOPMENT MODE: safeguards relaxed "
        f"({', '.join(sorted(RELAXATIONS))}); output is not certified evidence"
    )
