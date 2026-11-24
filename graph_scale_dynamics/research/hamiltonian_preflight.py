from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math

from graph_scale_dynamics.dsl.dsl import DEFAULT_MOVE_MIX, DYNAMICS_DEFAULTS, cooling_schedule, dynamics_settings

PREFLIGHT_VERSION = "hamiltonian-preflight-2"
ZERO_TEMPERATURE_FOLDED = "hamiltonian-preflight-3"
IDENTITY_VERSIONS = (PREFLIGHT_VERSION, ZERO_TEMPERATURE_FOLDED)

DEGREE_SEQUENCE_OPERATORS = frozenset({
    "edge_count", "degree_anchor", "degree_square_sum", "wedge_count",
    "degree_anchor_abs", "degree_cube_sum", "degree_fourth_sum",
})
TOPOLOGY_OPERATORS = frozenset({
    "triangle_count", "triangle_edge_overlap", "square_count",
    "square_edge_overlap", "induced_square_count", "degree_neighbor_gradient", "ollivier_curvature",
})


def _number(value: object) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("non-finite Hamiltonian coefficient")
    return float(f"{out:.12g}")


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: object, length: int = 20) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()[:length]


def canonical_scale(coeff: dict) -> tuple[str, float | None]:
    scale = str(coeff.get("scale") or "one")
    if scale != "power":
        return scale, None
    exponent = _number(coeff.get("p"))
    if abs(exponent) < 1e-12:
        return "one", None
    if abs(exponent + 1.0) < 1e-12:
        return "inv_N", None
    if abs(exponent + 0.5) < 1e-12:
        return "inv_sqrt_N", None
    return "power", exponent


def _basis_key(op: str, params: dict, coeff: dict) -> tuple[str, str, str, float | None]:
    scale, exponent = canonical_scale(coeff)
    return op, _encoded(params), scale, exponent


def effective_basis(spec: dict) -> list[dict]:
    beta = _number((spec.get("dynamics") or {}).get("beta", 1.0))
    combined: defaultdict[tuple[str, str, str, float | None], float] = defaultdict(float)

    def add(op: str, params: dict, coeff: dict, multiplier: float = 1.0) -> None:
        key = _basis_key(op, params, coeff)
        combined[key] += beta * _number(coeff.get("c0", 0.0)) * multiplier

    for term in spec.get("terms") or []:
        op = str(term.get("op") or "unknown")
        params = dict(term.get("params") or {})
        coeff = dict(term.get("coeff") or {})
        if op == "wedge_count":
            add("degree_square_sum", {}, coeff, 0.5)
            add("edge_count", {}, coeff, -1.0)
        elif op == "degree_anchor":
            k = int(params.get("k", 0))
            add("degree_square_sum", {}, coeff, 1.0)
            add("edge_count", {}, coeff, -4.0 * k)
        else:
            add(op, params, coeff, 1.0)

    terms: list[dict] = []
    for (op, params_json, scale, exponent), value in combined.items():
        value = _number(value)
        if abs(value) <= 1e-11:
            continue
        node = {
            "op": op,
            "params": json.loads(params_json),
            "scale": scale,
            "coefficient": value,
        }
        if scale == "power":
            node["p"] = exponent
        terms.append(node)
    terms.sort(key=lambda row: (row["op"], _encoded(row["params"]), row["scale"],
                                float(row.get("p") or 0.0), row["coefficient"]))
    return terms


def dynamics_signature(spec: dict) -> dict | None:
    settings = dynamics_settings(spec)
    mix = {key: round(float(value), 12) for key, value in
           sorted(((spec.get("dynamics") or {}).get("move_mix") or DEFAULT_MOVE_MIX).items())}
    default_mix = mix == {key: round(value, 12) for key, value in sorted(DEFAULT_MOVE_MIX.items())}
    cooling = cooling_schedule(spec)
    if settings == DYNAMICS_DEFAULTS and default_mix and cooling is None:
        return None
    return {"locality": round(settings["locality"], 12), "local_move": settings["local_move"],
            "zero_temperature": settings["zero_temperature"], **({} if default_mix else {"move_mix": mix}),
            **({"cooling": cooling} if cooling else {})}


def fold_zero_temperature(basis: list[dict]) -> list[dict]:
    if not basis:
        return basis
    scales = {(row["scale"], row.get("p")) for row in basis}
    rows = [dict(row) for row in basis]
    if len(scales) == 1:
        for row in rows:
            row["scale"] = "one"
            row.pop("p", None)
    largest = max(abs(float(row["coefficient"])) for row in rows)
    for row in rows:
        row["coefficient"] = _number(float(row["coefficient"]) / largest)
    rows.sort(key=lambda row: (row["op"], _encoded(row["params"]), row["scale"],
                               float(row.get("p") or 0.0), row["coefficient"]))
    return rows


def equilibrium_identity(spec: dict, *, version: str = PREFLIGHT_VERSION) -> tuple[str, str, list[dict]]:
    if version not in IDENTITY_VERSIONS:
        raise ValueError(f"unknown identity version {version!r}; known: {IDENTITY_VERSIONS}")
    signature = dynamics_signature(spec)
    zero_temperature = bool(signature and signature["zero_temperature"])
    if zero_temperature:
        spec = dict(spec, dynamics=dict(spec.get("dynamics") or {}, beta=1.0))
    basis = effective_basis(spec)
    if zero_temperature and version == ZERO_TEMPERATURE_FOLDED:
        basis = fold_zero_temperature(basis)
    else:
        version = PREFLIGHT_VERSION
    identity = {"version": version, "ensemble": "simple_graph_grand_canonical",
                "basis": basis, **({"dynamics": signature} if signature else {})}
    label = "+".join(term["op"] for term in basis) or "constant_hamiltonian"
    return _digest(identity, 24), label, basis


def equilibrium_family(spec: dict) -> tuple[str, str]:
    _, _, basis = equilibrium_identity(spec)
    structure = [{"op": term["op"], "params": term["params"],
                  "scale": term["scale"], **({"p": term["p"]} if "p" in term else {})}
                 for term in basis]
    label = "+".join(term["op"] for term in structure) or "constant_hamiltonian"
    signature = dynamics_signature(spec)
    return _digest({"version": PREFLIGHT_VERSION, "basis_structure": structure,
                    **({"dynamics": signature} if signature else {})}, 16), label


def equilibrium_coefficient_region(spec: dict) -> tuple[str, str]:
    _, _, basis = equilibrium_identity(spec)
    nodes = []
    labels = []
    for term in basis:
        value = float(term["coefficient"])
        sign = "positive" if value > 0 else "negative"
        magnitude = abs(value)
        exponent = math.floor(math.log10(magnitude) * 2.0) / 2.0 if magnitude else -99.0
        bucket = f"10^{exponent:+.1f}" if magnitude else "zero"
        node = {"op": term["op"], "params": term["params"], "scale": term["scale"],
                "sign": sign, "magnitude": bucket}
        if "p" in term:
            node["p"] = round(float(term["p"]) * 4.0) / 4.0
        nodes.append(node)
        labels.append(f"{term['op']}:{sign}:{bucket}:{term['scale']}")
    nodes.sort(key=_encoded)
    labels.sort()
    return _digest(nodes, 18), " | ".join(labels) or "constant_hamiltonian"


def _scale_relevance(term: dict) -> str:
    scale = term["scale"]
    if scale == "one":
        return "extensive_if_bounded_degree"
    if scale == "log_N":
        return "log_enhanced"
    if scale == "inv_log_N":
        return "slowly_vanishing"
    if scale in {"inv_N", "inv_sqrt_N"}:
        return "power_vanishing"
    exponent = float(term.get("p") or 0.0)
    if exponent < 0:
        return "power_vanishing"
    if exponent > 0:
        return "superextensive_if_bounded_degree"
    return "extensive_if_bounded_degree"


def _positive(term: dict) -> bool:
    return float(term["coefficient"]) > 0


def _robust_sparse_mechanism(basis: list[dict]) -> bool:
    for term in basis:
        op, scale = term["op"], term["scale"]
        if not _positive(term):
            continue
        if op in {"degree_square_sum", "degree_cube_sum", "degree_fourth_sum"}:
            return True
        if op in {"edge_count", "degree_anchor_abs"}:
            if scale == "log_N":
                return True
            if scale == "power" and float(term.get("p") or 0.0) > 0:
                return True
    return False


def preflight_assessment(spec: dict) -> dict:
    physical_id, physical_label, basis = equilibrium_identity(spec)
    original_ops = {str(term.get("op") or "unknown") for term in (spec.get("terms") or [])}
    degree_only = bool(original_ops) and original_ops <= DEGREE_SEQUENCE_OPERATORS
    topology = [term for term in basis if term["op"] in TOPOLOGY_OPERATORS]
    topology_relevant = [term for term in topology if _scale_relevance(term) not in {
        "slowly_vanishing", "power_vanishing",
    }]
    anti_coercive = [term for term in basis
                     if term["op"] in {"degree_square_sum", "degree_cube_sum", "degree_fourth_sum"}
                     and float(term["coefficient"]) < 0]
    positive_quartic = [term for term in basis
                        if term["op"] == "degree_fourth_sum"
                        and float(term["coefficient"]) > 0]
    stabilized_anti_coercive = [term for term in anti_coercive
                                if term["op"] in {"degree_square_sum", "degree_cube_sum"}
                                and positive_quartic]
    unstabilized_anti_coercive = [term for term in anti_coercive
                                  if term not in stabilized_anti_coercive]
    robust_sparse = _robust_sparse_mechanism(basis)
    warnings: list[str] = []
    multiplier = 1.0
    if not basis:
        warnings.append("Hamiltonian is graph-independent after exact reduction")
        multiplier *= 0.10
    if degree_only:
        warnings.append("energy depends only on the degree sequence and cannot distinguish rewired graphs with identical degrees")
        multiplier *= 0.25
    elif topology and not topology_relevant:
        warnings.append("all topology-sensitive terms vanish in the bounded-degree sparse limit")
        multiplier *= 0.40
    if not robust_sparse:
        warnings.append("no conservative entropy-balancing sparse mechanism was identified")
        multiplier *= 0.35
    if unstabilized_anti_coercive:
        warnings.append("negative highest-order degree term creates a dense or hub-condensation risk")
        multiplier *= 0.30
    elif stabilized_anti_coercive:
        warnings.append("negative lower-order degree term is paired with a positive quartic stabilizer")
    triangle_reward = any(term["op"] == "triangle_count" and float(term["coefficient"]) < 0
                          for term in basis)
    overlap_control = any(term["op"] == "triangle_edge_overlap"
                          and float(term["coefficient"]) > 0 for term in basis)
    if triangle_reward and not overlap_control:
        warnings.append("triangle reward lacks an edge-overlap penalty and can favor clique condensation")
        multiplier *= 0.70
    elif triangle_reward and overlap_control:
        warnings.append("triangle reward is paired with a short-cycle edge-overlap penalty")
    square_reward = any(term["op"] in {"square_count", "induced_square_count"}
                        and float(term["coefficient"]) < 0 for term in basis)
    square_overlap_control = any(term["op"] == "square_edge_overlap"
                                 and float(term["coefficient"]) > 0 for term in basis)
    if square_reward and not square_overlap_control:
        warnings.append("square reward lacks an edge-overlap penalty and can favor overlapping-square or bipartite block condensation")
        multiplier *= 0.75
    elif square_reward and square_overlap_control:
        warnings.append("square reward is paired with a square edge-overlap penalty")

    term_relevance = [{**term, "sparse_relevance": _scale_relevance(term)} for term in basis]
    classification = (
        "constant" if not basis else
        "degree_sequence_only" if degree_only else
        "topology_sensitive"
    )
    return {
        "version": PREFLIGHT_VERSION,
        "ensemble": "empty_start_grand_canonical_add_delete",
        "physical_equivalence_id": physical_id,
        "physical_label": physical_label,
        "classification": classification,
        "degree_sequence_only": degree_only,
        "topology_sensitive_terms": len(topology),
        "topology_relevant_terms": len(topology_relevant),
        "robust_sparse_mechanism": robust_sparse,
        "anti_coercive_degree_terms": len(anti_coercive),
        "stabilized_anti_coercive_degree_terms": len(stabilized_anti_coercive),
        "unstabilized_anti_coercive_degree_terms": len(unstabilized_anti_coercive),
        "allocation_multiplier": max(0.02, multiplier),
        "warnings": warnings,
        "effective_basis": term_relevance,
    }
