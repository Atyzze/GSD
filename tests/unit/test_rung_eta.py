from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.rung_eta import (
    CENSOR_FLOOR_FRACTION, MIN_SAMPLES, _ceiling, classify_attempts,
    kaplan_meier, quantile, remaining, rung_duration,
)

ROOT = Path(__file__).resolve().parents[2]


def att(wall, exit_code=0):
    return {"wall_seconds": wall, "exit_code": exit_code}


def test_censored_attempts_raise_the_median_above_the_completions_only_answer():
    rows = [att(w) for w in (300, 320, 340, 360, 380, 400)] + [att(3600, -9)] * 4
    completions_only = statistics.median([300, 320, 340, 360, 380, 400])
    estimate = rung_duration(rows, ceiling=3600)
    assert estimate["identifiable"]
    assert estimate["median_seconds"] > completions_only, \
        "ignoring the attempts that ran long biases the median low"
    assert estimate["completed"] == 6 and estimate["censored"] == 4


def test_median_is_refused_when_most_attempts_never_finish():
    rows = [att(w) for w in (300, 320, 340)] + [att(3600, -9)] * 7
    estimate = rung_duration(rows, ceiling=3600)
    assert estimate["median_seconds"] is None
    assert estimate["identifiable"] is False
    assert "not identifiable" in estimate["reason"]
    assert estimate["exceeds_seconds"] == 3600


def test_short_crashes_are_discarded_rather_than_censored():
    rows = [att(w) for w in (300, 320, 340, 360, 380, 400)] + [att(2, 1), att(1.5, 1)]
    estimate = rung_duration(rows, ceiling=3600)
    assert estimate["discarded_short_failures"] == 2
    assert estimate["censored"] == 0
    assert estimate["attempts"] == 6


def test_the_censor_boundary_is_a_declared_fraction_of_the_ceiling():
    ceiling = 1000.0
    boundary = ceiling * CENSOR_FLOOR_FRACTION
    just_under = classify_attempts([att(boundary - 1, 1)], ceiling=ceiling)
    just_over = classify_attempts([att(boundary + 1, 1)], ceiling=ceiling)
    assert just_under["discarded_short_failures"] == 1 and not just_under["censored"]
    assert len(just_over["censored"]) == 1 and not just_over["discarded_short_failures"]


def test_too_few_attempts_declines_rather_than_fitting_three_numbers():
    estimate = rung_duration([att(300), att(320), att(340)], ceiling=3600)
    assert estimate["median_seconds"] is None
    assert str(MIN_SAMPLES) in estimate["reason"]


def test_no_completions_at_all_declines():
    estimate = rung_duration([att(3600, -9)] * 8, ceiling=3600)
    assert estimate["median_seconds"] is None
    assert "has finished" in estimate["reason"]


def test_kaplan_meier_reduces_to_the_plain_median_with_no_censoring():
    events = [10.0, 20.0, 30.0, 40.0, 50.0]
    curve = kaplan_meier(events, [])
    assert quantile(curve, 0.5) == 30.0


def test_censoring_before_an_event_raises_the_survival_curve():
    plain = quantile(kaplan_meier([10.0, 20.0, 30.0, 40.0], []), 0.5)
    censored = quantile(kaplan_meier([10.0, 20.0, 30.0, 40.0], [15.0, 15.0]), 0.5)
    assert censored >= plain


def test_quantile_returns_none_rather_than_the_largest_time():
    curve = kaplan_meier([10.0], [20.0] * 9)
    assert quantile(curve, 0.5) is None


def test_the_ceiling_is_the_budget_s_estimate_in_seconds_and_stops_nothing():
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scheduling.limits import estimated_seconds
    spec = shipped_spec()
    assert _ceiling(spec, 4096) == estimated_seconds(spec, 4096) > 0
    assert _ceiling({}) == float("inf") and _ceiling(spec) == float("inf"), "no size, no budget to estimate"


@pytest.mark.parametrize("elapsed,expect", [(100, "remaining"), (500, "overdue")])
def test_a_job_past_its_own_quartile_reads_as_overdue_not_as_nearly_done(elapsed, expect):
    estimate = rung_duration([att(w) for w in (300, 310, 320, 330, 340, 350, 360, 370)],
                             ceiling=3600)
    progress = remaining(estimate, elapsed)
    if expect == "overdue":
        assert progress["overdue"] and progress["overdue_by_seconds"] > 0
        assert progress["remaining_seconds"] is None
    else:
        assert not progress["overdue"] and progress["remaining_seconds"] > 0


def test_remaining_is_silent_when_the_estimate_is_not_identifiable():
    estimate = rung_duration([att(300)] * 3 + [att(3600, -9)] * 7, ceiling=3600)
    progress = remaining(estimate, 1200)
    assert progress["remaining_seconds"] is None
    assert progress["identifiable"] is False
    assert progress["elapsed_seconds"] == 1200


def test_the_eta_ceiling_follows_the_campaign_s_budget_not_a_constant():
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scheduling.rung_eta import _ceiling, job_budget_seconds
    spec = shipped_spec()
    assert _ceiling(spec, 65536) > _ceiling(spec, 4096)
    job = {"spec": {"execution": {"one_shot": {"work_budget": 10 ** 12,
                                               "work_unit": {"seconds_a_unit": 2e-10}}}}}
    assert job_budget_seconds(job) == 200.0
