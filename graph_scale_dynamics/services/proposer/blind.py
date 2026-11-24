from __future__ import annotations

import json
import math
import random
from functools import lru_cache
from pathlib import Path

from graph_scale_dynamics.domain.randomness import derive_seed
from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.research.coupling import (
    REFERENCE_N, coupling_strength, sweeps_for_coupling,
)
from graph_scale_dynamics.research.hamiltonian_preflight import PREFLIGHT_VERSION, ZERO_TEMPERATURE_FOLDED

GRID_SAMPLER = "sampler"
SAMPLER_631 = "blind-sampler-2"
SAMPLERS = (SAMPLER_631,)
LAW_STREAM_CONTRACT = "proposer-law-1"
STRATUM_DRAWS = 20000
GRID_RETRIES = 50
SURVEY_DUPLICATES = 1000
PRODUCED, DUPLICATES, GRID_EXHAUSTED = "produced", "duplicates", "grid_retries"
STRATUM_UNFILLED = "stratum_unfilled"
GRID_UNITS, GRID_UNIT_TABLE = "units", "unit_table"
NATURAL_UNITS = "natural"
OPERATOR_UNITS_FILE = Path(__file__).resolve().parents[2] / "resources" / "calibration" / "operator_units.json"


def sampler_of(grid: dict | None) -> str | None:
    value = (grid or {}).get(GRID_SAMPLER)
    return str(value) if value else None


def identity_version(grid: dict | None) -> str:
    return ZERO_TEMPERATURE_FOLDED if sampler_of(grid) == SAMPLER_631 else PREFLIGHT_VERSION


def law_stream(search_seed, index: int) -> random.Random:
    return random.Random(derive_seed("proposer-law", str(search_seed), int(index), LAW_STREAM_CONTRACT))


@lru_cache(maxsize=1)
def operator_units() -> dict:
    return json.loads(OPERATOR_UNITS_FILE.read_text(encoding="utf-8"))


def _natural(grid: dict) -> bool:
    return grid.get(GRID_UNITS) == NATURAL_UNITS

DEFAULT_GRID: dict = {
    "term_counts": [1, 2, 3, 4],
    "signs": [-1, 1],
    "magnitudes": [0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
    "scales": ["one", "log_N", "inv_log_N", "inv_N", "inv_sqrt_N", "power"],
    "power_exponents": [-2.0, -1.5, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 1.5, 2.0],
    "anchor_k": list(range(2, 33)),
    "betas": [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0],
    "base_sweeps": 30,
    "move_mix": dict(dsl.DEFAULT_MOVE_MIX),
}

GRID_LIST_KEYS = ("term_counts", "signs", "magnitudes", "scales",
                  "power_exponents", "anchor_k", "betas")

GRID_INTERVAL_KEYS = ("magnitudes", "betas", "power_exponents", "anchor_k")

GRID_INTEGER_KEYS = ("anchor_k",)

GRID_PER_TERM_KEYS = ("magnitudes", "signs", "scales", "power_exponents", "anchor_k")

GRID_PER_TERM = "per_term"

GRID_DYNAMICS_KEYS = ("localities", "local_moves", "zero_temperature", "swap_shares")
_SHARE_KEYS = ("localities", "swap_shares")

DRAW_SIGNIFICANT_FIGURES = 6

_POSITIVE_ONLY_OPS = frozenset({"degree_anchor_abs", "degree_fourth_sum"})
_SPARSE_PHASE_DEGREE_OPS = frozenset({
    "degree_anchor", "degree_square_sum", "wedge_count", "degree_cube_sum", "degree_fourth_sum",
})


class GridError(ValueError):
    pass


def _interval_problems(key: str, interval: dict) -> list[str]:
    from graph_scale_dynamics.dsl.dsl import _COEF_BOUND, _POWER_BOUNDS
    where = f"search_policy.grid.{key}"
    bounds = [interval.get("min"), interval.get("max")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in bounds):
        return [f"{where} interval needs finite numeric min and max"]
    low, high = float(bounds[0]), float(bounds[1])
    if high <= low:
        return [f"{where} interval max must be above min"]
    spacing = interval.get("spacing")
    if spacing is not None and spacing not in {"log", "linear"}:
        return [f"{where} spacing must be log or linear"]
    problems = []
    if key in ("magnitudes", "betas"):
        if low <= 0:
            problems.append(f"{where} interval must stay above zero")
        if key == "magnitudes" and high > _COEF_BOUND:
            problems.append(f"{where} interval max exceeds the DSL coefficient bound {_COEF_BOUND}")
    if spacing == "log" and low <= 0:
        problems.append(f"{where} cannot be log-spaced through zero")
    if key == "power_exponents" and not (
            _POWER_BOUNDS[0] <= low and high <= _POWER_BOUNDS[1]):
        problems.append(f"{where} interval must lie inside {_POWER_BOUNDS}")
    if key in GRID_INTEGER_KEYS and high - low < 1:
        problems.append(f"{where} interval must span at least one whole number")
    return problems


def validate_grid(grid: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(grid, dict):
        return ["search_policy.grid must be an object"]
    for key in GRID_LIST_KEYS:
        values = grid.get(key)
        interval = interval_of(values) if key in GRID_INTERVAL_KEYS else None
        if interval is not None:
            problems.extend(_interval_problems(key, interval))
            continue
        if not isinstance(values, list) or not values:
            problems.append(
                f"search_policy.grid.{key} must be a non-empty list"
                + (" or an interval {min, max}" if key in GRID_INTERVAL_KEYS else ""))
            continue
        if key in ("term_counts", "anchor_k"):
            if not all(isinstance(v, int) and v > 0 for v in values):
                problems.append(f"search_policy.grid.{key} must be positive integers")
        elif key == "signs":
            if not set(values) <= {-1, 1}:
                problems.append("search_policy.grid.signs must be a subset of [-1, 1]")
        elif key == "scales":
            unknown = set(values) - {"one", "log_N", "inv_log_N", "inv_N", "inv_sqrt_N", "power"}
            if unknown:
                problems.append(f"search_policy.grid.scales has unknown entries: {sorted(unknown)}")
        else:
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                problems.append(f"search_policy.grid.{key} must be finite numbers")
            if key in ("magnitudes", "betas") and not all(v > 0 for v in values):
                problems.append(f"search_policy.grid.{key} must be positive")
    if not isinstance(grid.get("base_sweeps", 30), int) or grid.get("base_sweeps", 30) <= 0:
        problems.append("search_policy.grid.base_sweeps must be a positive integer")
    problems.extend(_dynamics_problems(grid))
    problems.extend(_per_term_problems(grid))
    problems.extend(_sampler_problems(grid))
    return problems


def _sampler_problems(grid: dict) -> list[str]:
    where = "search_policy.grid."
    problems: list[str] = []
    sampler = grid.get(GRID_SAMPLER)
    if sampler is not None and sampler not in SAMPLERS:
        problems.append(f"{where}{GRID_SAMPLER} must be one of {list(SAMPLERS)}")
    declared = sampler == SAMPLER_631
    from graph_scale_dynamics.research.strata import GRID_STRATA, strata_problems
    if GRID_STRATA in grid:
        if not declared:
            problems.append(f"{where}{GRID_STRATA} needs {GRID_SAMPLER} {SAMPLER_631}: only it draws by stratum")
        problems.extend(strata_problems(grid))
    if GRID_UNITS in grid or GRID_UNIT_TABLE in grid:
        if grid.get(GRID_UNITS) != NATURAL_UNITS:
            problems.append(f"{where}{GRID_UNITS} must be {NATURAL_UNITS!r} where it is declared")
        elif not declared:
            problems.append(f"{where}{GRID_UNITS} needs {GRID_SAMPLER} {SAMPLER_631}")
        else:
            table = operator_units()
            if grid.get(GRID_UNIT_TABLE) != table.get("version"):
                problems.append(f"{where}{GRID_UNIT_TABLE} must name the committed table, {table.get('version')!r} "
                                f"(resources/calibration/operator_units.json)")
    return problems


def _dynamics_problems(grid: dict) -> list[str]:
    problems: list[str] = []
    where = "search_policy.grid."
    for key in _SHARE_KEYS:
        if key not in grid:
            continue
        entry = grid[key]
        interval = interval_of(entry)
        if interval is not None:
            ends = [interval.get("min"), interval.get("max")]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                       for v in ends):
                problems.append(f"{where}{key} interval needs finite numeric min and max")
            elif not 0.0 <= float(ends[0]) < float(ends[1]) < 1.0:
                problems.append(f"{where}{key} interval must lie inside [0,1) with max above min")
            elif interval.get("spacing") not in (None, "linear", "log") or (
                    interval.get("spacing") == "log" and float(ends[0]) <= 0.0):
                problems.append(f"{where}{key} spacing must be linear, or log above zero")
        elif not isinstance(entry, list) or not entry or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) < 1.0
                for v in entry):
            problems.append(f"{where}{key} must be a non-empty list in [0,1) or an interval")
    if "local_moves" in grid:
        entry = grid["local_moves"]
        if not isinstance(entry, list) or not entry or not set(entry) <= set(dsl.LOCAL_MOVES):
            problems.append(f"{where}local_moves must be a non-empty subset of {list(dsl.LOCAL_MOVES)}")
    if "zero_temperature" in grid:
        entry = grid["zero_temperature"]
        if not isinstance(entry, list) or not entry or not all(isinstance(v, bool) for v in entry):
            problems.append(f"{where}zero_temperature must be a non-empty list of true and false")
    return problems


def draw_dynamics(rng: random.Random, grid: dict) -> dict:
    out: dict = {}
    if "localities" in grid:
        locality = _draw_share(rng, grid["localities"])
        if locality > 0.0:
            out["locality"] = locality
            if "local_moves" in grid:
                move = rng.choice(grid["local_moves"])
                if move != "toggle":
                    out["local_move"] = move
    if "zero_temperature" in grid and bool(rng.choice(grid["zero_temperature"])):
        out["zero_temperature"] = True
    if "swap_shares" in grid:
        swap = _draw_share(rng, grid["swap_shares"])
        rest = (1.0 - swap) / 2.0
        out["move_mix"] = {"add": rest, "delete": rest, "swap": swap}
    return out


def _draw_share(rng: random.Random, entry) -> float:
    interval = interval_of(entry)
    if interval is None:
        return float(draw_value(rng, entry))
    value = float(draw_value(rng, dict(interval, spacing=interval.get("spacing") or "linear")))
    return min(value, float(interval["max"]))


def _per_term_problems(grid: dict) -> list[str]:
    per_term = grid.get(GRID_PER_TERM)
    if per_term is None:
        return []
    if not isinstance(per_term, dict):
        return [f"search_policy.grid.{GRID_PER_TERM} must be an object of term name to grid"]
    from graph_scale_dynamics.dsl.dsl import OPERATORS
    problems: list[str] = []
    for op, override in per_term.items():
        where = f"search_policy.grid.{GRID_PER_TERM}.{op}"
        if op not in OPERATORS:
            problems.append(f"{where} is not a known operator")
            continue
        if not isinstance(override, dict) or not override:
            problems.append(f"{where} must be a non-empty grid")
            continue
        unknown = sorted(set(override) - set(GRID_PER_TERM_KEYS))
        if unknown:
            problems.append(
                f"{where} may only override {', '.join(GRID_PER_TERM_KEYS)}; got {unknown}")
            continue
        merged = dict(grid, **override)
        merged.pop(GRID_PER_TERM, None)
        problems.extend(problem.replace("search_policy.grid.", where + ".", 1)
                        for problem in validate_grid(merged)
                        if any(problem.startswith(f"search_policy.grid.{key}")
                               for key in override))
    return problems


def _has_sparse_phase(terms: list[dict]) -> bool:
    for term in terms:
        coeff = term.get("coeff") or {}
        if float(coeff.get("c0") or 0.0) <= 0:
            continue
        op = term["op"]
        if op in _SPARSE_PHASE_DEGREE_OPS:
            return True
        scale = coeff.get("scale")
        strong = scale == "log_N" or (scale == "power" and float(coeff.get("p") or 0.0) > 0)
        if op in ("edge_count", "degree_anchor_abs") and strong:
            return True
    return False


def _bounded_below(terms: list[dict]) -> bool:
    from graph_scale_dynamics.research.hamiltonian_preflight import effective_basis

    basis = effective_basis({"terms": terms, "dynamics": {"beta": 1.0}})

    def scale(row: dict) -> tuple:
        return row["scale"], row.get("p")

    quartic = {scale(row) for row in basis if row["op"] == "degree_fourth_sum" and row["coefficient"] > 0}
    return all(scale(row) in quartic for row in basis
               if row["op"] == "degree_square_sum" and row["coefficient"] < 0)


def _past_coefficient_bound(terms: list[dict]) -> bool:
    return any(abs(float((term.get("coeff") or {}).get("c0") or 0.0)) > dsl._COEF_BOUND for term in terms)


def validity_problem(law: dict, *, complexity_budget: int | None = None, sampler: str | None = None) -> str | None:
    terms = law.get("terms") or []
    if not terms:
        return "no_terms"
    if complexity_budget is not None and dsl.complexity(law) > int(complexity_budget):
        return "over_budget"
    keys = [(t["op"], json.dumps(t.get("params") or {}, sort_keys=True)) for t in terms]
    if len(set(keys)) != len(keys):
        return "duplicate_term"
    if not _has_sparse_phase(terms):
        return "no_sparse_phase"
    if not _bounded_below(terms):
        return "unbounded_below"
    if sampler == SAMPLER_631 and _past_coefficient_bound(terms):
        return "coefficient_bound"
    return None


def interval_of(entry) -> dict | None:
    if not isinstance(entry, dict):
        return None
    if "min" not in entry or "max" not in entry:
        return None
    return entry


def term_grid(grid: dict, op: str) -> dict:
    override = (grid.get(GRID_PER_TERM) or {}).get(op)
    if not isinstance(override, dict):
        return grid
    return dict(grid, **{key: value for key, value in override.items()
                         if key in GRID_PER_TERM_KEYS})


def is_continuous(grid: dict | None) -> bool:
    merged = dict(DEFAULT_GRID, **(grid or {}))
    continuous_keys = [key for key in GRID_INTERVAL_KEYS if key not in GRID_INTEGER_KEYS]
    if any(interval_of(merged.get(key)) is not None for key in continuous_keys + list(_SHARE_KEYS)):
        return True
    for override in (merged.get(GRID_PER_TERM) or {}).values():
        if isinstance(override, dict) and any(
                interval_of(override.get(key)) is not None for key in continuous_keys):
            return True
    return False


def _significant(value: float, digits: int = DRAW_SIGNIFICANT_FIGURES) -> float:
    if not value or not math.isfinite(value):
        return float(value)
    return round(value, -int(math.floor(math.log10(abs(value)))) + (digits - 1))


def draw_value(rng: random.Random, entry, *, integer: bool = False):
    interval = interval_of(entry)
    if interval is None:
        value = rng.choice(entry)
        return int(value) if integer else float(value)
    low, high = float(interval["min"]), float(interval["max"])
    if high < low:
        low, high = high, low
    spacing = str(interval.get("spacing") or ("log" if low > 0 else "linear"))
    if spacing == "log":
        value = math.exp(rng.uniform(math.log(low), math.log(high)))
    else:
        value = rng.uniform(low, high)
    if integer:
        return max(int(round(low)), min(int(round(high)), int(round(value))))
    return _significant(value)


def _draw_whole(rng: random.Random, entry) -> int:
    interval = interval_of(entry)
    if interval is None:
        return int(rng.choice(entry))
    low, high = sorted((float(interval["min"]), float(interval["max"])))
    return rng.randint(math.ceil(low), math.floor(high))


def _draw_term(rng: random.Random, op: str, grid: dict) -> dict:
    grid = term_grid(grid, op)
    sign = rng.choice(grid["signs"])
    if op in _POSITIVE_ONLY_OPS:
        sign = 1
    scale = rng.choice(grid["scales"])
    magnitude = draw_value(rng, grid["magnitudes"])
    if _natural(grid):
        magnitude = _significant(magnitude / float(operator_units()["units"][op]))
    coeff = {"c0": float(sign * magnitude), "scale": scale}
    if scale == "power":
        coeff["p"] = float(draw_value(rng, grid["power_exponents"]))
    params = {}
    if op in ("degree_anchor", "degree_anchor_abs"):
        k = _draw_whole(rng, grid["anchor_k"])
        params = {"k": k}
    return {"op": op, "params": params, "coeff": coeff}


def _sweeps(law: dict) -> int:
    base = int(law["dynamics"]["sweeps"])
    if law["dynamics"].get("zero_temperature"):
        return base
    return sweeps_for_coupling(base, coupling_strength(law, REFERENCE_N))


def blind_law(rng: random.Random, whitelist: list[str], grid: dict | None = None,
              *, complexity_budget: int | None = None, max_attempts: int = 200,
              ledger: list | None = None) -> dict:
    grid = dict(DEFAULT_GRID, **(grid or {}))
    ops = [op for op in whitelist if op in dsl.OPERATORS]
    if not ops:
        raise GridError("operator whitelist has no known operators")
    for _ in range(max_attempts):
        n_terms = int(rng.choice(grid["term_counts"]))
        terms = [_draw_term(rng, rng.choice(ops), grid) for _ in range(n_terms)]
        law = {
            "dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {
                "kind": "equilibrium", "beta": float(draw_value(rng, grid["betas"])),
                "move_mix": dict(grid.get("move_mix") or DEFAULT_GRID["move_mix"]),
                "sweeps": int(grid.get("base_sweeps") or DEFAULT_GRID["base_sweeps"]),
            },
        }
        law["dynamics"].update(draw_dynamics(rng, grid))
        problem = validity_problem(law, complexity_budget=complexity_budget, sampler=SAMPLER_631)
        if problem is not None:
            if ledger is not None:
                ledger.append((f"invalid:{problem}", law))
            continue
        law["dynamics"]["sweeps"] = _sweeps(law)
        return law
    raise GridError(f"no valid law in {max_attempts} draws; the grid cannot define a sparse phase")


def blind_batch(rng: random.Random, need: int, whitelist: list[str], grid: dict | None,
                existing: set[str], existing_physical: set[str],
                *, fingerprint, physical_identity, complexity_budget: int | None = None,
                max_rounds: int = 60, ledger: list | None = None,
                streams=None, first_index: int = 0, survey_duplicates: int = SURVEY_DUPLICATES,
                stops: list | None = None) -> list[dict]:
    out: list[dict] = []
    rounds = 0
    positions: dict[int, int] = {}

    def note(outcome, law, fp=None, stream=None):
        if ledger is None:
            return
        if stream is None:
            ledger.append({"draw_index": len(ledger), "outcome": outcome, "candidate_id": fp, "law": law})
            return
        position = positions.get(stream, 0)
        positions[stream] = position + 1
        ledger.append({"stream_index": stream, "draw_index": position, "outcome": outcome,
                       "candidate_id": fp, "law": law})

    if streams is not None:
        from graph_scale_dynamics.research.strata import allocation_of, draw_stratum, stratum_of
        allocation = allocation_of(grid)
        for index in range(int(first_index), int(first_index) + int(need)):
            stream = streams(index)
            target = draw_stratum(stream, allocation) if allocation else None
            found, repeats, valid = None, 0, 0
            exhausted, unfilled, reason = 0, None, PRODUCED
            while found is None:
                if target is not None and (valid >= STRATUM_DRAWS or repeats >= survey_duplicates):
                    unfilled, target, repeats = target, None, 0
                if repeats >= survey_duplicates or exhausted >= GRID_RETRIES:
                    reason = DUPLICATES if repeats >= survey_duplicates else GRID_EXHAUSTED
                    break
                rejected: list = []
                try:
                    law = dsl.normalize(blind_law(stream, whitelist, grid, complexity_budget=complexity_budget,
                                                  ledger=rejected if ledger is not None else None))
                except GridError:
                    exhausted += 1
                    for code, bad in rejected:
                        note(code, bad, stream=index)
                    if not any(op in dsl.OPERATORS for op in whitelist):
                        raise
                    continue
                valid += 1
                for code, bad in rejected:
                    note(code, bad, stream=index)
                if target is not None and stratum_of(law) != target:
                    note("set_aside", law, stream=index)
                    continue
                fp = fingerprint(law)
                physical = physical_identity(law)
                if fp in existing or physical in existing_physical:
                    repeats += 1
                    note("duplicate_law" if fp in existing else "duplicate_identity", law, fp, stream=index)
                    continue
                note("admitted", law, fp, stream=index)
                existing.add(fp)
                existing_physical.add(physical)
                found = law
            if stops is not None:
                stops.append({"stream_index": index, "reason": reason, "valid": valid, "duplicates": repeats,
                              "unfilled": unfilled})
            if found is None:
                break
            out.append(found)
        return out

    exhausted = 0
    while len(out) < need and rounds < max_rounds * max(1, need) and exhausted < GRID_RETRIES * max(1, need):
        rounds += 1
        rejected = []
        try:
            law = dsl.normalize(blind_law(rng, whitelist, grid, complexity_budget=complexity_budget,
                                          ledger=rejected if ledger is not None else None))
        except GridError:
            exhausted += 1
            for code, bad in rejected:
                note(code, bad)
            if not any(op in dsl.OPERATORS for op in whitelist):
                raise
            continue
        for code, bad in rejected:
            note(code, bad)
        fp = fingerprint(law)
        physical = physical_identity(law)
        if fp in existing or physical in existing_physical:
            note("duplicate_law" if fp in existing else "duplicate_identity", law, fp)
            continue
        note("admitted", law, fp)
        existing.add(fp)
        existing_physical.add(physical)
        out.append(law)
    return out
