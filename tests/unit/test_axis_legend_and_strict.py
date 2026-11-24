from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.research.stability_score import density_diagnostic

ROOT = Path(__file__).resolve().parents[2]
BASE = [64, 256, 1024, 4096, 16384]


def test_strict_is_a_subset_of_settled():
    cases = ([3.0, 2.99, 2.995, 2.996, 2.996],
             [3.0, 2.6, 2.9, 2.995, 2.996],
             [6.125, 5.932, 5.428, 5.033, 5.002],
             [2.0, 2.60, 2.95, 2.97, 2.972],
             [8.0, 6.0, 5.0, 4.0, 3.98])
    for md in cases:
        d = density_diagnostic(md, BASE)
        if d.get("settled_strict"):
            assert d.get("settled"), f"strict without settled on {md}"


def test_strict_is_the_same_rule_one_rung_deeper():
    flat4 = density_diagnostic([3.0, 2.99, 2.995, 2.996, 2.996], BASE)
    top_only = density_diagnostic([3.0, 2.6, 2.9, 2.995, 2.996], BASE)
    assert flat4["settled_strict"] is True
    assert top_only["settled_strict"] is False


def test_the_summary_counts_whatever_criteria_exist():
    d = density_diagnostic([3.0, 2.99, 2.995, 2.996, 2.996], BASE)
    for key in ("last_two_steps_within_strict", "last_three_steps_within_strict"):
        assert key in d["criteria"]
