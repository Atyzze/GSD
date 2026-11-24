from __future__ import annotations

import json

from graph_scale_dynamics.research import law_paths as DM
from graph_scale_dynamics.research import measured_anchors as MA

SPECIMENS = [
    {"candidate_id": "a" * 64, "phenotype": {
        "base_sizes": [64, 256, 1024, 4096], "extension_sizes": [16384],
        "probe_vectors": {"d_s": [1.9, 2.0, 2.05, 2.1], "d_V": [1.8, None, 1.95, 2.0], "d_B": [None, 1.7, 1.8, 1.85],
                          "d_w": [2.1, 2.05, 2.0, None]},
        "per_n": {"64": {"mean_degree": 3.6}, "256": {"mean_degree": 3.8}, "1024": {"mean_degree": 3.9},
                  "4096": {"mean_degree": 3.95}},
        "extension_probe_vectors": {"d_s": [2.12], "d_V": [2.02]}, "extension_mean_degree_vector": [3.97]}},
    {"candidate_id": "b" * 64, "phenotype": {"base_sizes": [64, 256, 1024, 4096],
                                             "probe_vectors": {"d_s": [1.0, 1.05], "d_V": []}}},
    {"candidate_id": "c" * 64, "phenotype": {"base_sizes": [64, 256], "probe_vectors": {}}},
]


def _report_root(tmp_path, specimens):
    root = tmp_path / "live_campaign_1"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "05.json").write_text(json.dumps({"body": {"specimens": specimens}}))
    return root


def test_each_law_is_read_at_every_rung_it_reached_from_report_05(tmp_path):
    paths = DM.law_paths(_report_root(tmp_path, SPECIMENS))
    assert paths == [[(64, 1.9, 1.8, None, 2.1, 3.6), (256, 2.0, None, 1.7, 2.05, 3.8),
                      (1024, 2.05, 1.95, 1.8, 2.0, 3.9), (4096, 2.1, 2.0, 1.85, None, 3.95),
                      (16384, 2.12, 2.02, None, None, 3.97)],
                     [(64, 1.0, None, None, None, None), (256, 1.05, None, None, None, None)]], (
        "(N, d_s, d_V, d_B, d_w, k) at every rung where a probe read; a law that read nothing has no path")
    assert DM.law_paths(tmp_path / "nowhere") == []


def test_a_family_s_mean_degree_is_its_seeds_mean_at_each_n_and_its_short_name_is_the_explorer_s():
    degrees = MA.family_degrees({"cells": {
        f"periodic_square_lattice:{n}:{seed}": {"family": "periodic_square_lattice", "n": n,
                                                 "structure": {"mean_degree": 4.0 + 0.1 * (seed - 1)}}
        for n in (1024, 4096) for seed in range(3)}})
    assert {n: round(v, 6) for n, v in degrees["periodic_square_lattice"].items()} == {1024: 4.0, 4096: 4.0}
    assert MA.family_degrees(None) == {}
    assert [MA.short(f) for f in ("periodic_square_lattice", "sierpinski_gasket", "uniform_random_tree")] == [
        "square", "gasket", "CRT"]
