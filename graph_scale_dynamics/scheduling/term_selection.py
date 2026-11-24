from __future__ import annotations

import random
from collections import Counter

from graph_scale_dynamics.dsl.dsl import OPERATORS
from graph_scale_dynamics.research.hamiltonian_preflight import (
    DEGREE_SEQUENCE_OPERATORS, effective_basis,
)

TERM_SELECTION_CONTRACT = "gsd-term-selection-1"

ADMISSION_DRAWS = 64

PREVIEW_DRAWS = 240

LOW_YIELD_FRACTION = 0.05

SPACE_DRAWS = 600

SPACE_COVERAGE = 0.995


def _probe_law(op: str) -> dict:
    params = {"k": 2} if "k" in (OPERATORS[op]["params"] or {}) else {}
    return {"dsl_version": 1, "init": "empty",
            "terms": [{"op": op, "params": params, "coeff": {"c0": 1.0, "scale": "one"}}],
            "dynamics": {"kind": "equilibrium", "beta": 1.0}}


def _reduces_to(op: str) -> list[str]:
    basis = sorted({str(term["op"]) for term in effective_basis(_probe_law(op))})
    return [] if basis == [op] else basis


def _sparse_phase_operators() -> frozenset[str]:
    from graph_scale_dynamics.services.proposer.blind import _SPARSE_PHASE_DEGREE_OPS
    return frozenset(_SPARSE_PHASE_DEGREE_OPS)


def catalogue() -> list[dict]:
    sparse = _sparse_phase_operators()
    out = []
    for op, meta in OPERATORS.items():
        out.append({
            "op": op,
            "cost": int(meta["cost"]),
            "params": {name: list(bounds) for name, bounds in (meta["params"] or {}).items()},
            "group": ("degree_sequence" if op in DEGREE_SEQUENCE_OPERATORS else "topology"),
            "defines_sparse_phase": op in sparse,
            "reduces_to": _reduces_to(op),
        })
    return out


def _draw_sample(whitelist: list[str], grid: dict | None, complexity_budget: int | None,
                 draws: int, seed: int) -> dict:
    from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.services.proposer import blind
    rng = random.Random(seed)
    drawn = 0
    fingerprints: set[str] = set()
    physical: Counter[str] = Counter()
    error = None
    for _ in range(max(1, int(draws))):
        try:
            law = dsl.normalize(blind.blind_law(rng, list(whitelist), grid,
                                                complexity_budget=complexity_budget,
                                                max_attempts=40))
        except blind.GridError as refused:
            error = str(refused)
            continue
        drawn += 1
        fingerprints.add(dsl.fingerprint(law))
        physical[equilibrium_identity(law, version=blind.identity_version(grid))[0]] += 1
    attempted = max(1, int(draws))
    collapse = (1.0 - len(physical) / len(fingerprints)) if fingerprints else None
    singletons = sum(1 for count in physical.values() if count == 1)
    return {"attempts": attempted, "laws_drawn": drawn,
            "yield_fraction": drawn / attempted,
            "distinct_laws": len(fingerprints), "distinct_physical": len(physical),
            "seen_once": singletons,
            "coverage": (1.0 - singletons / drawn) if drawn else 0.0,
            "physical_collapse_fraction": collapse, "last_refusal": error}


def _entangled(whitelist: list[str]) -> list[dict]:
    out = []
    for op in whitelist:
        if op not in OPERATORS:
            continue
        reduction = _reduces_to(op)
        if reduction:
            out.append({"op": op, "reduces_to": reduction,
                        "also_selected": sorted(set(reduction) & set(whitelist))})
    return out


def _space_estimate(whitelist: list[str], grid: dict | None, complexity_budget: int | None,
                    *, draws: int, seed: int) -> dict:
    from graph_scale_dynamics.services.proposer.blind import is_continuous
    sample = _draw_sample(whitelist, grid, complexity_budget, draws, seed)
    distinct = int(sample["distinct_physical"])
    drawn = max(1, int(sample["laws_drawn"]))
    coverage = float(sample["coverage"])
    continuous = is_continuous(grid)
    saturated = (not continuous) and coverage >= SPACE_COVERAGE
    return {"distinct_physical": distinct, "draws": drawn, "saturated": bool(saturated),
            "coverage": coverage, "seen_once": int(sample["seen_once"]),
            "continuous": bool(continuous), "exhaustive": bool(saturated)}


def _parameterless(selected: list[str]) -> list[str]:
    return [op for op in selected if not (OPERATORS.get(op, {}).get("params") or {})]


def space_advice(selected: list[str], space: dict, grid: dict | None,
                 complexity_budget: int | None, pool_min: int | None,
                 *, seed: int = 0) -> list[dict]:
    from graph_scale_dynamics.services.proposer.blind import (
        DEFAULT_GRID, GRID_INTERVAL_KEYS, interval_of,
    )
    out: list[dict] = []
    held = int(space.get("distinct_physical") or 0)
    declared = dict(DEFAULT_GRID, **(grid or {}))

    listed = [key for key in ("magnitudes", "betas")
              if key in GRID_INTERVAL_KEYS and interval_of(declared.get(key)) is None]
    if listed:
        spans = {}
        for key in listed:
            values = [abs(float(v)) for v in declared[key] if float(v)]
            spans[key] = {"min": min(values), "max": max(values)}
        widened = _space_estimate(selected, dict(declared, **spans), complexity_budget,
                                  draws=SPACE_DRAWS, seed=seed)
        out.append({"change": "search_policy.grid." + " and ".join(listed), "keeps_terms": True,
                    "detail": ("draw the coupling from an interval instead of a list: "
                               + ", ".join(f"{key} {spans[key]['min']:g} to {spans[key]['max']:g}"
                                           for key in listed)
                               + ". The same range, sampled continuously, so the search has no "
                                 "last law"),
                    "from": held, "to": None,
                    "sampled": int(widened["distinct_physical"]),
                    "continuous": True})

    unused = [scale for scale in DEFAULT_GRID["scales"] if scale not in declared["scales"]]
    if unused:
        widened = _space_estimate(selected, dict(declared, scales=DEFAULT_GRID["scales"]),
                                  complexity_budget, draws=SPACE_DRAWS, seed=seed)
        if int(widened["distinct_physical"]) > held:
            out.append({"change": "search_policy.grid.scales", "keeps_terms": True,
                        "detail": "add " + ", ".join(unused) + " to the grid's scales",
                        "from": held, "to": int(widened["distinct_physical"])})

    if len(selected) == 1 and _parameterless(selected):
        combinations = len(declared["magnitudes"]) * len(declared["betas"])
        out.append({"change": "none: this is the physics", "keeps_terms": True,
                    "detail": (f"one parameterless term makes a law beta * c * {selected[0]}, and "
                               "the equilibrium depends only on that product, so strength and "
                               f"temperature are one knob. The grid offers {combinations} "
                               "strength/temperature pairs and both ladders are geometric, so "
                               f"they land on {held} distinct values"),
                    "from": combinations, "to": held})

    if pool_min and held < int(pool_min):
        out.append({"change": "proposer.pool_min", "keeps_terms": True,
                    "detail": f"keep a pool of {held} or fewer so the pool can fill",
                    "from": int(pool_min), "to": held})
    return out


def preflight(whitelist: list[str], grid: dict | None = None,
              complexity_budget: int | None = None, *, pool_min: int | None = None,
              draws: int = PREVIEW_DRAWS, seed: int = 0) -> dict:
    selected = [str(op) for op in (whitelist or [])]
    problems: list[str] = []
    notes: list[str] = []
    unknown = sorted(set(selected) - set(OPERATORS))
    if not selected:
        problems.append("select at least one term")
    if unknown:
        problems.append(f"unknown terms: {unknown}")
    if len(selected) != len(set(selected)):
        problems.append("a term may only be selected once")

    sample: dict = {}
    space: dict = {}
    advice: list[dict] = []
    sparse = _sparse_phase_operators()
    if not problems and isinstance(grid, dict) and "strata" in grid:
        from graph_scale_dynamics.research.strata import strata_problems
        problems.extend(problem for problem in strata_problems(grid, selected) if "selected term" in problem)
    if not problems:
        sample = _draw_sample(selected, grid, complexity_budget, draws, seed)
        if sample["laws_drawn"] == 0:
            missing = sorted(sparse - set(selected))
            problems.append(
                "this selection cannot produce a law: no law it can write defines a sparse "
                "phase, so every draw is refused"
                + (f". Adding any one of {missing} would fix it" if missing else "")
            )
        elif sample["yield_fraction"] < LOW_YIELD_FRACTION:
            notes.append(
                f"only {sample['yield_fraction']:.1%} of draws are valid; the search will "
                "spend most of its proposals on rejections")
        collapse = sample.get("physical_collapse_fraction")
        if collapse is not None and collapse > 0.1:
            notes.append(
                f"{collapse:.0%} of drawn laws are the same physics written differently and "
                "are discarded by the proposer's own deduplication")

    if not problems and sample:
        space = _space_estimate(selected, grid, complexity_budget, draws=SPACE_DRAWS, seed=seed)
        wanted = int(pool_min) if pool_min else None
        if space.get("continuous"):
            notes.append(
                "this grid draws its coupling from an interval, so the search has no last "
                "law: the campaign runs until it is paused rather than until it is surveyed")
        elif wanted and space["exhaustive"] and space["distinct_physical"] < wanted:
            notes.append(
                f"this selection can write {space['distinct_physical']} physically distinct laws "
                f"and the campaign keeps a pool of {wanted}: the pool never fills, and the "
                "campaign finishes by surveying the space rather than by running out of budget")
        elif wanted and space["exhaustive"] and space["distinct_physical"] < wanted * 4:
            notes.append(
                f"the whole space is about {space['distinct_physical']} distinct laws against a "
                f"pool of {wanted}; this campaign will run out of new laws quickly")
        if space.get("exhaustive"):
            advice = space_advice(selected, space, grid, complexity_budget, wanted, seed=seed)

    entangled = _entangled(selected)
    for row in entangled:
        if row["also_selected"]:
            notes.append(
                f"{row['op']} is exactly {' + '.join(row['reduces_to'])}, which you have also "
                "selected: these are not independent terms")
        else:
            notes.append(
                f"{row['op']} is exactly {' + '.join(row['reduces_to'])}, so "
                f"{' and '.join(row['reduces_to'])} is explored whether or not it is selected")

    return {
        "contract": TERM_SELECTION_CONTRACT,
        "selected": selected,
        "status": "REFUSED" if problems else "PASS",
        "problems": problems,
        "notes": notes,
        "sample": sample,
        "space": space,
        "advice": advice,
        "pool_min": int(pool_min) if pool_min else None,
        "entangled": entangled,
        "sparse_phase_selected": sorted(set(selected) & sparse),
        "reading": ("A selection is workable when the drawer can write a law with it and the "
                    "space it can write is bigger than the pool the campaign keeps. Both "
                    "figures come from drawing real laws through `blind_law`, not from a "
                    "second copy of its rules."),
    }


def selection_problems(spec: dict) -> list[str]:
    from graph_scale_dynamics.scheduling.search_policy import kind_of
    if not isinstance(spec, dict):
        return []
    declared = kind_of(spec)
    if declared is not None and not declared.proposes:
        return []
    whitelist = spec.get("operator_whitelist")
    if not isinstance(whitelist, list) or not whitelist:
        return []
    if sorted(set(whitelist) - set(OPERATORS)) or len(whitelist) != len(set(whitelist)):
        return []
    budget = spec.get("complexity_budget")
    grid = (spec.get("search_policy") or {}).get("grid")
    pool_min = (spec.get("proposer") or {}).get("pool_min")
    try:
        verdict = preflight(list(whitelist), grid if isinstance(grid, dict) else None,
                            int(budget) if isinstance(budget, int) else None,
                            pool_min=int(pool_min) if isinstance(pool_min, int) else None,
                            draws=ADMISSION_DRAWS)
    except (KeyError, TypeError, ValueError):
        return []
    return list(verdict["problems"])


def selection_diff(parent: list[str] | None, child: list[str]) -> dict:
    before = [op for op in (parent or [])]
    after = [op for op in child]
    added = [op for op in after if op not in before]
    removed = [op for op in before if op not in after]
    parts = []
    if added:
        parts.append("added " + ", ".join(added))
    if removed:
        parts.append("removed " + ", ".join(removed))
    return {"added": added, "removed": removed, "unchanged": [op for op in after if op in before],
            "summary": "; ".join(parts) or "same terms as the parent"}
