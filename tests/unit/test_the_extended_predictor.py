from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from graph_scale_dynamics.research import degree_prediction_extended as X
from graph_scale_dynamics.research.degree_prediction import predicted_mean_degree

ROOT = Path(__file__).resolve().parents[2]
CRITERION = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "predictor_l2_criterion.json"


PARSED_AT_709 = {
    "graph_scale_dynamics/research/degree_prediction_extended.py": "71b223482ae95af446c8615b1dcc5f6ff7b6cd70f16403d2f0821be1b438e7fd",
    "graph_scale_dynamics/research/degree_prediction.py": "4b8128ec71db960eaed302fb8a545d37b0803fe75d00b0d41bb89ba9f71819fa",
}


def test_the_predictor_is_the_one_the_criterion_hashed():
    from graph_scale_dynamics.measurements.parsed_code import normalized_digest
    criterion = json.loads(CRITERION.read_bytes())
    assert set(criterion["sources"]) == set(PARSED_AT_709)
    for relative, digest in PARSED_AT_709.items():
        assert normalized_digest(ROOT / relative) == digest, \
            f"{relative} changed after the predictor was committed: that is a new predictor"


def _law(terms, *, zero_t=False, beta=1.0):
    return {"terms": [{"op": op, "params": ({"k": k} if k is not None else {}),
                       "coeff": {"c0": c, "scale": "one"}} for op, k, c in terms],
            "dynamics": {"beta": beta, "zero_temperature": zero_t}}


def test_a_law_that_sees_only_degrees_is_538s_arithmetic_unchanged():
    law = _law([("degree_anchor", 6, 1.0)], beta=2.0)
    assert X.predicted_mean_degree_extended(law, 4096, 16)["mean_degree"] == \
        predicted_mean_degree(law, 4096, 16)["mean_degree"]


def test_a_clique_carries_its_cycles_exactly():
    k4 = X.clique_cycles_per_node(3)
    assert math.isclose(k4["triangle_count"], 4 / 4) and math.isclose(k4["square_count"], 3 / 4)
    assert k4["induced_square_count"] == 0.0
    assert math.isclose(k4["triangle_edge_overlap"], 1.5 * math.comb(2, 2))


def test_a_downhill_chain_stops_at_the_first_local_minimum():
    assert X.downhill_rest(np.array([0.0, 1.0, -5.0])) == 0, "one more edge costs: the chain stays empty"
    assert X.downhill_rest(np.array([0.0, -1.0, -2.0, -1.0, -9.0])) == 2


def test_a_zero_temperature_law_rewarding_triangles_rests_in_cliques_once_it_leaves_the_empty_graph():
    law = _law([("degree_anchor", 3, 1.0), ("triangle_count", None, -10.0)], zero_t=True)
    predicted = X.predicted_mean_degree_extended(law, 4096, 16)
    assert predicted["method"] == X.ZERO_T_CLIQUE and predicted["mean_degree"] > 3


def test_a_penalised_gradient_at_finite_temperature_goes_through_the_mean_field():
    law = _law([("degree_anchor", 4, 0.5), ("degree_neighbor_gradient", None, 0.2)], beta=1.5)
    predicted = X.predicted_mean_degree_extended(law, 4096, 16)
    assert predicted["method"] == X.MEAN_FIELD and 0 < predicted["mean_degree"] < 16
    assert X.ledger_entry(law, 4096, 16)[1] == "correlations / finite temperature"
