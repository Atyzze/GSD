from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine.engine import configuration_energy
from graph_scale_dynamics.research import degree_prediction as D
from graph_scale_dynamics.scaleflow.engine_door import simulate_of

run_simulation = simulate_of("rust")

ROOT = Path(__file__).resolve().parents[2]
SCALES = ({"scale": "one"}, {"scale": "log_N"}, {"scale": "inv_log_N"}, {"scale": "inv_sqrt_N"},
          {"scale": "inv_N"}, {"scale": "power", "p": 0.3})


def _law(terms, beta=1.0, zero_temperature=False):
    dynamics = {"kind": "equilibrium", "beta": beta, "sweeps": 100,
                "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}}
    if zero_temperature:
        dynamics["zero_temperature"] = True
    return {"dsl_version": 1, "init": "empty", "dynamics": dynamics,
            "terms": [{"op": op, "params": params, "coeff": dict(scale, c0=c0)} for op, params, c0, scale in terms]}


def test_the_node_energy_is_the_engine_s_energy_on_any_graph():
    rng = random.Random(538)
    n = 200
    edges = sorted({tuple(sorted(rng.sample(range(n), 2))) for _ in range(500)})
    degrees = np.zeros(n)
    for u, v in edges:
        degrees[u] += 1
        degrees[v] += 1
    for op in sorted(D.DEGREE_OPS):
        params = {"k": 5} if op.startswith("degree_anchor") else {}
        for scale in SCALES:
            spec = _law([(op, params, 0.7, scale)])
            engine = configuration_energy(spec, n, edges)
            ours = float(D.node_energy(spec, degrees, n).sum())
            assert abs(engine - ours) < 1e-6 * max(1.0, abs(engine)), (op, scale, engine, ours)


def test_three_kinds_by_what_the_energy_can_see():
    assert D.law_kind(_law([("degree_anchor", {"k": 4}, 1.0, SCALES[0])])) == D.KIND_DEGREES
    assert D.law_kind(_law([("wedge_count", {}, 1.0, SCALES[0]), ("edge_count", {}, -1.0, SCALES[0])])) == D.KIND_DEGREES
    assert D.law_kind(_law([("degree_neighbor_gradient", {}, 1.0, SCALES[0])])) == D.KIND_CORRELATIONS
    assert D.law_kind(_law([("degree_anchor", {"k": 4}, 1.0, SCALES[0]),
                            ("square_count", {}, -1.0, SCALES[0])])) == D.KIND_CYCLES
    assert D.predicted_mean_degree(_law([("triangle_count", {}, -1.0, SCALES[0])]), 4096, 16) is None


def test_at_zero_temperature_every_node_rests_at_the_minimum_of_its_energy():
    ring = D.predicted_mean_degree(_law([("degree_anchor", {"k": 2}, 0.3, SCALES[0])], zero_temperature=True), 4096, 16)
    assert ring["mean_degree"] == 2.0 and ring["method"] == D.ZERO_T_METHOD, "an anchor at 2 makes rings"
    pulled = _law([("degree_anchor", {"k": 7}, 1.0, SCALES[0]), ("degree_fourth_sum", {}, 0.01, SCALES[0])],
                  zero_temperature=True)
    assert D.predicted_mean_degree(pulled, 4096, 16)["mean_degree"] == 5.0, "(d-7)^2 + d^4/100 is least at 5"
    dense = _law([("edge_count", {}, -1.0, SCALES[0])], zero_temperature=True)
    assert D.predicted_mean_degree(dense, 4096, 16) == {"mean_degree": 16.0, "method": D.ZERO_T_METHOD,
                                                        "too_dense": True}


def test_at_finite_temperature_the_arithmetic_meets_the_chain():
    cases = [_law([("degree_anchor", {"k": 6}, 0.5, SCALES[0])], beta=1.0),
             _law([("degree_square_sum", {}, 0.3, SCALES[0]), ("edge_count", {}, -2.0, SCALES[0])], beta=2.0),
             _law([("degree_fourth_sum", {}, 0.05, SCALES[2])], beta=0.5)]
    for spec in cases:
        envelope = run_simulation(spec, 1024, 0, target_sweeps=1000)
        measured = 2 * len(CL.block(envelope, CL.FROM_EMPTY)["edge_list"]) / 1024
        predicted = D.predicted_mean_degree(spec, 1024, 16)
        assert predicted["method"] == D.GIBBS_METHOD
        assert abs(predicted["mean_degree"] - measured) < 0.1, (spec["terms"], predicted, measured)
    assert D.predicted_mean_degree(cases[0], 1024, 16)["mean_degree"] > 8.0
