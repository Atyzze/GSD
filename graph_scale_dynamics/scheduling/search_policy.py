from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class SearchPolicyKind:
    name: str
    proposes: bool
    steerable: bool
    statement: str
    validate: Callable[[dict, dict], list[str]]


_STEERING_KEYS = ("weights", "family_memory", "term_count_weights",
                  "scaling_profiles", "coupling", "operator_multipliers")


def _validate_blind(policy: dict, spec: dict) -> list[str]:
    from graph_scale_dynamics.services.proposer.blind import validate_grid
    problems = []
    if "grid" not in policy:
        problems.append("search_policy.grid must be declared for a blind campaign")
    else:
        problems.extend(validate_grid(policy.get("grid")))
    proposer = spec.get("proposer")
    if isinstance(proposer, dict):
        steering = sorted(k for k in proposer if k != "pool_min")
        if steering:
            problems.append(
                "a blind campaign's proposer may only set pool_min; "
                f"remove {steering} (they steer the search)")
    return problems


REGISTRY: dict[str, SearchPolicyKind] = {}


def register(kind: SearchPolicyKind) -> SearchPolicyKind:
    if kind.name in REGISTRY:
        raise ValueError(f"search policy kind {kind.name!r} registered twice")
    REGISTRY[kind.name] = kind
    return kind


register(SearchPolicyKind("blind", proposes=True, steerable=False,
                          statement="laws drawn uniformly from a declared grid; nothing steers",
                          validate=_validate_blind))


def _validate_hand(policy: dict, spec: dict) -> list[str]:
    proposer = spec.get("proposer")
    if isinstance(proposer, dict):
        steering = [k for k in _STEERING_KEYS if k in proposer]
        if steering:
            return [f"a hand-fed campaign's proposer draws nothing; remove {steering}"]
    return []


register(SearchPolicyKind("hand", proposes=False, steerable=False,
                          statement="every law submitted by hand; the proposer draws nothing",
                          validate=_validate_hand))


def kind_of(spec: dict) -> SearchPolicyKind | None:
    policy = spec.get("search_policy")
    if not isinstance(policy, dict):
        return None
    return REGISTRY.get(str(policy.get("kind") or ""))


def kind_names() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))


def validate_search_policy(spec: dict) -> list[str]:
    policy = spec.get("search_policy")
    if not isinstance(policy, dict):
        return [f"search_policy must be an object with kind in {list(kind_names())}"]
    kind = REGISTRY.get(str(policy.get("kind") or ""))
    if kind is None:
        return [f"search_policy.kind must be one of {list(kind_names())}"]
    return kind.validate(policy, spec)
