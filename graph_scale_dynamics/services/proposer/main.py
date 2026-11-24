from __future__ import annotations
import uuid
import argparse, json, math, os, random
from collections import Counter
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.db.repo import Repo, retryable_db_error
from graph_scale_dynamics.decisions.engine import Policy, in_audit_sample
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, CandidateState
from graph_scale_dynamics.domain.randomness import derive_seed
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.research.proposal_memory import (
    FAMILY_MEMORY_VERSION, build_family_memory, proposal_assessment,
)
from graph_scale_dynamics.research.search_measure import exposure_record
from graph_scale_dynamics.research.proposal_intelligence import (
    SCALING_PROFILES, proposal_coordinates, scaling_profile,
)
from graph_scale_dynamics.research.coupling import (
    BETA_MAX, BETA_MIN, COUPLING_STRATA, REFERENCE_N, coupling_stratum,
    coupling_strength, coupling_targets, rescale_coupling,
    sample_target_strength, sweeps_for_coupling,
)
from graph_scale_dynamics.research.flow_fitness import (
    selection_value, flow_fitness,
)
from graph_scale_dynamics.research.dimensional_cartography import (
    CARTOGRAPHY_ASSESSMENT_MODE, CARTOGRAPHY_VERSION, build_observations, cartography_plan, local_perturbation,
)
from graph_scale_dynamics.operations import campaign_control
from graph_scale_dynamics.services.proposer.blind import is_continuous as blind_is_continuous
from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
from graph_scale_dynamics.scheduling.admission import SLOT_BASE_BLOCK, SLOT_PROPOSED, SLOTS, admission_slot
from graph_scale_dynamics.scheduling.admission import waiting_to_learn, without_the_waiting
from graph_scale_dynamics.services.proposer.blind import blind_batch, law_stream
from graph_scale_dynamics.services.proposer.blind import DUPLICATES, PRODUCED, STRATUM_UNFILLED
from graph_scale_dynamics.services.proposer.blind import identity_version as blind_identity_version

TERMINAL = TERMINAL_CANDIDATE_STATES


def admission(live_laws: list[dict], *, pool_min: int, max_active: int, top_base_n: int) -> dict:
    counts = Counter(admission_slot(str(row.get("state")), row.get("action"), row.get("next_n"), top_base_n)
                     for row in live_laws)
    proposed, base_block = counts[SLOT_PROPOSED], counts[SLOT_BASE_BLOCK]
    window = max_active + pool_min
    if proposed >= pool_min:
        reason = f"{proposed} proposed laws await validation, at the pool of {pool_min}"
    elif base_block >= window:
        reason = f"{base_block} laws are in their base block, at the window of {window}"
    else:
        reason = f"{base_block} of {window} base-block places taken, {proposed} of {pool_min} proposed"
    return {"open": proposed < pool_min and base_block < window, "need": max(0, pool_min - proposed),
            "counts": {slot: counts[slot] for slot in SLOTS},
            "window": window, "reason": reason}


def _proposal_exposure_with_operator_metadata(spec: dict, **kwargs) -> dict:
    row = exposure_record(spec, **kwargs)
    coordinates = dict(row.get("coordinates") or {})
    coordinates["operators"] = sorted({
        str(term.get("op") or "unknown") for term in (spec.get("terms") or [])
    })
    row["coordinates"] = coordinates
    return row


def campaign_rng_seed(search_seed: int | str, candidate_count: int) -> int:
    return derive_seed("proposer-campaign", str(search_seed), int(candidate_count),
                       "proposer-contract-3")

def _round(value: float) -> float:
    return float(f"{value:.4g}")


BASE_SWEEPS = 30


def _coupling_policy(spec: dict) -> tuple[dict[str, float], dict]:
    configured = coupling_targets(spec)
    return configured, {
        "epoch": None, "policy_version": "campaign-spec",
        "configured_targets": configured, "effective_targets": configured,
        "immutable": True,
    }


def _dynamics(rng: random.Random, beta: float | None = None,
              sweeps: int | None = None) -> dict:
    if beta is None:
        beta = math.exp(rng.uniform(math.log(BETA_MIN * 10.0), math.log(BETA_MAX)))
    return {"kind": "equilibrium", "beta": _round(beta),
            "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15},
            "sweeps": int(sweeps or BASE_SWEEPS)}


def coordination_seed_library() -> list[dict]:
    library = []
    for beta, edge, k, anchor in ((40.0, 0.25, 4, 0.50),
                                  (40.0, 0.25, 8, 0.50),
                                  (80.0, 0.20, 12, 0.35)):
        library.append({
            "dsl_version": 1, "init": "empty",
            "terms": [
                {"op": "edge_count", "params": {},
                 "coeff": {"c0": edge, "scale": "log_N"}},
                {"op": "degree_anchor_abs", "params": {"k": k},
                 "coeff": {"c0": anchor, "scale": "one"}},
            ],
            "dynamics": {"kind": "equilibrium", "beta": beta,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15},
                         "sweeps": sweeps_for_coupling(BASE_SWEEPS, beta * anchor)},
        })
    return library


def seed_library() -> list[dict]:
    library = list(coordination_seed_library())

    for k in (4, 8):
        library.append({"dsl_version": 1, "init": "empty",
            "terms": [{"op": "edge_count", "params": {},
                       "coeff": {"c0": 0.2, "scale": "log_N"}},
                      {"op": "degree_anchor_abs", "params": {"k": k},
                       "coeff": {"c0": 0.5, "scale": "inv_log_N"}}],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 30}})

    library.append({"dsl_version": 1, "init": "empty",
        "terms": [{"op": "degree_cube_sum", "params": {},
                   "coeff": {"c0": 0.02, "scale": "one"}},
                  {"op": "edge_count", "params": {},
                   "coeff": {"c0": -0.4, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 30}})

    for motif, sign in (("triangle_count", -1), ("triangle_count", 1),
                        ("square_count", -1), ("square_count", 1)):
        for k in (6, 10):
            library.append({
                "dsl_version": 1, "init": "empty",
                "terms": [
                    {"op": "edge_count", "params": {},
                     "coeff": {"c0": 0.25, "scale": "log_N"}},
                    {"op": "degree_anchor_abs", "params": {"k": k},
                     "coeff": {"c0": 0.4, "scale": "one"}},
                    {"op": motif, "params": {},
                     "coeff": {"c0": sign * 0.2, "scale": "one"}},
                ],
                "dynamics": {"kind": "equilibrium", "beta": 1.0,
                             "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 30}})

    for overlap in (0.15, 0.35, 0.7):
        library.append({"dsl_version": 1, "init": "empty",
            "terms": [
                {"op": "edge_count", "params": {},
                 "coeff": {"c0": 0.25, "scale": "log_N"}},
                {"op": "triangle_count", "params": {},
                 "coeff": {"c0": -0.2, "scale": "one"}},
                {"op": "triangle_edge_overlap", "params": {},
                 "coeff": {"c0": overlap, "scale": "one"}},
            ],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 30}})

    for square_op in ("square_count", "induced_square_count"):
        library.append({"dsl_version": 1, "init": "empty",
            "terms": [
                {"op": "edge_count", "params": {},
                 "coeff": {"c0": 0.25, "scale": "log_N"}},
                {"op": square_op, "params": {},
                 "coeff": {"c0": -0.16, "scale": "one"}},
                {"op": "square_edge_overlap", "params": {},
                 "coeff": {"c0": 0.12, "scale": "one"}},
            ],
            "dynamics": _dynamics(random.Random(3700 + len(library)), beta=1.0)})

    for gradient in (0.12, -0.12):
        library.append({"dsl_version": 1, "init": "empty",
            "terms": [
                {"op": "edge_count", "params": {},
                 "coeff": {"c0": 0.25, "scale": "log_N"}},
                {"op": "degree_neighbor_gradient", "params": {},
                 "coeff": {"c0": gradient, "scale": "one"}},
            ],
            "dynamics": _dynamics(random.Random(3800 + len(library)), beta=1.0)})

    library.append({"dsl_version": 1, "init": "empty",
        "terms": [
            {"op": "degree_anchor", "params": {"k": 7},
             "coeff": {"c0": -0.08, "scale": "one"}},
            {"op": "degree_fourth_sum", "params": {},
             "coeff": {"c0": 0.004, "scale": "one"}},
            {"op": "edge_count", "params": {},
             "coeff": {"c0": 0.18, "scale": "log_N"}},
        ],
        "dynamics": _dynamics(random.Random(3900), beta=1.0)})
    return library


SCALED_COEFFICIENT_SCALES = ("log_N", "inv_log_N", "inv_N", "inv_sqrt_N", "power")
_CANONICAL_POWER_EXPONENTS = (-2.0, -1.5, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 1.5, 2.0)
_ANCHOR_VALUES = tuple(range(2, 33))


def _sample_power_exponent(rng: random.Random) -> float:
    if rng.random() < 0.60:
        return float(rng.choice(_CANONICAL_POWER_EXPONENTS))
    return _round(rng.uniform(-2.0, 2.0))


def _sample_anchor_k(rng: random.Random) -> int:
    weights = [1.0 / math.sqrt(k) for k in _ANCHOR_VALUES]
    return int(rng.choices(_ANCHOR_VALUES, weights=weights)[0])


def _set_term_scale(term: dict, scale: str, rng: random.Random) -> None:
    term["coeff"]["scale"] = scale
    if scale == "power":
        term["coeff"]["p"] = _sample_power_exponent(rng)
    else:
        term["coeff"].pop("p", None)


def _walk_power_exponent(term: dict, rng: random.Random) -> None:
    if term.get("coeff", {}).get("scale") != "power":
        return
    current = float(term["coeff"].get("p", 0.0))
    term["coeff"]["p"] = _round(min(2.0, max(-2.0, current + rng.gauss(0.0, 0.22))))


def _stabilize_negative_degree_anchors(terms: list[dict], rng: random.Random) -> None:
    negative = [t for t in terms
                if t.get("op") == "degree_anchor"
                and float((t.get("coeff") or {}).get("c0") or 0.0) < 0]
    if not negative:
        return
    scale = negative[0]["coeff"].get("scale", "one")
    p = negative[0]["coeff"].get("p")
    for term in negative[1:]:
        term["coeff"]["scale"] = scale
        if scale == "power":
            term["coeff"]["p"] = p
        else:
            term["coeff"].pop("p", None)
    quartic = next((t for t in terms if t.get("op") == "degree_fourth_sum"), None)
    if quartic is None:
        quartic = {"op": "degree_fourth_sum", "params": {},
                   "coeff": {"c0": _round(0.002 + rng.random() * 0.02), "scale": scale}}
        terms.append(quartic)
    quartic["coeff"]["c0"] = abs(float(quartic["coeff"].get("c0") or 0.005)) or 0.005
    quartic["coeff"]["scale"] = scale
    if scale == "power":
        quartic["coeff"]["p"] = p if p is not None else _sample_power_exponent(rng)
    else:
        quartic["coeff"].pop("p", None)


def _enforce_scaling_profile(terms: list[dict], profile: str,
                             rng: random.Random) -> None:
    if not terms:
        return
    if profile == "unscaled":
        for term in terms:
            _set_term_scale(term, "one", rng)
        return
    if profile == "scaled":
        for term in terms:
            if term["coeff"].get("scale") == "one":
                _set_term_scale(term, rng.choice(SCALED_COEFFICIENT_SCALES), rng)
        return
    if len(terms) < 2:
        return
    if not any(term["coeff"].get("scale") == "one" for term in terms):
        _set_term_scale(rng.choice(terms), "one", rng)
    if not any(term["coeff"].get("scale") != "one" for term in terms):
        choices = [term for term in terms if term["coeff"].get("scale") == "one"]
        _set_term_scale(rng.choice(choices), rng.choice(SCALED_COEFFICIENT_SCALES), rng)


def _place_on_coupling_axis(spec: dict, rng: random.Random,
                            coupling_target: str | None) -> dict:
    if coupling_target:
        rescale_coupling(spec, sample_target_strength(rng, coupling_target))
    strength = coupling_strength(spec, REFERENCE_N)
    spec["dynamics"]["sweeps"] = sweeps_for_coupling(BASE_SWEEPS, strength)
    return spec


def _sparsity_guard(terms: list[dict], rng: random.Random,
                    target_profile: str | None = None) -> None:
    def positive(term):
        return float((term.get("coeff") or {}).get("c0") or 0.0) > 0

    def strong_scale(term):
        coeff = term.get("coeff") or {}
        scale = coeff.get("scale")
        return scale == "log_N" or (scale == "power" and float(coeff.get("p") or 0.0) > 0)

    for term in terms:
        op = term["op"]
        if not positive(term):
            continue
        if op in ("degree_anchor", "degree_square_sum", "wedge_count", "degree_cube_sum",
                  "degree_fourth_sum"):
            return
        if op in ("edge_count", "degree_anchor_abs") and strong_scale(term):
            return

    existing = {(term["op"], json.dumps(term.get("params") or {}, sort_keys=True)): term
                for term in terms}
    if target_profile == "unscaled":
        key = ("degree_square_sum", "{}")
        if key in existing:
            existing[key]["coeff"]["c0"] = abs(existing[key]["coeff"]["c0"]) or _round(0.05)
            _set_term_scale(existing[key], "one", rng)
        else:
            terms.append({"op": "degree_square_sum", "params": {},
                          "coeff": {"c0": _round(0.03 + rng.random() * 0.12), "scale": "one"}})
    else:
        key = ("edge_count", "{}")
        if key in existing:
            existing[key]["coeff"]["c0"] = abs(existing[key]["coeff"]["c0"]) or _round(0.25)
            _set_term_scale(existing[key], "log_N", rng)
        else:
            terms.append({"op": "edge_count", "params": {},
                          "coeff": {"c0": _round(0.15 + rng.random() * 0.4), "scale": "log_N"}})
    if target_profile:
        _enforce_scaling_profile(terms, target_profile, rng)


def _term_count(rng: random.Random, config: dict | None = None,
                target_profile: str | None = None) -> int:
    raw = (config or {}).get("term_count_weights") or {"1": 0.12, "2": 0.38,
                                                        "3": 0.32, "4": 0.18}
    values, weights = [], []
    for key, weight in raw.items():
        try:
            count = int(key)
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if count > 0 and weight > 0:
            values.append(count)
            weights.append(weight)
    if not values:
        values, weights = [1, 2, 3, 4], [0.12, 0.38, 0.32, 0.18]
    count = rng.choices(values, weights)[0]
    if target_profile == "mixed":
        count = max(2, count)
    return count


def _new_term(rng: random.Random, op: str, scale: str) -> dict:
    coeff = {
        "c0": _round(rng.choice([-1, 1]) * math.exp(
            rng.uniform(math.log(0.05), math.log(2.0))
        )),
        "scale": scale,
    }
    term = {"op": op, "params": {}, "coeff": coeff}
    if scale == "power":
        coeff["p"] = _sample_power_exponent(rng)
    if op in ("degree_anchor", "degree_anchor_abs"):
        term["params"] = {"k": _sample_anchor_k(rng)}
        term["coeff"]["c0"] = abs(term["coeff"]["c0"])
    if op == "degree_fourth_sum":
        term["coeff"]["c0"] = abs(term["coeff"]["c0"])
    return term


def random_law(rng: random.Random, whitelist: list[str], *,
               target_profile: str | None = None, config: dict | None = None,
               coupling_target: str | None = None) -> dict:
    profile = target_profile or rng.choice(SCALING_PROFILES)
    n_terms = _term_count(rng, config, profile)
    ops = [op for op in whitelist if op in dsl.OPERATORS]
    operator_multipliers = (config or {}).get("operator_multipliers") or {}
    weights = [max(0.05, float(operator_multipliers.get(op, 1.0)))
               / dsl.OPERATORS[op]["cost"] for op in ops]
    terms: list[dict] = []
    used: set[tuple[str, str]] = set()
    attempts = 0
    while len(terms) < n_terms and attempts < 40:
        attempts += 1
        op = rng.choices(ops, weights)[0]
        if profile == "unscaled":
            scale = "one"
        elif profile == "scaled":
            scale = rng.choice(SCALED_COEFFICIENT_SCALES)
        else:
            scale = "one" if len(terms) == 0 else (
                rng.choice(SCALED_COEFFICIENT_SCALES) if len(terms) == 1
                else rng.choice(("one", *SCALED_COEFFICIENT_SCALES))
            )
        term = _new_term(rng, op, scale)
        key = (op, json.dumps(term["params"], sort_keys=True))
        if key in used:
            continue
        used.add(key)
        terms.append(term)
    _sparsity_guard(terms, rng, profile)
    _enforce_scaling_profile(terms, profile, rng)
    _stabilize_negative_degree_anchors(terms, rng)
    law = {"dsl_version": 1, "init": "empty", "terms": terms, "dynamics": _dynamics(rng)}
    return _place_on_coupling_axis(law, rng, coupling_target)


def mutate(rng: random.Random, parent_spec: dict, whitelist: list[str], *,
           target_profile: str | None = None, config: dict | None = None,
           coupling_target: str | None = None) -> dict:
    child = json.loads(json.dumps(parent_spec))
    terms = child["terms"]

    axis = rng.random()
    if axis < 0.12:
        current = coupling_strength(child, REFERENCE_N)
        if current > 0:
            rescale_coupling(child, current * math.exp(rng.uniform(math.log(0.35),
                                                                  math.log(3.0))))
    elif axis < 0.20:
        beta = float(child["dynamics"].get("beta", 1.0))
        child["dynamics"]["beta"] = _round(
            min(BETA_MAX, max(BETA_MIN, beta * rng.uniform(0.5, 2.0)))
        )

    move = rng.random()
    if move < 0.30 and terms:
        term = rng.choice(terms)
        term["coeff"]["c0"] = _round(term["coeff"]["c0"] * rng.uniform(0.55, 1.8))
    elif move < 0.40 and terms:
        term = rng.choice(terms)
        if term["op"] == "degree_anchor":
            quartic = next((q for q in terms
                            if q["op"] == "degree_fourth_sum"
                            and float(q["coeff"]["c0"]) > 0), None)
            if quartic is not None:
                term["coeff"]["c0"] = _round(-term["coeff"]["c0"])
                _set_term_scale(quartic, term["coeff"].get("scale", "one"), rng)
                if term["coeff"].get("scale") == "power":
                    quartic["coeff"]["p"] = term["coeff"].get("p", 0.0)
        elif term["op"] not in ("degree_anchor_abs", "degree_fourth_sum"):
            term["coeff"]["c0"] = _round(-term["coeff"]["c0"])
    elif move < 0.55 and terms:
        term = rng.choice(terms)
        if term["coeff"].get("scale") == "power" and rng.random() < 0.45:
            _walk_power_exponent(term, rng)
        else:
            _set_term_scale(term, rng.choice(("one", *SCALED_COEFFICIENT_SCALES)), rng)
    elif move < 0.72:
        extra = random_law(rng, whitelist, target_profile=target_profile,
                           config=config)["terms"][0]
        key = (extra["op"], json.dumps(extra.get("params") or {}, sort_keys=True))
        existing = {(term["op"], json.dumps(term.get("params") or {}, sort_keys=True))
                    for term in terms}
        if key not in existing:
            terms.append(extra)
    elif move < 0.84 and len(terms) > 1:
        terms.pop(rng.randrange(len(terms)))
    elif move < 0.93:
        anchors = [term for term in terms
                   if term["op"] in ("degree_anchor", "degree_anchor_abs")]
        if anchors:
            chosen = rng.choice(anchors)
            current = chosen["params"]["k"]
            choices = [k for k in _ANCHOR_VALUES if k != current]
            weights = [1.0 / math.sqrt(k) for k in choices]
            chosen["params"]["k"] = int(rng.choices(choices, weights=weights)[0])
    elif terms:
        index = rng.randrange(len(terms))
        replacement = random_law(rng, whitelist, target_profile=target_profile,
                                 config=config)["terms"][0]
        terms[index] = replacement
    profile = target_profile or scaling_profile(child)
    if profile == "mixed" and len(terms) < 2:
        for extra in random_law(rng, whitelist, target_profile="mixed",
                                config=config)["terms"]:
            key = (extra["op"], json.dumps(extra.get("params") or {}, sort_keys=True))
            existing = {(term["op"], json.dumps(term.get("params") or {}, sort_keys=True))
                        for term in terms}
            if key not in existing:
                terms.append(extra)
                break
    _sparsity_guard(terms, rng, profile)
    _enforce_scaling_profile(terms, profile, rng)
    _stabilize_negative_degree_anchors(terms, rng)
    return _place_on_coupling_axis(child, rng, coupling_target)


def _profile_targets(spec: dict) -> dict[str, float]:
    raw = (spec.get("proposer", {}).get("scaling_profiles") or {}).get("targets") or {
        "unscaled": 0.30, "mixed": 0.40, "scaled": 0.30,
    }
    targets = {profile: max(0.0, float(raw.get(profile, 0.0)))
               for profile in SCALING_PROFILES}
    total = sum(targets.values())
    if total <= 0:
        return {profile: 1.0 / len(SCALING_PROFILES) for profile in SCALING_PROFILES}
    return {profile: value / total for profile, value in targets.items()}


def _choose_profile(rng: random.Random, counts: Counter, targets: dict[str, float]) -> str:
    total = sum(counts.values())
    weights = []
    for profile in SCALING_PROFILES:
        expected = targets[profile] * (total + 1)
        deficit = expected - counts.get(profile, 0)
        weights.append(max(targets[profile] * 0.10, deficit + targets[profile]))
    return rng.choices(SCALING_PROFILES, weights)[0]


def _choose_coupling(rng: random.Random, counts: Counter,
                     targets: dict[str, float]) -> str:
    total = max(1, sum(counts.values()))
    weights = []
    for stratum in COUPLING_STRATA:
        expected = targets[stratum] * total
        deficit = expected - counts.get(stratum, 0)
        weights.append(max(targets[stratum] * 0.10, deficit + targets[stratum]))
    return rng.choices(list(COUPLING_STRATA), weights)[0]


def _coupling_multiplier(stratum: str, counts: Counter,
                         targets: dict[str, float]) -> float:
    total = max(1, sum(counts.values()))
    current = counts.get(stratum, 0) / total
    target = targets.get(stratum, 1.0 / len(COUPLING_STRATA))
    return max(0.35, min(3.0, (target + 0.02) / (current + 0.02)))


def _profile_multiplier(profile: str, counts: Counter,
                        targets: dict[str, float]) -> float:
    total = max(1, sum(counts.values()))
    current = counts.get(profile, 0) / total
    target = targets.get(profile, 1.0 / len(SCALING_PROFILES))
    return max(0.35, min(3.0, (target + 0.02) / (current + 0.02)))


def _choose_parent(rng: random.Random, parents: list[dict]) -> dict:
    total_attempts = sum(int(p.get("breed_attempts") or 0) for p in parents)
    weights = [selection_value(p.get("fitness") or {},
                               attempts=int(p.get("breed_attempts") or 0),
                               total_attempts=total_attempts)
               for p in parents]
    chosen = rng.choices(parents, weights)[0]
    chosen["breed_attempts"] = int(chosen.get("breed_attempts") or 0) + 1
    return chosen


def generate_batch(rng: random.Random, need: int, spec: dict, existing: set[str],
                   parents: list[dict], profile_counts: Counter | None = None,
                   existing_physical: set[str] | None = None,
                   coupling_counts: Counter | None = None
                   ) -> list[tuple[dict, str | None, str]]:
    whitelist = spec.get("operator_whitelist", list(dsl.OPERATORS))
    budget = spec.get("complexity_budget", 6)
    proposer_cfg = spec.get("proposer", {})
    weights = proposer_cfg.get("weights",
                               {"enumeration": 0.4, "mutation": 0.35, "novelty": 0.25})
    targets = _profile_targets(spec)
    counts = Counter(profile_counts or {})
    coupling_target_fractions = coupling_targets(spec)
    coupling_seen = Counter(coupling_counts or {})
    physical = existing_physical if existing_physical is not None else set()
    library = [law for law in seed_library()
               if not dsl.validate(law, complexity_budget=budget, operator_whitelist=whitelist)
               and dsl.fingerprint(law) not in existing]
    batch: list[tuple[dict, str | None, str]] = []
    attempts = 0
    while len(batch) < need and attempts < max(300, need * 60):
        attempts += 1
        target_profile = _choose_profile(rng, counts, targets)
        target_coupling = _choose_coupling(rng, coupling_seen, coupling_target_fractions)
        roll = rng.random()
        candidate, parent, source = None, None, None
        if roll < weights["enumeration"] and library:
            matching = [index for index, law in enumerate(library)
                        if scaling_profile(law) == target_profile]
            index = matching[0] if matching else 0
            candidate, source = library.pop(index), "enumeration"
        elif roll < weights["enumeration"] + weights["mutation"] and parents:
            chosen = _choose_parent(rng, parents)
            candidate = mutate(rng, chosen["spec"], whitelist,
                               target_profile=target_profile, config=proposer_cfg,
                               coupling_target=target_coupling)
            parent, source = chosen["candidate_id"], "mutation"
        else:
            candidate = random_law(rng, whitelist, target_profile=target_profile,
                                   config=proposer_cfg, coupling_target=target_coupling)
            source = "novelty"
        if dsl.validate(candidate, complexity_budget=budget, operator_whitelist=whitelist):
            continue
        fingerprint = dsl.fingerprint(candidate)
        if fingerprint in existing:
            continue
        normalized = dsl.normalize(candidate)
        physical_id = equilibrium_identity(normalized)[0]
        if physical_id in physical:
            continue
        existing.add(fingerprint)
        physical.add(physical_id)
        batch.append((normalized, parent, source))
        counts[scaling_profile(normalized)] += 1
        coupling_seen[coupling_stratum(normalized)] += 1
    return batch


def select_batch(rng: random.Random, batch: list[tuple[dict, str | None, str]],
                 need: int, memory: dict[str, dict], family_cfg: dict,
                 profile_counts: Counter, targets: dict[str, float], mode: str,
                 coupling_counts: Counter | None = None,
                 coupling_target_fractions: dict[str, float] | None = None,
                 coupling_policy: dict | None = None
                 ) -> list[tuple[dict, str | None, str, dict]]:
    coupling_fractions = coupling_target_fractions or coupling_targets({})
    live_coupling = Counter(coupling_counts or {})
    remaining = []
    for candidate_spec, parent, source in batch:
        assessment = proposal_assessment(candidate_spec, memory, family_cfg)
        assessment = dict(assessment)
        assessment["coupling_strength"] = round(
            coupling_strength(candidate_spec, REFERENCE_N), 6)
        assessment["coupling_stratum"] = coupling_stratum(candidate_spec, REFERENCE_N)
        assessment["beta"] = candidate_spec["dynamics"]["beta"]
        assessment["declared_sweeps"] = candidate_spec["dynamics"]["sweeps"]
        remaining.append([candidate_spec, parent, source, assessment])
    if mode != "active":
        return [(spec, parent, source, assessment)
                for spec, parent, source, assessment in remaining[:need]]

    selected: list[tuple[dict, str | None, str, dict]] = []
    batch_family_counts: Counter = Counter()
    batch_region_counts: Counter = Counter()
    live_counts = Counter(profile_counts)
    family_decay = float(family_cfg.get("batch_family_decay", 0.45))
    region_decay = float(family_cfg.get("batch_region_decay", 0.25))
    while remaining and len(selected) < need:
        weights = []
        for _, _, _, assessment in remaining:
            family_id = assessment["family_id"]
            region_id = assessment["coefficient_region_id"]
            profile = assessment["scaling_profile"]
            weight = float(assessment.get("allocation_weight") or 1.0)
            weight *= _profile_multiplier(profile, live_counts, targets)
            weight *= _coupling_multiplier(assessment["coupling_stratum"],
                                           live_coupling, coupling_fractions)
            weight *= family_decay ** batch_family_counts[family_id]
            weight *= region_decay ** batch_region_counts[region_id]
            weights.append(max(float(assessment.get("exploration_floor") or 0.08), weight))
        index = rng.choices(range(len(remaining)), weights)[0]
        candidate_spec, parent, source, assessment = remaining.pop(index)
        profile = assessment["scaling_profile"]
        weight_sum = sum(weights)
        stratum = assessment["coupling_stratum"]
        coupling_total = max(1, sum(live_coupling.values()))
        assessment = dict(assessment) | {
            "selection_weight": weights[index],
            "pool_selection_probability": (weights[index] / weight_sum if weight_sum > 0 else None),
            "pool_size_before_selection": len(remaining) + 1,
            "coupling_target_fraction": coupling_fractions[stratum],
            "coupling_current_fraction": live_coupling.get(stratum, 0) / coupling_total,
            "coupling_policy": dict(coupling_policy or {}),
            "scaling_target_fraction": targets[profile],
            "scaling_current_fraction": (
                live_counts.get(profile, 0) / max(1, sum(live_counts.values()))
            ),
            "profile_multiplier": _profile_multiplier(profile, live_counts, targets),
            "batch_family_count_before": batch_family_counts[assessment["family_id"]],
            "batch_region_count_before": batch_region_counts[assessment["coefficient_region_id"]],
        }
        selected.append((candidate_spec, parent, source, assessment))
        batch_family_counts[assessment["family_id"]] += 1
        batch_region_counts[assessment["coefficient_region_id"]] += 1
        live_counts[profile] += 1
        live_coupling[stratum] += 1
    return selected


def attach_flow_fitness(repo, campaign_id: str, spec: dict, parents: list[dict]) -> None:
    if not parents:
        return
    try:
        version = spec.get("analysis_version") or repo.latest_analysis_version(campaign_id)
        summaries = repo.campaign_rung_summaries(campaign_id, version) if version else {}
    except Exception:
        summaries = {}
    ladder = spec.get("ladder") or None
    convergence = (spec.get("policy") or {}).get("convergence") or {}
    tolerance = float(convergence.get("max_final_drift", 0.25))
    seed_tolerance = float(convergence.get("seed_reproducibility_sd", 0.30))
    for parent in parents:
        rows = summaries.get(parent["candidate_id"]) or []
        rungs = {int(row["n"]): row.get("summary") or {} for row in rows}
        parent["fitness"] = flow_fitness(
            rungs, ladder=ladder, drift_tolerance=tolerance,
            seed_sd_tolerance=seed_tolerance,
        )
        parent["breed_attempts"] = 0


def lineage_parents(candidates: list[dict]) -> list[dict]:
    from graph_scale_dynamics.domain.model import RUNNING_CANDIDATE_STATES
    parents = []
    for candidate in candidates:
        state = candidate["state"]
        reason = candidate.get("state_reason") or ""
        if state in RUNNING_CANDIDATE_STATES:
            parents.append(candidate)
        elif state == "PARKED" and "budget ceiling" in reason:
            parents.append(candidate)
    return parents


EXTEND_ONLY_FLAG = "extend_only"


def extend_only(campaign: dict, flagged: frozenset[str] = frozenset()) -> bool:
    if str(campaign.get("campaign_id")) in flagged:
        return True
    if str(campaign.get(EXTEND_ONLY_FLAG) or "").strip().lower() in ("1", "true", "yes"):
        return True
    spec = campaign.get("spec")
    if isinstance(spec, str):
        try:
            import json as _json
            spec = _json.loads(spec)
        except ValueError:
            spec = None
    if isinstance(spec, dict):
        return bool((spec.get("search") or {}).get(EXTEND_ONLY_FLAG))
    return False


def proposal_targets(actives: list[dict],
                     flagged: frozenset[str] = frozenset()) -> list[dict]:
    return [campaign for campaign in actives if not extend_only(campaign, flagged)]


def proposal_target_banner(actives: list[dict],
                           flagged: frozenset[str] = frozenset()) -> str:
    targets = [str(c["campaign_id"]) for c in proposal_targets(actives, flagged)]
    line = f"proposer targets: {', '.join(targets) or 'none'} (every active campaign)"
    extending = [str(c["campaign_id"]) for c in actives if extend_only(c, flagged)]
    if extending:
        line += (f"; extend-only, no new candidates: {', '.join(extending)}. "
                 "Existing work, continuations and deeper rungs continue")
    return line


_ADMISSION_LOGGED: dict[str, bool] = {}


def _note_admission(log: Log, campaign_id: str, window: dict) -> None:
    if _ADMISSION_LOGGED.get(str(campaign_id)) != window["open"]:
        _ADMISSION_LOGGED[str(campaign_id)] = window["open"]
        log.write("admission_open" if window["open"] else "admission_closed", campaign=str(campaign_id)[:17],
                  reason=window["reason"], counts=window["counts"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--var", default="var")
    parser.add_argument("--poll", type=float, default=ticks(1))
    args = parser.parse_args(argv)
    repo = Repo(args.db)
    service = f"proposer-{os.getpid()}"
    log = Log(args.var, service)
    log.write("start", home=str(args.campaign))
    try:
        while True:
            try:
                if repo.get_flag("paused", "0") == "1":
                    repo.heartbeat(service, {"paused": True, "proposal_campaigns": []})
                    repo.wait_for_work(30.0)
                    continue
                actives = repo.active_campaigns()
                if not actives and not repo.fleet_has_work():
                    log.write("exit", reason="no active campaign, analysis backlog or control event remains")
                    return 0
                targets = proposal_targets(actives, repo.extend_only_campaigns())
                windows = serve_campaigns(repo, log, targets)
                repo.heartbeat(service, {"active_campaigns": len(actives),
                                         "proposal_campaigns": [c["campaign_id"] for c in targets],
                                         "admission": windows})
            except DatabaseOperationalError as exc:
                if not retryable_db_error(exc):
                    raise
                log.write("database_busy", error=str(exc)[:200])
                try:
                    repo.conn.rollback_if_open()
                except Exception:
                    pass
            repo.wait_for_work(max(args.poll, 0.5))
    finally:
        repo.close()


def _cartography_evidence(repo: Repo, campaign: dict, candidates: list[dict],
                         config: dict) -> tuple[list[dict], dict] | tuple[None, dict]:
    source_id = str(config.get("source_campaign_id") or "").strip()
    source = repo.campaign(source_id) if source_id else None
    if source is None:
        return None, {"status": "INSUFFICIENT_EVIDENCE",
                      "reason": f"cartography source campaign {source_id!r} does not exist"}
    if source.get("science_contract_hash") != campaign.get("science_contract_hash"):
        return None, {"status": "INCOMPATIBLE_SOURCE",
                      "reason": "source and cartography campaigns do not share the same science contract"}
    source_candidates = repo.candidates(source_id)
    all_by_id = {row["candidate_id"]: row for row in source_candidates}
    all_by_id.update({row["candidate_id"]: row for row in candidates})
    summaries: dict[str, list[dict]] = {}
    source_version = repo.campaign_analysis_contract(source_id)
    current_id = campaign["campaign_id"]
    current_version = repo.campaign_analysis_contract(current_id)
    if source_version != current_version:
        return None, {"status": "INCOMPATIBLE_SOURCE",
                      "reason": f"analysis contract differs: source={source_version}, current={current_version}"}
    summaries.update(repo.campaign_rung_summaries(source_id, source_version))
    summaries.update(repo.campaign_rung_summaries(current_id, current_version))
    observations = build_observations(all_by_id.values(), summaries,
                                      metric=str(config.get("metric") or "d_s"))
    plan = cartography_plan(observations, config)
    plan["source_campaign_id"] = source_id
    plan["cartography_campaign_id"] = current_id
    plan["observations"] = len(observations)
    return observations, plan


def _normalized_anchor_rows(plan: dict) -> dict[str, list[dict]]:
    modes = {
        "boundary": list(plan.get("boundary_pairs") or []),
        "flow_edge": list(plan.get("flow_edges") or []),
        "resonance": list(plan.get("resonance_pairs") or []),
    }
    for rows in modes.values():
        maximum = max((float(row.get("score") or 0.0) for row in rows), default=0.0)
        for row in rows:
            row["priority"] = (float(row.get("score") or 0.0) / maximum) if maximum > 0 else 0.0
    return modes


def _cartography_probe_pool(rng: random.Random, need: int, spec: dict,
                            observations: list[dict], plan: dict,
                            existing: set[str], existing_physical: set[str]) -> list[tuple[dict, str, str, dict]]:
    cfg = dict((spec.get("proposer") or {}).get("cartography") or {})
    if plan.get("status") != "READY":
        return []
    by_id = {row["candidate_id"]: row for row in observations}
    modes = _normalized_anchor_rows(plan)
    fractions = {
        "boundary": float(cfg.get("boundary_fraction", 0.60)),
        "flow_edge": float(cfg.get("flow_edge_fraction", 0.25)),
        "resonance": float(cfg.get("resonance_fraction", 0.15)),
    }
    available = {mode: rows for mode, rows in modes.items() if rows and fractions[mode] > 0}
    if not available:
        return []
    weight_total = sum(fractions[mode] for mode in available)
    mode_names = list(available)
    mode_weights = [fractions[mode] / weight_total for mode in mode_names]
    multiplier = max(1, int(cfg.get("pool_multiplier", 10)))
    target = max(need, need * multiplier)
    sigma = float(cfg.get("local_jitter_sigma", 0.10))
    edge_sigma = float(cfg.get("edge_jitter_sigma", 0.18))
    pool: list[tuple[dict, str, str, dict]] = []
    attempts = 0
    while len(pool) < target and attempts < max(400, target * 80):
        attempts += 1
        mode = rng.choices(mode_names, mode_weights)[0]
        rows = available[mode]
        priorities = [max(0.05, float(row.get("priority") or 0.0)) for row in rows]
        anchor = rng.choices(rows, priorities)[0]
        if mode == "flow_edge":
            parent_id = str(anchor["candidate_id"])
            allow_discrete = True
            local_sigma = edge_sigma
            anchor_ids = [parent_id]
        else:
            anchor_ids = [str(anchor["a"]), str(anchor["b"])]
            parent_id = rng.choice(anchor_ids)
            allow_discrete = False
            local_sigma = sigma
        parent = by_id.get(parent_id)
        if parent is None:
            continue
        child, perturbation = local_perturbation(
            parent["spec"], rng, sigma=local_sigma, allow_discrete_step=allow_discrete)
        child = dsl.normalize(child)
        if dsl.validate(child, complexity_budget=spec.get("complexity_budget", 6),
                        operator_whitelist=spec.get("operator_whitelist")):
            continue
        fingerprint = dsl.fingerprint(child)
        if fingerprint in existing:
            continue
        physical_id = equilibrium_identity(child)[0]
        if physical_id in existing_physical:
            continue
        existing.add(fingerprint)
        existing_physical.add(physical_id)
        coords = proposal_coordinates(child)
        source = f"cartography-{mode.replace('_', '-')}"
        assessment = {
            "version": CARTOGRAPHY_VERSION,
            "category": source,
            "would_admit": True,
            "score": float(anchor.get("priority") or 0.0),
            "allocation_weight": max(0.05, float(anchor.get("priority") or 0.0)),
            "family_id": coords["family_id"],
            "family_label": coords["family_label"],
            "coefficient_region_id": coords["coefficient_region_id"],
            "coefficient_region_label": coords["coefficient_region_label"],
            "physical_equivalence_id": coords["physical_equivalence_id"],
            "scaling_profile": coords["scaling_profile"],
            "cartography": {
                "mode": mode,
                "source_campaign_id": plan.get("source_campaign_id"),
                "checkpoint": plan.get("checkpoint"),
                "anchor_candidate_ids": anchor_ids,
                "anchor": {key: value for key, value in anchor.items() if key != "priority"},
                "perturbation": perturbation,
            },
            "reasons": [
                "local probe selected from the measured dimensional-flow map",
                f"cartography mode={mode}",
                "no target dimension or predeclared basin boundary was used",
            ],
        }
        pool.append((child, parent_id, source, assessment))
    return pool


def _select_cartography_pool(rng: random.Random,
                             pool: list[tuple[dict, str, str, dict]], need: int,
                             config: dict) -> list[tuple[dict, str, str, dict]]:
    remaining = list(pool)
    selected = []
    parent_counts: Counter = Counter()
    mode_counts: Counter = Counter()
    fractions = {
        "boundary": float(config.get("boundary_fraction", 0.60)),
        "flow_edge": float(config.get("flow_edge_fraction", 0.25)),
        "resonance": float(config.get("resonance_fraction", 0.15)),
    }
    while remaining and len(selected) < need:
        total_fraction = sum(value for key, value in fractions.items()
                             if any((item[3].get("cartography") or {}).get("mode") == key for item in remaining))
        weights = []
        for _, parent, _, assessment in remaining:
            mode = (assessment.get("cartography") or {}).get("mode")
            target_share = fractions.get(mode, 0.0) / max(total_fraction, 1e-12)
            current_share = mode_counts[mode] / max(1, len(selected))
            deficit = max(0.10, 1.0 + 2.0 * (target_share - current_share))
            priority = max(0.05, float(assessment.get("allocation_weight") or 0.0))
            diversity = 0.45 ** parent_counts[parent]
            weights.append(priority * deficit * diversity)
        index = rng.choices(range(len(remaining)), weights)[0]
        item = remaining.pop(index)
        selected.append(item)
        parent_counts[item[1]] += 1
        mode_counts[(item[3].get("cartography") or {}).get("mode")] += 1
    return selected


def _top_up_cartography(repo: Repo, log: Log, campaign: dict, candidates: list[dict],
                        need: int, rng: random.Random) -> bool:
    spec = campaign["spec"]
    cfg = dict((spec.get("proposer") or {}).get("cartography") or {})
    if not cfg.get("enabled", False):
        return False
    observations, plan = _cartography_evidence(repo, campaign, candidates, cfg)
    if observations is None or plan.get("status") != "READY":
        log.write("cartography_waiting", campaign=campaign["campaign_id"][:17],
                  status=plan.get("status"), reason=str(plan.get("reason"))[:240],
                  checkpoint=plan.get("checkpoint"))
        return True
    source_candidates = repo.candidates(str(cfg["source_campaign_id"]))
    all_candidates = [*source_candidates, *candidates]
    existing = {row["candidate_id"] for row in all_candidates}
    existing_physical = {equilibrium_identity(row["spec"])[0] for row in all_candidates}
    pool = _cartography_probe_pool(rng, need, spec, observations, plan,
                                   existing, existing_physical)
    selected = _select_cartography_pool(rng, pool, need, cfg)
    if not selected:
        log.write("cartography_waiting", campaign=campaign["campaign_id"][:17],
                  status="NO_UNIQUE_LOCAL_PROBES",
                  reason="local perturbation pool produced no new physical Hamiltonians",
                  checkpoint=plan.get("checkpoint"))
        return True
    selected_ids = {dsl.fingerprint(item[0]) for item in selected}
    pool_id = f"{campaign['campaign_id']}:cartography:{uuid.uuid4().hex}"
    for pool_index, (pool_spec, pool_parent, pool_source, _assessment) in enumerate(pool):
        fingerprint = dsl.fingerprint(pool_spec)
        repo.insert_proposal_exposure(
            campaign["campaign_id"],
            _proposal_exposure_with_operator_metadata(
                pool_spec, source=pool_source, lineage_parent=pool_parent,
                pool_id=pool_id, pool_index=pool_index,
                selected=fingerprint in selected_ids,
                candidate_id=fingerprint if fingerprint in selected_ids else None),
        )
    admitted_modes = Counter()
    for candidate_spec, parent, source, assessment in selected:
        fingerprint = dsl.fingerprint(candidate_spec)
        assessment["unfiltered"] = in_audit_sample(fingerprint, Policy.from_spec(campaign["spec"]).audit_fraction)
        repo.insert_candidate(fingerprint, campaign["campaign_id"], candidate_spec,
                              candidate_spec["dynamics"]["kind"], dsl.complexity(candidate_spec),
                              CandidateState.PROPOSED.value, lineage_parent=parent,
                              unfiltered=bool(assessment["unfiltered"]))
        repo.insert_proposal_assessment(
            campaign["campaign_id"], fingerprint, CARTOGRAPHY_VERSION,
            source, CARTOGRAPHY_ASSESSMENT_MODE, assessment,
        )
        mode = (assessment.get("cartography") or {}).get("mode") or "unknown"
        admitted_modes[mode] += 1
        log.write("cartography_proposed", candidate=fingerprint[:12], source=source,
                  parent=parent[:12], mode=mode,
                  checkpoint_n=(plan.get("checkpoint") or {}).get("n"),
                  anchor_score=round(float(assessment.get("score") or 0.0), 4),
                  perturbation=(assessment.get("cartography") or {}).get("perturbation"))
    repo.emit("cartography_candidates_proposed", {
        "campaign_id": campaign["campaign_id"], "count": len(selected),
        "source_campaign_id": cfg["source_campaign_id"],
        "checkpoint": plan.get("checkpoint"), "probe_modes": dict(admitted_modes),
        "cartography_version": CARTOGRAPHY_VERSION,
    })
    return True


def _top_up_blind(repo: Repo, log: Log, campaign: dict, candidates: list[dict], need: int,
                  rng: random.Random, existing: set[str], existing_physical: set[str]) -> None:
    spec = campaign["spec"]
    campaign_id = campaign["campaign_id"]
    grid = (spec.get("search_policy") or {}).get("grid")
    whitelist = list(spec.get("operator_whitelist") or dsl.OPERATORS)
    budget = spec.get("complexity_budget")
    if campaign_control.survey_state(repo, campaign_id) is not None:
        return
    ledger: list[dict] = []
    stops: list[dict] = []
    version = blind_identity_version(grid)
    seed_identity = campaign.get("search_seed")
    if seed_identity is None:
        seed_identity = campaign_id
    laws = blind_batch(rng, need, whitelist, grid, existing, existing_physical,
                       fingerprint=dsl.fingerprint,
                       physical_identity=lambda law: equilibrium_identity(law, version=version)[0],
                       complexity_budget=int(budget) if budget is not None else None, ledger=ledger,
                       streams=lambda index: law_stream(seed_identity, index), first_index=len(candidates),
                       stops=stops)
    for stop in stops:
        if stop["unfilled"]:
            unfilled = {"campaign_id": campaign_id, "stream_index": stop["stream_index"], "stratum": stop["unfilled"],
                        "valid_draws": stop["valid"], "reason": stop["reason"]}
            log.write(STRATUM_UNFILLED, **{k: v for k, v in unfilled.items() if k != "campaign_id"},
                      campaign=campaign_id[:17])
            repo.emit(STRATUM_UNFILLED, unfilled)
    from graph_scale_dynamics.db.draw_ledger import insert_proposal_draws
    if ledger and "stream_index" in ledger[0]:
        for index in sorted({row["stream_index"] for row in ledger}):
            insert_proposal_draws(repo, campaign_id, index, [row for row in ledger if row["stream_index"] == index])
    else:
        insert_proposal_draws(repo, campaign_id, len(candidates), ledger)
    family_cfg = dict(spec.get("proposer", {}).get("family_memory") or {})
    pool_id = f"{campaign_id}:{uuid.uuid4().hex}"
    admitted = []
    for pool_index, law in enumerate(laws):
        fingerprint = dsl.fingerprint(law)
        repo.insert_proposal_exposure(
            campaign_id,
            _proposal_exposure_with_operator_metadata(
                law, source="blind", lineage_parent=None, pool_id=pool_id,
                pool_index=pool_index, selected=True, candidate_id=fingerprint,
            ),
        )
        assessment = dict(proposal_assessment(law, {}, family_cfg))
        assessment["coupling_strength"] = round(coupling_strength(law, REFERENCE_N), 6)
        assessment["coupling_stratum"] = coupling_stratum(law, REFERENCE_N)
        assessment["beta"] = law["dynamics"]["beta"]
        assessment["declared_sweeps"] = law["dynamics"]["sweeps"]
        assessment["search_policy"] = "blind"
        assessment["selection_weight"] = 1.0
        assessment["pool_selection_probability"] = 1.0
        assessment["unfiltered"] = in_audit_sample(fingerprint, Policy.from_spec(spec).audit_fraction)
        repo.insert_candidate(fingerprint, campaign_id, law, law["dynamics"]["kind"],
                              dsl.complexity(law), CandidateState.PROPOSED.value,
                              lineage_parent=None, unfiltered=bool(assessment["unfiltered"]))
        repo.insert_proposal_assessment(campaign_id, fingerprint, FAMILY_MEMORY_VERSION,
                                        "blind", "off", assessment)
        admitted.append(law)
        log.write("proposed", candidate=fingerprint[:12], source="blind",
                  family=assessment["family_id"],
                  coefficient_region=assessment.get("coefficient_region_id"),
                  scaling_profile=assessment.get("scaling_profile"),
                  search_policy="blind")
    if admitted:
        repo.emit("candidates_proposed", {
            "campaign_id": campaign_id, "count": len(admitted),
            "search_policy": "blind", "proposal_intelligence_mode": "off",
            "scaling_profiles": dict(Counter(scaling_profile(law) for law in admitted)),
        })
    stopped = stops[-1] if stops and stops[-1]["reason"] != PRODUCED else None
    if len(admitted) < need:
        log.write("blind_batch_short", campaign=campaign_id[:17], wanted=need, produced=len(admitted),
                  stopped=stopped and stopped["reason"], stream=stopped and stopped["stream_index"],
                  valid_draws=sum(stop["valid"] for stop in stops))
    if admitted:
        campaign_control.clear_survey(repo, campaign_id)
    elif (need > 0 and existing_physical and not blind_is_continuous(grid) and stopped is not None
          and stopped["reason"] == DUPLICATES and not any(
            str(row.get("outcome")).startswith("predicted:") for row in ledger)):
        campaign_control.record_survey_complete(
            repo, campaign_id, held=len(existing_physical),
            wanted=int(spec.get("proposer", {}).get("pool_min", 4)),
            rounds=sum(stop["valid"] for stop in stops))


def serve_campaigns(repo: Repo, log: Log, targets: list[dict]) -> dict:
    windows = {}
    for campaign in targets:
        try:
            window = top_up(repo, log, campaign)
        except DatabaseOperationalError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            log.write("top_up_failed", campaign=str(campaign["campaign_id"]), error=error)
            try:
                repo.conn.rollback_if_open()
            except Exception:
                pass
            windows[str(campaign["campaign_id"])] = {"error": error}
            continue
        if window is not None:
            windows[str(campaign["campaign_id"])] = window
    return windows


def top_up(repo: Repo, log: Log, campaign: dict) -> dict | None:
        spec = campaign["spec"]
        if not spec.get("proposer"):
            return None
        pool_min = int(spec.get("proposer", {}).get("pool_min", 4))
        max_active = int(spec.get("max_active_candidates", 6))
        campaign_id = campaign["campaign_id"]
        window = admission(without_the_waiting(repo.live_laws_latest_decision(campaign_id),
                                               waiting_to_learn(repo, str(campaign_id))), pool_min=pool_min,
                           max_active=max_active, top_base_n=Policy.from_spec(spec).base_sizes[-1])
        _note_admission(log, campaign_id, window)
        if window["open"]:
            from graph_scale_dynamics.operations import study
            if study.budget_reached(repo, campaign_id):
                return window
            proposed_count = window["counts"][SLOT_PROPOSED]
            candidates = repo.candidates(campaign_id)
            room = study.budget_room(repo, campaign_id, len(candidates))
            if room is not None and room <= 0:
                return window
            seed_identity = campaign.get("search_seed")
            if seed_identity is None:
                seed_identity = campaign_id
            rng = random.Random(campaign_rng_seed(seed_identity, len(candidates)))
            existing = {c["candidate_id"] for c in candidates}
            identity = blind_identity_version((spec.get("search_policy") or {}).get("grid"))
            existing_physical = {equilibrium_identity(c["spec"], version=identity)[0] for c in candidates}
            need = pool_min - proposed_count if room is None else min(pool_min - proposed_count, room)
            if _top_up_cartography(repo, log, campaign, candidates, need, rng):
                return window
            from graph_scale_dynamics.scheduling.search_policy import kind_of
            declared_kind = kind_of(spec)
            if declared_kind is not None and not declared_kind.proposes:
                return window
            if declared_kind is not None and declared_kind.name == "blind":
                _top_up_blind(repo, log, campaign, candidates, need, rng, existing, existing_physical)
                return window
            batch = []
            profile_counts = Counter(scaling_profile(candidate["spec"]) for candidate in candidates)
            coupling_counts = Counter(coupling_stratum(candidate["spec"])
                                      for candidate in candidates)
            coupling_fractions, coupling_policy = _coupling_policy(spec)
            generation_coupling_counts = Counter(coupling_counts)
            family_cfg = dict(spec.get("proposer", {}).get("family_memory") or {})
            mode = str(family_cfg.get("mode", "shadow")).lower()
            if mode not in {"off", "shadow", "active"}:
                mode = "shadow"
            decisions_by = repo.latest_engine_decisions(campaign_id)
            memory = build_family_memory(candidates, decisions_by, family_cfg)
            parents = lineage_parents(candidates)
            attach_flow_fitness(repo, campaign_id, spec, parents)
            targets = _profile_targets(spec)
            generation_need = max(0, need - len(batch))
            if mode == "active":
                generation_need *= int(family_cfg.get("candidate_pool_multiplier", 8))
            batch += generate_batch(
                rng, generation_need, spec, existing, parents, profile_counts=profile_counts,
                existing_physical=existing_physical, coupling_counts=generation_coupling_counts,
            )
            selected = select_batch(
                rng, batch, need, memory, family_cfg, profile_counts, targets, mode,
                coupling_counts=coupling_counts,
                coupling_target_fractions=coupling_fractions,
                coupling_policy=coupling_policy,
            )
            best_parent = max((p.get("fitness", {}).get("score", 0.0) for p in parents),
                              default=0.0)
            log.write("search_state", campaign=campaign_id[:17],
                      coupling_coverage=dict(coupling_counts),
                      coupling_policy_epoch=coupling_policy.get("epoch"),
                      coupling_targets=coupling_fractions,
                      best_parent_fitness=round(best_parent, 4),
                      parents=len(parents))

            admitted = []
            pool_id = f"{campaign_id}:{uuid.uuid4().hex}"
            selected_ids = {dsl.fingerprint(item[0]) for item in selected}
            selected_candidate_ids = {dsl.fingerprint(item[0]): dsl.fingerprint(item[0]) for item in selected}
            for pool_index, (pool_spec, pool_parent, pool_source) in enumerate(batch):
                fingerprint = dsl.fingerprint(pool_spec)
                repo.insert_proposal_exposure(
                    campaign_id,
                    _proposal_exposure_with_operator_metadata(
                        pool_spec, source=pool_source, lineage_parent=pool_parent,
                        pool_id=pool_id, pool_index=pool_index,
                        selected=fingerprint in selected_ids,
                        candidate_id=selected_candidate_ids.get(fingerprint),
                    ),
                )
            for candidate_spec, parent, source, assessment in selected:
                fingerprint = dsl.fingerprint(candidate_spec)
                assessment["unfiltered"] = in_audit_sample(fingerprint, Policy.from_spec(spec).audit_fraction)
                repo.insert_candidate(fingerprint, campaign_id, candidate_spec,
                                      candidate_spec["dynamics"]["kind"],
                                      dsl.complexity(candidate_spec),
                                      CandidateState.PROPOSED.value, lineage_parent=parent,
                                      unfiltered=bool(assessment["unfiltered"]))
                repo.insert_proposal_assessment(
                    campaign_id, fingerprint, FAMILY_MEMORY_VERSION, source, mode, assessment
                )
                admitted.append((candidate_spec, parent, source))
                log.write(
                    "proposed", candidate=fingerprint[:12], source=source,
                    parent=(parent or "")[:12], family=assessment["family_id"],
                    coefficient_region=assessment.get("coefficient_region_id"),
                    scaling_profile=assessment.get("scaling_profile"),
                    physical_classification=assessment.get("physical_classification"),
                    physical_equivalence=assessment.get("physical_equivalence_id"),
                    proposal_mode=mode, family_category=assessment.get("category"),
                    coupling_policy_epoch=(assessment.get("coupling_policy") or {}).get("epoch"),
                    coupling_target_fraction=assessment.get("coupling_target_fraction"),
                    allocation_weight=round(float(assessment.get("allocation_weight") or 0.0), 4),
                    selection_weight=round(float(assessment.get("selection_weight") or 0.0), 4),
                )
            if admitted:
                repo.emit("candidates_proposed", {
                    "campaign_id": campaign_id, "count": len(admitted),
                    "proposal_intelligence_mode": mode,
                    "coupling_policy": coupling_policy,
                    "scaling_profiles": dict(Counter(
                        scaling_profile(candidate_spec)
                        for candidate_spec, _, _ in admitted
                    )),
                })
        return window


if __name__ == "__main__":
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    raise SystemExit(main())
