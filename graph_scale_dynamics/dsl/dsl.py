from __future__ import annotations
import math
from graph_scale_dynamics.domain.model import candidate_id, canonical_json

DSL_VERSION = 1

OPERATORS = {
    "edge_count":        {"cost": 1, "params": {}},
    "degree_anchor":     {"cost": 1, "params": {"k": (1, 64)}},
    "degree_square_sum": {"cost": 1, "params": {}},
    "wedge_count":       {"cost": 1, "params": {}},
    "triangle_count":    {"cost": 2, "params": {}},
    "triangle_edge_overlap": {"cost": 3, "params": {}},
    "square_count":      {"cost": 3, "params": {}},
    "square_edge_overlap": {"cost": 3, "params": {}},
    "induced_square_count": {"cost": 3, "params": {}},
    "degree_neighbor_gradient": {"cost": 2, "params": {}},
    "degree_anchor_abs": {"cost": 1, "params": {"k": (1, 64)}},
    "degree_cube_sum":   {"cost": 1, "params": {}},
    "degree_fourth_sum": {"cost": 1, "params": {}},
    "ollivier_curvature": {"cost": 4, "params": {}},
}

SCALES = {
    "one":       lambda n: 1.0,
    "log_N":     lambda n: math.log(max(2, n)),
    "inv_log_N": lambda n: 1.0 / math.log(max(2, n)),
    "inv_N":     lambda n: 1.0 / max(1, n),
    "inv_sqrt_N": lambda n: 1.0 / math.sqrt(max(1, n)),
    "power":     None,
}

DYNAMICS_KINDS = {"equilibrium"}
LOCAL_MOVES = ("toggle",)
DYNAMICS_DEFAULTS = {"locality": 0.0, "local_move": "toggle", "zero_temperature": False}
DYNAMICS_REGIMES = ("equilibrium", "zero_temperature")
DEFAULT_MOVE_MIX = {"add": 0.425, "delete": 0.425, "swap": 0.15}


def local_move_problem(move) -> str:
    return f"dynamics.local_move must be one of {', '.join(LOCAL_MOVES)}"


def dynamics_settings(spec: dict) -> dict:
    dyn = (spec or {}).get("dynamics") or {}
    return {"locality": float(dyn.get("locality", 0.0) or 0.0),
            "local_move": str(dyn.get("local_move") or "toggle"),
            "zero_temperature": bool(dyn.get("zero_temperature", False))}


COOLING_SHAPE = "linear_in_beta"


def cooling_schedule(spec: dict) -> dict | None:
    cooling = ((spec or {}).get("dynamics") or {}).get("cooling")
    if not cooling:
        return None
    return {"from_beta": float(cooling["from_beta"]), "over_sweeps": int(cooling["over_sweeps"])}


def dynamics_regime(spec: dict) -> str:
    settings = dynamics_settings(spec)
    if settings["zero_temperature"]:
        return "zero_temperature"
    return "equilibrium"


def dynamics_record(spec: dict) -> dict:
    dyn = (spec or {}).get("dynamics") or {}
    mix = {"swap": 0.0, **dict(dyn.get("move_mix") or DEFAULT_MOVE_MIX)}
    beta = dyn.get("beta")
    return {"regime": dynamics_regime(spec), **dynamics_settings(spec),
            "beta": None if beta is None else float(beta),
            "swap_share": float(mix.get("swap", 0.0)),
            "move_mix": {key: float(value) for key, value in sorted(mix.items())}}


_COEF_BOUND = 1e3
_POWER_BOUNDS = (-2.0, 2.0)


class DSLValidationError(ValueError):
    pass


def _norm_float(value) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise DSLValidationError("non-finite coefficient")
    return float(f"{out:.12g}")


def coefficient(term: dict, n: int) -> float:
    coeff = term["coeff"]
    scale = coeff["scale"]
    if scale == "power":
        return coeff["c0"] * (max(1, n) ** coeff["p"])
    return coeff["c0"] * SCALES[scale](n)


def validate(spec: dict, *, complexity_budget: int = 6, operator_whitelist=None) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["candidate spec must be an object"]
    if spec.get("dsl_version") != DSL_VERSION:
        problems.append(f"dsl_version must be {DSL_VERSION}")
    terms = spec.get("terms")
    if not isinstance(terms, list) or not terms:
        problems.append("terms must be a non-empty list")
        terms = []
    allowed = set(operator_whitelist) if operator_whitelist else set(OPERATORS)
    total_cost = 0
    seen = set()
    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            problems.append(f"term {index}: must be an object")
            continue
        op = term.get("op")
        if op not in OPERATORS:
            problems.append(f"unknown operator {op!r}")
            continue
        if op not in allowed:
            problems.append(f"operator {op!r} is not whitelisted for this campaign")
        total_cost += OPERATORS[op]["cost"]
        params = term.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            problems.append(f"{op}: params must be an object")
            params = {}
        schema = OPERATORS[op]["params"]
        if set(params) != set(schema):
            problems.append(f"{op}: params must be exactly {sorted(schema)}")
        for name, (lo, hi) in schema.items():
            value = params.get(name)
            if name == "k":
                if isinstance(value, bool) or not isinstance(value, int):
                    problems.append(f"{op}: param {name} must be an integer")
                elif not (lo <= value <= hi):
                    problems.append(f"{op}: param {name} outside [{lo},{hi}]")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)):
                problems.append(f"{op}: param {name} must be a finite number")
            elif not (lo <= value <= hi):
                problems.append(f"{op}: param {name} outside [{lo},{hi}]")
        coeff = term.get("coeff")
        if not isinstance(coeff, dict):
            problems.append(f"{op}: coeff must be an object")
            coeff = {}
        scale = coeff.get("scale")
        if scale not in SCALES:
            problems.append(f"{op}: unknown coefficient scale {scale!r}")
        c0_raw = coeff.get("c0")
        if isinstance(c0_raw, bool):
            problems.append(f"{op}: c0 must be a finite number")
        else:
            try:
                c0 = _norm_float(c0_raw)
                if abs(c0) > _COEF_BOUND:
                    problems.append(f"{op}: |c0| exceeds bound {_COEF_BOUND}")
            except (TypeError, ValueError, DSLValidationError):
                problems.append(f"{op}: c0 must be a finite number")
        if scale == "power":
            exponent = coeff.get("p")
            if isinstance(exponent, bool) or not isinstance(exponent, (int, float)) \
                    or not math.isfinite(float(exponent)) \
                    or not (_POWER_BOUNDS[0] <= exponent <= _POWER_BOUNDS[1]):
                problems.append(f"{op}: power exponent must lie in {_POWER_BOUNDS}")
        key = (op, canonical_json(params))
        if key in seen:
            problems.append(f"duplicate term for operator {op}")
        seen.add(key)
    if total_cost > complexity_budget:
        problems.append(f"complexity {total_cost} exceeds budget {complexity_budget}")

    dyn = spec.get("dynamics")
    if not isinstance(dyn, dict):
        problems.append("dynamics must be an object")
        dyn = {}
    kind = dyn.get("kind")
    if kind != "equilibrium":
        if kind == "nonequilibrium":
            problems.append("dynamics.kind 'nonequilibrium' is not implemented; use 'equilibrium'")
        else:
            problems.append("dynamics.kind must declare 'equilibrium'")
    beta = dyn.get("beta")
    if isinstance(beta, bool) or not isinstance(beta, (int, float)) \
            or not math.isfinite(float(beta)) or not (0 < beta <= 100):
        problems.append("dynamics.beta must lie in (0,100]")
    mix = dyn.get("move_mix")
    allowed_mix_keys = ({"add", "delete"}, {"add", "delete", "swap"})
    if not isinstance(mix, dict) or set(mix) not in allowed_mix_keys:
        problems.append("dynamics.move_mix must contain add/delete and may optionally include swap")
    else:
        add, delete = mix["add"], mix["delete"]
        swap = mix.get("swap", 0.0)
        finite = all(not isinstance(v, bool) and isinstance(v, (int, float))
                     and math.isfinite(float(v)) for v in (add, delete, swap))
        if (not finite or float(add) <= 0 or float(delete) <= 0 or float(swap) < 0
                or abs(float(add) + float(delete) + float(swap) - 1.0) > 1e-9):
            problems.append("dynamics.move_mix must give positive add/delete, nonnegative swap, and sum to 1")
    sweeps = dyn.get("sweeps")
    if isinstance(sweeps, bool) or not (isinstance(sweeps, int) and 1 <= sweeps <= 100000):
        problems.append("dynamics.sweeps must be an integer in [1,100000]")
    locality = dyn.get("locality", 0.0)
    if isinstance(locality, bool) or not isinstance(locality, (int, float)) \
            or not math.isfinite(float(locality)) or not (0.0 <= float(locality) < 1.0) \
            or float(f"{float(locality):.12g}") >= 1.0:
        problems.append("dynamics.locality must lie in [0,1)")
    local_move = dyn.get("local_move", "toggle")
    if not isinstance(local_move, str) or local_move not in LOCAL_MOVES:
        problems.append(local_move_problem(local_move))
    if not isinstance(dyn.get("zero_temperature", False), bool):
        problems.append("dynamics.zero_temperature must be true or false")
    cooling = dyn.get("cooling")
    if cooling is not None:
        start = cooling.get("from_beta") if isinstance(cooling, dict) else None
        over = cooling.get("over_sweeps") if isinstance(cooling, dict) else None
        if not isinstance(cooling, dict) or set(cooling) != {"from_beta", "over_sweeps"}:
            problems.append("dynamics.cooling must give from_beta and over_sweeps, and nothing else")
        elif isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)) \
                or not isinstance(beta, (int, float)) or not (0 < float(start) < float(beta)):
            problems.append("dynamics.cooling.from_beta must lie above 0 and below the law's beta (it starts hotter)")
        elif isinstance(over, bool) or not (isinstance(over, int) and 1 <= over <= 100000):
            problems.append("dynamics.cooling.over_sweeps must be an integer in [1,100000]")
        if dyn.get("zero_temperature") is True:
            problems.append("dynamics.cooling needs a temperature: a zero-temperature law cannot cool")
    if spec.get("init") != "empty":
        problems.append("init must be 'empty' (empty-state emergence is the protocol)")
    return problems


def normalize(spec: dict) -> dict:
    terms = []
    for term in spec["terms"]:
        coeff = {"c0": _norm_float(term["coeff"]["c0"]), "scale": term["coeff"]["scale"]}
        if coeff["scale"] == "power":
            coeff["p"] = _norm_float(term["coeff"]["p"])
        params = {}
        for key in sorted(term.get("params", {})):
            value = term.get("params", {})[key]
            params[key] = int(value) if key == "k" else _norm_float(value)
        terms.append({"op": term["op"], "params": params, "coeff": coeff})
    terms.sort(key=lambda t: (t["op"], canonical_json(t["params"]), canonical_json(t["coeff"])))
    dyn = spec["dynamics"]
    dynamics = {"kind": dyn["kind"], "beta": _norm_float(dyn["beta"]),
                "move_mix": {k: _norm_float(v) for k, v in sorted(dyn["move_mix"].items())},
                "sweeps": int(dyn["sweeps"])}
    settings = dynamics_settings(spec)
    if settings["locality"] > 0.0:
        dynamics["locality"] = _norm_float(settings["locality"])
        if settings["local_move"] != "toggle":
            dynamics["local_move"] = settings["local_move"]
    if settings["zero_temperature"]:
        dynamics["zero_temperature"] = True
    cooling = cooling_schedule(spec)
    if cooling is not None:
        dynamics["cooling"] = {"from_beta": _norm_float(cooling["from_beta"]), "over_sweeps": cooling["over_sweeps"]}
    return {
        "dsl_version": DSL_VERSION,
        "terms": terms,
        "dynamics": dynamics,
        "init": "empty",
    }


def execution_identity_problems(spec: dict, candidate_id_value: str | None = None) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["candidate spec must be an object"]
    for index, term in enumerate(spec.get("terms") or []):
        if not isinstance(term, dict):
            continue
        if "k" in (term.get("params") or {}):
            value = term["params"]["k"]
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"term {index}: k must be an integer; execution cannot coerce it")
    if not problems and candidate_id_value is not None:
        try:
            actual = fingerprint(spec)
        except Exception as exc:
            problems.append(f"candidate fingerprint cannot be recomputed: {exc}")
        else:
            if actual != candidate_id_value:
                problems.append("stored candidate id does not match the canonical specification")
    return problems


def fingerprint(spec: dict) -> str:
    return candidate_id(normalize(spec))


def complexity(spec: dict) -> int:
    return sum(OPERATORS[t["op"]]["cost"] for t in spec.get("terms", []) if t.get("op") in OPERATORS)
