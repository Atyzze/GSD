import itertools
import random
from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as eng
from graph_scale_dynamics.engine.engine import GraphState
from graph_scale_dynamics.dsl.dsl import coefficient
from graph_scale_dynamics.scaleflow import engine_door


def brute_energy(spec, n, edges):
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v); adj[v].add(u)
    deg = [len(a) for a in adj]
    wedges = sum(d * (d - 1) // 2 for d in deg)
    triangles = sum(1 for a, b, c in itertools.combinations(range(n), 3)
                    if b in adj[a] and c in adj[a] and c in adj[b])
    squares = 0
    for a, b in itertools.combinations(range(n), 2):
        common = len(adj[a] & adj[b])
        squares += common * (common - 1) // 2
    squares //= 1
    squares = squares // 2 if False else sum(
        (len(adj[a] & adj[b]) * (len(adj[a] & adj[b]) - 1) // 2)
        for a, b in itertools.combinations(range(n), 2)) // 2
    triangle_overlap = 0
    square_overlap = 0
    for u, v in edges:
        shared = len(adj[u] & adj[v])
        triangle_overlap += shared * (shared - 1) // 2
        q = sum(len(adj[x] & (adj[v] - {u})) for x in (adj[u] - {v}))
        square_overlap += q * (q - 1) // 2
    induced_squares = 0
    for nodes in itertools.combinations(range(n), 4):
        node_set = set(nodes)
        local_deg = {u: sum(1 for v in adj[u] if v in node_set) for u in nodes}
        local_edges = sum(local_deg.values()) // 2
        if local_edges == 4 and all(value == 2 for value in local_deg.values()):
            induced_squares += 1
    degree_gradient = sum((deg[u] - deg[v]) ** 2 for u, v in edges)
    values = {"edge_count": len(edges), "degree_square_sum": sum(d * d for d in deg),
              "degree_cube_sum": sum(d ** 3 for d in deg),
              "degree_fourth_sum": sum(d ** 4 for d in deg), "wedge_count": wedges,
              "triangle_count": triangles, "triangle_edge_overlap": triangle_overlap,
              "square_count": squares, "square_edge_overlap": square_overlap,
              "induced_square_count": induced_squares,
              "degree_neighbor_gradient": degree_gradient}
    total = 0.0
    for term in spec["terms"]:
        op = term["op"]
        if op == "degree_anchor":
            k = term["params"]["k"]
            total += coefficient(term, n) * sum((d - k) ** 2 for d in deg)
        elif op == "degree_anchor_abs":
            k = term["params"]["k"]
            total += coefficient(term, n) * sum(abs(d - k) for d in deg)
        else:
            total += coefficient(term, n) * values[op]
    return total


SPEC = {"dsl_version": 1, "init": "empty",
        "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.3, "scale": "log_N"}},
                  {"op": "degree_anchor", "params": {"k": 3}, "coeff": {"c0": 0.4, "scale": "one"}},
                  {"op": "degree_anchor", "params": {"k": 7}, "coeff": {"c0": 0.25, "scale": "one"}},
                  {"op": "degree_anchor_abs", "params": {"k": 4}, "coeff": {"c0": 0.5, "scale": "one"}},
                  {"op": "degree_cube_sum", "params": {}, "coeff": {"c0": 0.03, "scale": "one"}},
                  {"op": "degree_fourth_sum", "params": {}, "coeff": {"c0": 0.004, "scale": "one"}},
                  {"op": "degree_neighbor_gradient", "params": {}, "coeff": {"c0": 0.07, "scale": "one"}},
                  {"op": "wedge_count", "params": {}, "coeff": {"c0": 0.12, "scale": "one"}},
                  {"op": "triangle_count", "params": {}, "coeff": {"c0": -0.2, "scale": "one"}},
                  {"op": "triangle_edge_overlap", "params": {}, "coeff": {"c0": 0.11, "scale": "one"}},
                  {"op": "square_count", "params": {}, "coeff": {"c0": 0.15, "scale": "one"}},
                  {"op": "square_edge_overlap", "params": {}, "coeff": {"c0": 0.09, "scale": "one"}},
                  {"op": "induced_square_count", "params": {}, "coeff": {"c0": -0.08, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 1.0,
                     "move_mix": {"add": 0.5, "delete": 0.5}, "sweeps": 1}}


def test_incremental_deltas_match_brute_force_including_dual_anchors():
    n = 7
    rng = random.Random(5)
    assert callable(engine_door.run_simulation), "import sanity: the frozen sampler is importable"
    node_functionals = {"degree_anchor": lambda d, k: (d - k) ** 2,
                        "degree_anchor_abs": lambda d, k: abs(d - k),
                        "degree_cube_sum": lambda d, k: d ** 3,
                        "degree_fourth_sum": lambda d, k: d ** 4}
    node_terms = [(t["op"], coefficient(t, n), int(t.get("params", {}).get("k", 0)))
                  for t in SPEC["terms"] if t["op"] in node_functionals]
    state = GraphState(n)
    edges = set()
    energy = sum(c * n * node_functionals[op](0, k) for op, c, k in node_terms)
    assert abs(energy - brute_energy(SPEC, n, edges)) < 1e-9
    for _ in range(300):
        u, v = rng.randrange(n), rng.randrange(n)
        if u == v:
            continue
        u, v = min(u, v), max(u, v)
        adding = (u, v) not in edges
        deltas = state.op_deltas(u, v, adding)
        node_energy = 0.0
        sign = 1 if adding else -1
        du = state.degree(u) - (0 if adding else 1)
        dv = state.degree(v) - (0 if adding else 1)
        for op, c, k in node_terms:
            f = node_functionals[op]
            node_energy += c * sign * (f(du + 1, k) - f(du, k) + f(dv + 1, k) - f(dv, k))
        delta = eng._term_delta_energy(SPEC, n, deltas, node_energy)
        state.apply(u, v, adding, deltas)
        edges.add((u, v)) if adding else edges.discard((u, v))
        energy += delta
        assert abs(energy - brute_energy(SPEC, n, edges)) < 1e-8, "delta drifted from truth"


def test_swap_augmented_chain_preserves_full_operator_energy_exactness():
    import copy
    spec = copy.deepcopy(SPEC)
    spec["dynamics"] = {"kind": "equilibrium", "beta": 0.3,
                        "move_mix": {"add": 0.3, "delete": 0.3, "swap": 0.4},
                        "sweeps": 16}
    envelope = engine_door.run_simulation(spec, 8, 3711, record_points=50)
    truth = brute_energy(spec, 8, set(map(tuple, CL.sorted_edges(envelope))))
    assert abs(CL.record(envelope, CL.FROM_EMPTY)["final"]["energy"] - truth) < 1e-7
    assert CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["attempted"]["swap"] > 0


def test_square_overlap_reuses_proposal_multiplicity_on_apply(monkeypatch):
    state = GraphState(6)
    state.require_ops({"square_edge_overlap"})
    for u, v in ((0, 2), (0, 3), (1, 2), (1, 3)):
        deltas = state.op_deltas(u, v, True)
        state.apply(u, v, True, deltas)

    calls = 0
    original = state._square_multiplicity

    def counted(u, v, paths):
        nonlocal calls
        calls += 1
        return original(u, v, paths)

    monkeypatch.setattr(state, "_square_multiplicity", counted)
    deltas = state.op_deltas(0, 1, True)
    assert calls == 1
    state.apply(0, 1, True, deltas)
    assert calls == 1, "accepted apply must reuse the multiplicity already computed for scoring"
