from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.research.stability_score import (
    MEAN_DEGREE_STRICT_TOLERANCE, density_diagnostic)

ROOT = Path(__file__).resolve().parents[2]
BASE = [64, 256, 1024, 4096, 16384]


def test_a_curve_that_merely_flattens_is_not_settled():
    d = density_diagnostic([6.125, 5.932, 5.428, 5.033, 5.002], BASE)
    assert d["settled"] is False
    assert round(d["relative_steps"][-2], 3) == 0.073


def test_three_consecutive_flat_rungs_are_settled():
    d = density_diagnostic([3.0, 2.99, 2.995, 2.996, 2.996], BASE)
    assert d["settled"] is True
    assert d["settled_rungs_flat"] == 3
    assert max(d["relative_steps"][-2:]) <= MEAN_DEGREE_STRICT_TOLERANCE


def test_one_lucky_small_step_after_a_large_one_is_not_settled():
    d = density_diagnostic([8.0, 6.0, 5.0, 4.0, 3.98], BASE)
    assert d["settled"] is False, (
        "a 20% step then a 0.5% step is a law still moving that happened to be "
        "sampled near a turn")


def test_two_rungs_cannot_show_three_flat_ones():
    d = density_diagnostic([3.0, 3.0, None, None, None], BASE)
    assert not d.get("settled"), (
        "one step is one step; the claim being made is about three rungs. "
        "Below three rungs the diagnostic is not evaluable at all and returns "
        "no verdict, which must also read as 'not settled' to every caller.")
    assert d.get("evaluable") is False


def test_both_criteria_stay_published():
    d = density_diagnostic([3.0, 2.99, 2.995, 2.996, 2.996], BASE)
    for key in ("not_flowing", "within_tolerance",
                "decelerating_and_within_tolerance",
                "last_two_steps_within_strict", "last_two_steps_within_tolerance"):
        assert key in d["criteria"], (
            "a gate is argued from measured precision, so every candidate stays "
            "countable rather than being replaced silently")
