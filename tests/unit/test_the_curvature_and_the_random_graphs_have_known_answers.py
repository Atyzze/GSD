from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.research import curvature_known_answers as K
from graph_scale_dynamics.research import look_alikes
from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]


def _json(name: str) -> dict:
    return json.loads(committed.path(name).read_text(encoding="utf-8"))


def _edge(edges, a, b) -> int:
    return edges.index((min(a, b), max(a, b)))


def test_ollivier_s_curvature_is_what_it_is_by_hand():
    n, edges = K.complete(4)
    assert abs(K.ollivier(K.adjacency(n, edges), 0, 1) - 2.0 / 3.0) < 1e-9
    path = K.adjacency(4, [(0, 1), (1, 2), (2, 3)])
    assert abs(K.ollivier(path, 1, 2)) < 1e-9
    star = K.adjacency(4, [(0, 1), (0, 2), (0, 3)])
    assert abs(K.ollivier(star, 0, 1) - 0.0) < 1e-9


def test_the_probe_is_exact_on_a_square_torus_and_a_third_high_on_a_triangular_one():
    n, edges = look_alikes.torus(36, 2)
    adj = K.adjacency(n, edges)
    probe = K.probe_curvature(n, edges, adj)
    assert abs(K.ollivier(adj, *edges[0])) < 1e-9 and abs(probe[0]) < 1e-9
    n, edges = look_alikes.triangular_torus(36)
    adj = K.adjacency(n, edges)
    probe = K.probe_curvature(n, edges, adj)
    assert abs(K.ollivier(adj, *edges[0])) < 1e-9 and abs(probe[0] - 1.0 / 3.0) < 1e-9


def test_a_prediction_is_right_only_when_the_family_reads_as_committed():
    row = {"family": "f", "edges_read": 10, "edges_agreeing": 10, "apart_least": 0.0, "apart_most": 0.0}
    off = dict(row, edges_agreeing=0, apart_least=1 / 3, apart_most=1 / 3)
    assert K.judge({"cases": [{"family": "f", "expected": "exact"}]}, [row])["passes"]
    assert not K.judge({"cases": [{"family": "f", "expected": "exact"}]}, [off])["passes"]
    assert K.judge({"cases": [{"family": "f", "expected": "not_exact", "apart": 1 / 3}]}, [off])["passes"]
    assert not K.judge({"cases": [{"family": "f", "expected": "not_exact", "apart": 0.5}]}, [off])["passes"]
    open_case = K.judge({"cases": [{"family": "f"}]}, [off])
    assert open_case["predictions"] == 0 and not open_case["passes"] and open_case["not_exact_on"] == ["f"]


def test_the_curvature_s_judgement_in_the_tree_is_the_one_the_rule_gives():
    criterion, kept = _json("curvature_known_answers_criterion_2.json"), _json("curvature_known_answers_2_judged.json")
    rows = [{k: v for k, v in case.items() if k not in ("expected", "exact", "right")} for case in kept["cases"]]
    again = K.judge(criterion, rows)
    for key in ("cases", "predictions_right", "predictions", "passes", "exact_on", "not_exact_on"):
        assert json.loads(json.dumps(again[key])) == kept[key], key
    assert kept["passes"] and kept["predictions"] == 8 and kept["measured_utc"] > criterion["committed_utc"]
    assert "triangular_torus" in kept["not_exact_on"] and "square_torus" in kept["exact_on"]
    page = (ROOT / "docs" / "readings" / "curvature_known_answers_2_judged.md").read_text(encoding="utf-8")
    assert page == K.render(kept)
