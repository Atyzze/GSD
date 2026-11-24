from __future__ import annotations

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine

pytestmark = [pytest.mark.scientific]


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, mix=(0.4, 0.4, 0.2), sweeps=10, **dynamics):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0, "move_mix": {"add": mix[0], "delete": mix[1], "swap": mix[2]},
                         "sweeps": sweeps, **dynamics}}


LAWS = {
    "degrees_only": _law([_term("edge_count", 0.3), _term("degree_anchor", 0.3, k=4)]),
    "every_neighbourhood_term": _law([_term("edge_count", 0.3), _term("triangle_count", -0.2),
                                      _term("square_edge_overlap", 0.02), _term("triangle_edge_overlap", -0.05),
                                      _term("induced_square_count", 0.01), _term("degree_neighbor_gradient", 0.01)]),
    "curvature": _law([_term("degree_anchor", 0.5, k=6), _term("ollivier_curvature", -0.05)]),
    "local_pairs": _law([_term("edge_count", 0.2), _term("triangle_count", -0.3)], locality=0.6),
}


def _work(envelope, chain):
    return CL.record(envelope, chain)["accounting"]


@pytest.mark.parametrize("name", sorted(LAWS))
def test_both_engines_count_the_same_work_on_every_chain(name):
    run_py = resolve_engine({"engine": "python"})[1]
    run_rs = resolve_engine({"engine": "rust"})[1]
    py, rs = run_py(LAWS[name], 128, 5), run_rs(LAWS[name], 128, 5)
    for chain in ("empty", "given"):
        a, b = _work(py, chain), _work(rs, chain)
        assert a["work"] == b["work"] and a["late"]["work"] == b["late"]["work"]
        assert a["parts"] == b["parts"] and a["late"]["parts"] == b["late"]["parts"]
        assert 0 < a["late"]["work"] < a["work"]
        assert a["work"] >= sum(a["counts"].values())
        parts = a["parts"]
        assert parts["moves"] == CL.record(py, chain)["sweeps"] * 128
        assert parts["evaluations"] >= sum(a["counts"].values()) and parts["changes"] <= parts["evaluations"]
        read = parts["evaluations"] + parts["changes"] + parts["entries"]
        assert read <= a["work"] <= read + parts["tests"]


def _cost(ops, edges, pair):
    state = E.GraphState(8)
    state.require_ops(ops)
    for u, v in edges:
        state.apply(u, v, True, state.op_deltas(u, v, True))
    before = state.work
    state.op_deltas(*pair, True)
    return state.work - before


def test_a_term_that_reads_more_of_the_graph_costs_more_work():
    edges = ((0, 2), (2, 3), (3, 1), (2, 4), (4, 5), (0, 6), (6, 1), (5, 7))
    costs = [_cost(ops, edges, (0, 1)) for ops in ({"edge_count"}, {"triangle_count"}, {"square_count"},
                                                    {"square_count", "square_edge_overlap"},
                                                    {"ollivier_curvature"})]
    assert costs[0] == 1
    assert costs[0] < costs[1] < costs[2] < costs[3]
    assert costs[4] > costs[1]


def test_the_rule_counts_what_a_square_path_reads():
    state = E.GraphState(6)
    state.require_ops({"square_count"})
    for u, v in ((0, 2), (2, 3), (3, 1), (2, 4), (4, 5)):
        deltas = state.op_deltas(u, v, True)
        state.apply(u, v, True, deltas)
    before = state.work
    state.op_deltas(0, 1, True)
    common = len(state.adj[0]) + len(state.adj[1])
    paths = len(state.adj[0]) + len(state.adj[1]) + len(state.adj[2])
    assert state.work - before == 1 + common + paths


def test_an_old_accounting_reads_as_no_work_counted():
    old = {"counts": {}, "delta_h_log2": {}, "late": {"from_move": 3, "counts": {}}}
    acc = E.new_accounting(old)
    assert acc["work"] == 0 and acc["late"]["work"] == 0
