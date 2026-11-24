from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research.stability_score import (  # noqa: E402
    BLOCK_POINTS, DENSITY_CLAMPED_BUCKET, SCORED_BLOCKS, UNSCORED_BLOCKS,
    density_diagnostic, score_density_block, score_law,
)
from graph_scale_dynamics.scaleflow.probes import PROBES  # noqa: E402

SIZES = [64, 256, 1024, 4096, 16384]
FLOORS = {probe: 0.05 for probe in PROBES}
CLAMPED = "REFUSED_MEAN_DEGREE_ABOVE_WINDOW"

PINNED = [8.03, 8.01, 8.00, 8.00, 8.00]


def _converged(values):
    return {probe: (list(values) if probe == "d_s" else [None] * len(values))
            for probe in PROBES}


def test_the_cap_trajectory_still_looks_settled_to_a_naive_drift_test():
    steps = [abs(b - a) / a for a, b in zip(PINNED, PINNED[1:], strict=False)]
    assert max(steps[-2:]) <= 0.01, steps


def test_a_cap_pinned_law_no_longer_scores_the_density_block():
    buckets = [None, None, CLAMPED, CLAMPED, CLAMPED]
    density = density_diagnostic(PINNED, SIZES, rung_buckets=buckets)
    assert density["clamped_rungs"] == [1024, 4096, 16384]
    assert density["evaluable"] is False, "two unclamped rungs cannot show deceleration"
    block = score_density_block(density)
    assert block["score"] == 0.0
    assert block["settled"] is False


def test_the_same_law_scored_in_full_before_the_buckets_were_read():
    naive = density_diagnostic(PINNED, SIZES)
    assert naive["settled"] is True
    assert score_density_block(naive)["score"] == BLOCK_POINTS


def test_clamped_is_distinguishable_from_never_measured():
    clamped = score_density_block(
        density_diagnostic(PINNED, SIZES, rung_buckets=[None, None, CLAMPED, CLAMPED, CLAMPED]))
    absent = score_density_block(density_diagnostic([None] * 5, SIZES))
    assert clamped["score"] == absent["score"] == 0.0
    assert clamped["bucket"] == DENSITY_CLAMPED_BUCKET
    assert absent["bucket"] != DENSITY_CLAMPED_BUCKET
    assert clamped["clamped_rungs"] == [1024, 4096, 16384]


def test_a_law_that_settles_inside_the_window_is_untouched():
    real = [2.40, 2.32, 2.29, 2.29, 2.29]
    density = density_diagnostic(real, SIZES, rung_buckets=[None] * 5)
    assert density["evaluable"] and density["settled"]
    assert density["clamped_rungs"] == []
    assert score_density_block(density)["score"] == BLOCK_POINTS


def test_an_unclamped_prefix_survives_a_clamped_tail():
    degrees = [2.40, 2.32, 2.29, 8.00, 8.00]
    density = density_diagnostic(degrees, SIZES,
                                 rung_buckets=[None, None, None, CLAMPED, CLAMPED])
    assert density["evaluable"] and density["rungs_compared"] == 3
    assert density["clamped_rungs"] == [4096, 16384]


def test_the_scale_is_two_blocks_of_fifty():
    assert BLOCK_POINTS == 50.0
    assert SCORED_BLOCKS == ("d_s", "mean_degree")
    assert set(UNSCORED_BLOCKS) == set(PROBES) - {"d_s"}


def test_a_settled_d_s_off_the_line_on_a_settled_ensemble_scores_one_hundred():
    scored = score_law(_converged([2.0] * 5), None, floors=FLOORS, sizes=SIZES,
                       mean_degree_vector=[2.25] * 5)
    assert scored["blocks"]["d_s"]["score"] == BLOCK_POINTS
    assert scored["blocks"]["mean_degree"]["score"] == BLOCK_POINTS


@pytest.mark.parametrize("probe", ["d_V", "d_B", "d_w"])
def test_an_unscored_probe_is_measured_reported_and_worth_nothing(probe):
    vectors = _converged([2.0] * 5)
    vectors[probe] = [3.0] * 5
    scored = score_law(vectors, None, floors=FLOORS, sizes=SIZES,
                       mean_degree_vector=[2.25] * 5)
    block = scored["blocks"][probe]
    assert block["bucket"] == "CONVERGED", "still measured, still judged"
    assert block["scored"] is False
    assert block["score"] == 0.0
    assert block["unscored_score"] == BLOCK_POINTS, "what it would have been worth"
    assert (scored["blocks"]["d_s"]["score"], scored["blocks"]["mean_degree"]["score"]) == (
        BLOCK_POINTS, BLOCK_POINTS), "d_s and the ensemble, and nothing from this probe"


def test_approach_is_a_fraction_on_both_paths():
    settled = score_density_block(density_diagnostic([2.29] * 5, SIZES, rung_buckets=[None] * 5))
    assert settled["approach"] == 1.0
    partial = score_density_block(
        density_diagnostic([2.0, 2.6, 2.75, 2.80, 2.82], SIZES, rung_buckets=[None] * 5))
    assert 0.0 <= partial["approach"] <= 1.0


def test_the_shipped_spec_opens_the_window_and_arms_the_cap_above_the_cheap_rungs():
    spec = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))
    assert spec["limits"]["mean_degree_window"] == {"min": 0.0, "max": 16.0}
    assert spec["limits"]["mean_degree_cap_armed_from_n"] == 256, (
        "build 425: armed from 256, not 1024. Measured on the 424 bundle: at N=256 the mean degree quantiles are 1.5 / 8.0 / 41.0 / 255.0 and the MAX IS 255.0, the complete graph. 18.2% of laws exceed 16 there and 6.6% reach 128+, and N=256 was 46.9% of all simulation wall. At N=64 the same laws top out at 63.0, also complete, for 3.7%. One unclamped rung shows the divergence; the second shows it again at sixteen times the edges")
    armed = spec["limits"]["mean_degree_cap_armed_from_n"]
    free = [n for n in spec["base_block"]["sizes"] if n < armed]
    assert free == [64], (
        "build 425: a ONE-rung unclamped prefix. Two rungs measured the same "
        "runaway twice and the second cost half the campaign.")
    assert spec["auto_continuation"]["min_tier"] == 1, (
        "declared, not inherited from the environment: the tier counts scored "
        "probes and this campaign scores one, so a min_tier of 2 would be an "
        "unreachable gate wearing the costume of a strict one")
