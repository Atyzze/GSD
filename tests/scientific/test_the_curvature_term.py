from __future__ import annotations

import random

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as eng
from graph_scale_dynamics.engine.engine import GraphState, scaled_curvature
from graph_scale_dynamics.measurements.calibration import (periodic_cubic_lattice, periodic_square_lattice,
                                                          random_regular_graph)
from graph_scale_dynamics.scaleflow import engine_door


def edge_cycles(n: int, edges) -> dict:
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    out = {}
    for u, v in edges:
        nu, nv = adj[u] - {v}, adj[v] - {u}
        t = len(nu & nv)
        s = sum(1 for x in nu for y in adj[x] if y in nv and y != x)
        p = sum(1 for x in nu for z in adj[x] if z not in (u, v) for y in adj[z] if y in nv and y not in (x, u))
        out[(min(u, v), max(u, v))] = (t, s, p)
    return out


def brute_ledger(n: int, edges) -> int:
    adj = [0] * n
    for u, v in edges:
        adj[u] += 1
        adj[v] += 1
    return sum(scaled_curvature(*counts, adj[a], adj[b]) for (a, b), counts in edge_cycles(n, edges).items())


def test_the_formula_reads_flat_space_flat_and_a_tree_negative():
    n, square = periodic_square_lattice(8)
    assert all(scaled_curvature(*c, 4, 4) == 0 for c in edge_cycles(n, square).values()), "Z^2 is flat"
    n, cubic = periodic_cubic_lattice(6)
    assert all(scaled_curvature(*c, 6, 6) == 0 for c in edge_cycles(n, cubic).values()), "Z^3 is flat"
    assert scaled_curvature(0, 0, 0, 3, 3) == -2 * 3 * (3 - 2), "no short cycles: -2 d (d - 2), a tree's edge"
    assert scaled_curvature(1, 0, 0, 2, 2) == 2, "a triangle's edge: equation (20) as printed gives 1/2, times 2 x 2"
    n, regular = random_regular_graph(2000, degree=3, seed=3)
    values = [scaled_curvature(*c, 3, 3) for c in edge_cycles(n, regular).values()]
    assert sorted(values)[len(values) // 2] == -2 * 3 * 1, "most edges of a sparse random regular graph"


def test_the_ledger_and_the_kept_counts_match_a_recount_after_every_move():
    n, rng = 9, random.Random(11)
    state = GraphState(n)
    state.require_ops({"ollivier_curvature"})
    edges: set = set()
    for step in range(600):
        u, v = sorted(rng.sample(range(n), 2))
        adding = (u, v) not in edges
        deltas = state.op_deltas(u, v, adding)
        state.apply(u, v, adding, deltas)
        edges.add((u, v)) if adding else edges.discard((u, v))
        assert state.ledgers["ollivier_curvature"] == brute_ledger(n, edges), f"ledger drifted at move {step}"
        truth = {e: c for e, c in edge_cycles(n, edges).items() if any(c)}
        assert state.edge_cycles == truth, f"kept counts drifted at move {step}"


def test_a_whole_chain_with_swaps_ends_on_the_recounted_energy():
    law = {"dsl_version": 1, "init": "empty", "terms": [
        {"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 0.5, "scale": "one"}},
        {"op": "ollivier_curvature", "params": {}, "coeff": {"c0": -0.25, "scale": "one"}},
        {"op": "triangle_count", "params": {}, "coeff": {"c0": 0.5, "scale": "one"}}],
        "dynamics": {"kind": "equilibrium", "beta": 0.7, "move_mix": {"add": 0.35, "delete": 0.35, "swap": 0.3},
                     "sweeps": 10}}
    envelope = engine_door.run_simulation(law, 12, 4242, record_points=20)
    edges = [tuple(e) for e in CL.sorted_edges(envelope)]
    degrees = [0] * 12
    for u, v in edges:
        degrees[u] += 1
        degrees[v] += 1
    truth = (0.5 * sum((d - 4) ** 2 for d in degrees) - 0.25 * brute_ledger(12, edges)
             + 0.5 * sum(c[0] for c in edge_cycles(12, edges).values()) / 3)
    assert abs(CL.record(envelope, CL.FROM_EMPTY)["final"]["energy"] - truth) < 1e-9
    assert CL.record(envelope, CL.FROM_EMPTY)["acceptance"]["attempted"]["swap"] > 0
