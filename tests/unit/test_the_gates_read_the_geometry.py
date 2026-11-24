from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.research.stability_score import score_law

SIZES = [64, 256, 1024, 4096, 16384]
FLOORS = {"d_s": 0.05, "d_V": 0.05, "d_B": 0.05, "d_w": 0.05}
ROOT = Path(__file__).resolve().parents[2]


def _vectors(d_s, **others):
    out = {"d_s": d_s, "d_V": [None] * 5, "d_B": [None] * 5, "d_w": [None] * 5}
    out.update(others)
    return out


def test_a_metric_geometry_keeps_its_points_and_no_line_withholds_them():
    plane = score_law(_vectors([2.0] * 5), None, floors=FLOORS, sizes=SIZES, mean_degree_vector=[3.0] * 5,
                      connectivity_vector=[1.0] * 5, connectivity_floor=0.9,
                      half_volume_radius_vector=[n ** 0.5 for n in SIZES])
    assert plane["metric_class"]["verdict"] == "metric"
    assert "tree_line" not in plane
    assert plane["blocks"]["d_s"]["bucket"] == "CONVERGED" and plane["blocks"]["d_s"]["score"] == 50.0
    tree = score_law(_vectors([2.0] * 5), None, floors=FLOORS, sizes=SIZES, mean_degree_vector=[3.0] * 5)
    assert tree["blocks"]["d_s"]["bucket"] == "CONVERGED", "without a radius test d_s keeps its settling: the tree line left at 790"


def test_a_graph_with_no_metric_structure_relabels_every_probe_whatever_d_s_scored():
    radii = [3.0, 4.4, 5.8, 7.2, 8.6]
    scored = score_law(_vectors([None] * 5, d_V=[2.6] * 5), None, floors=FLOORS, sizes=SIZES,
                       mean_degree_vector=[4.6] * 5, connectivity_vector=[1.0] * 5, connectivity_floor=0.9,
                       half_volume_radius_vector=radii)
    assert scored["metric_class"]["verdict"] == "no_metric_structure"
    assert scored["buckets"]["d_V"] == "NO_METRIC_STRUCTURE" and scored["metric_class"]["gate_applied"]
    assert scored["metric_class"]["withheld_points"] == 0.0


def test_reports_04_05_10_and_18_read_the_control_families(monkeypatch):
    from graph_scale_dynamics.research import landscape_audit, stability_score
    asked = []
    real = stability_score.control_family_reference
    monkeypatch.setattr(stability_score, "control_family_reference",
                        lambda table: asked.append(table) or real(table))
    table = json.loads((ROOT / "calibration" / "seed_table.json").read_text(encoding="utf-8"))
    landscape_audit.candidate_landscape_rows([], calibration_table=table)
    assert asked == [table]


def test_no_asymptotic_approach_is_read_across_a_refused_rung():
    from graph_scale_dynamics.research.stability_score import score_block
    sizes = [64, 256, 1024, 4096, 16384]
    values = [1.0, 1.5, None, 1.8, 1.81]
    buckets = [None, None, "REFUSED_NO_SCALING_WINDOW", None, None]
    gapped = score_block(values, buckets, floor=0.05, sizes=sizes, ses=[0.01] * 5)
    assert gapped["steps_span_a_gap"] is True and gapped["settled_by_asymptotic_approach"] is False
    whole = score_block([1.0, 1.5, 1.7, 1.8, 1.81], [None] * 5, floor=0.05, sizes=sizes, ses=[0.01] * 5)
    assert whole["steps_span_a_gap"] is False
