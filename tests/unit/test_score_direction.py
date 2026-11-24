from __future__ import annotations

from graph_scale_dynamics.research.stability_score import (
    BLOCK_POINTS, CONSTANCY_SIGNIFICANCE, score_block,
)
from graph_scale_dynamics.scaleflow.probes import Bucket

FLOORS = {64: 0.30, 256: 0.30, 1024: 0.30, 4096: 0.30, 16384: 0.30}
SIZES = [64, 256, 1024, 4096, 16384]


def block(values, buckets=None, ses=None, sizes=None):
    sizes = sizes or SIZES[:len(values)]
    return score_block(values, buckets or [None] * len(values), floor=0.30,
                       sizes=sizes, floors_by_n=FLOORS, ses=ses)


def test_a_settled_probe_converges():
    out = block([1.30, 1.24, 1.26, 1.25, 1.252], ses=[0.05] * 5)
    assert out["bucket"] == Bucket.CONVERGED.value
    assert out["score"] == BLOCK_POINTS


def test_a_climb_larger_than_its_error_bars_is_not_convergence():
    out = block([1.17, 1.35, 1.55, 1.72, 1.87], ses=[0.02] * 5)
    assert out["constancy_p"] < CONSTANCY_SIGNIFICANCE
    assert out["moves_beyond_its_errors"] is True
    assert out["bucket"] == Bucket.DRIFTING_MONOTONICALLY.value
    assert out["score"] < BLOCK_POINTS


def test_the_same_climb_inside_wide_error_bars_is_not_convicted():
    tight = block([1.17, 1.35, 1.55, 1.72, 1.87], ses=[0.02] * 5)
    loose = block([1.17, 1.35, 1.55, 1.72, 1.87], ses=[0.6] * 5)
    assert tight["moves_beyond_its_errors"] is True
    assert loose["moves_beyond_its_errors"] is False
    assert loose["constancy_p"] > tight["constancy_p"]


def test_direction_alone_does_not_convict():
    out = block([1.00, 1.20, 1.30, 1.35, 1.37], ses=[0.5] * 5)
    assert out["monotone"] is True
    assert out["bucket"] == Bucket.CONVERGED.value


def test_a_shrink_ratio_of_noise_over_noise_does_not_convict():
    out = block([2.000, 1.982, 1.976, 1.953], ses=[0.18] * 4, sizes=SIZES[:4])
    assert out["monotone"] is True
    assert out["shrink_ratio"] > 1.0
    assert out["bucket"] == Bucket.CONVERGED.value


def test_a_block_without_standard_errors_keeps_the_older_behaviour():
    out = block([1.17, 1.35, 1.55, 1.72, 1.87])
    assert out["constancy_p"] is None
    assert out["moves_beyond_its_errors"] is False


def test_a_probe_measured_then_lost_is_not_a_probe_never_attempted():
    lost = block([1.2, 1.25, 1.24, 1.26, None], ses=[0.05] * 5,
                 buckets=[None, None, None, None, Bucket.REFUSED_NO_SCALING_WINDOW.value])
    assert lost["bucket"] == Bucket.DEGRADED_WITH_N.value
    assert lost["top_rung_bucket"] == Bucket.REFUSED_NO_SCALING_WINDOW.value
    assert lost["measured_through_n"] == 4096
    assert lost["score"] == 0.0
    assert lost["degraded_from_valid_rungs"] == lost["valid_rungs"]

    never = block([None] * 5, buckets=[Bucket.NOT_ATTEMPTED.value] * 5)
    assert never["bucket"] != Bucket.DEGRADED_WITH_N.value


def test_no_block_can_score_below_zero():
    cases = {
        "degraded late": dict(
            values=[1.20, 1.25, 1.24, 1.26, None], ses=[0.05] * 5,
            buckets=[None, None, None, None, Bucket.REFUSED_NO_SCALING_WINDOW.value]),
        "degraded early": dict(
            values=[1.20, 1.25, None, None, None], ses=[0.05] * 5,
            buckets=[None, None] + [Bucket.REFUSED_NO_SCALING_WINDOW.value] * 3),
        "runaway": dict(values=[1.00, 1.01, 1.30, 2.20], ses=[0.01] * 4,
                        sizes=SIZES[:4]),
        "never attempted": dict(values=[None] * 4,
                                buckets=[Bucket.NOT_ATTEMPTED.value] * 4,
                                sizes=SIZES[:4]),
    }
    for name, kwargs in cases.items():
        out = block(**kwargs)
        assert 0.0 <= out["score"] <= BLOCK_POINTS, (name, out["score"])


def test_a_runaway_is_still_named_as_one_at_zero():
    out = block([1.00, 1.01, 1.30, 2.20], ses=[0.01] * 4, sizes=SIZES[:4])
    assert out["score"] == 0.0
    assert out["moves_beyond_its_errors"] is True
    assert out["bucket"] in {Bucket.DRIFTING_MONOTONICALLY.value,
                             Bucket.STILL_DRIFTING.value}
    assert out["shrink_ratio"] > 1.0, "the ratio that produced the old penalty is still reported"
