from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research.stability_score import (  # noqa: E402
    BLOCK_POINTS, decelerating, remaining_distance, score_block, step_ratios,
)
from graph_scale_dynamics.research.step_shape import shown  # noqa: E402
from graph_scale_dynamics.scaleflow.probes import Bucket  # noqa: E402

SIZES = [64, 256, 1024, 4096, 16384, 65536]
G1186 = [1.402, 1.787, 2.120, 2.419, 2.601, 2.648]
CLIMBER = [1.17, 1.35, 1.55, 1.72, 1.87]
TIGHT = [0.02] * 6


def block(values, *, floor, ses=None):
    n = len(values)
    return score_block(values, [None] * n, floor=floor, sizes=SIZES[:n],
                       floors_by_n={s: floor for s in SIZES}, ses=(ses or TIGHT)[:n])


def test_the_constant_fit_is_rejected_on_both_which_is_the_whole_problem():
    for values, floor in ((G1186, 0.18), (CLIMBER, 0.30)):
        out = block(values, floor=floor)
        assert out["moves_beyond_its_errors"] is True, values
        assert out["monotone"] is True, values


def test_g1186_converges_because_its_tail_is_inside_the_instrument():
    out = block(G1186, floor=0.18)
    assert out["settled_by_asymptotic_approach"] is True
    assert out["bucket"] == Bucket.CONVERGED.value
    assert out["score"] == BLOCK_POINTS
    assert out["remaining_distance"] < 0.05


def test_a_climbing_probe_is_still_drifting_even_though_its_steps_shrink():
    out = block(CLIMBER, floor=0.30)
    assert out["decelerating"] is True, "its steps really are shrinking"
    assert out["tail_inside_tolerance"] is False
    assert out["settled_by_asymptotic_approach"] is False
    assert out["bucket"] == Bucket.DRIFTING_MONOTONICALLY.value
    assert out["score"] < BLOCK_POINTS
    assert out["remaining_distance"] > sum(
        abs(b - a) for a, b in zip(CLIMBER, CLIMBER[1:], strict=False)), (
        "more still to travel than it has travelled")


def test_a_runaway_is_untouched():
    out = block([1.0, 1.4, 1.9, 2.6, 3.6, 5.0], floor=0.09)
    assert out["decelerating"] is False
    assert out["score"] == 0.0
    assert out["bucket"] == Bucket.DRIFTING_MONOTONICALLY.value


def test_a_genuinely_flat_probe_takes_the_ordinary_path_not_the_escape():
    out = block([1.30, 1.24, 1.26, 1.25, 1.252], floor=0.30, ses=[0.05] * 6)
    assert out["moves_beyond_its_errors"] is False
    assert out["settled_by_asymptotic_approach"] is False
    assert out["bucket"] == Bucket.CONVERGED.value
    assert out["score"] == BLOCK_POINTS


def test_g1186_converges_only_through_the_escape():
    for se in (0.10, 0.15, 0.20, 0.30):
        out = block(G1186, floor=0.18, ses=[se] * 6)
        assert out["moves_beyond_its_errors"] is True, se
        assert out["settled_by_asymptotic_approach"] is True, se


def test_step_ratios_and_tail_are_one_definition_for_both_halves():
    deltas = [0.385, 0.333, 0.299, 0.182, 0.047]
    ratios = step_ratios(deltas)
    assert shown(ratios) == [0.8649, 0.8979, 0.6087, 0.2582], "unrounded since 701, shown rounded"
    assert decelerating(ratios) is True
    assert remaining_distance(deltas, ratios) < 0.02


def test_a_tail_is_refused_rather_than_guessed_when_the_ratio_is_not_below_one():
    deltas = [0.1, 0.2, 0.4]
    assert remaining_distance(deltas, step_ratios(deltas)) is None, (
        "a sequence with no limit in sight gets no extrapolation")
    assert remaining_distance([], []) is None
