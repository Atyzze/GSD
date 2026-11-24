from __future__ import annotations

import pytest

from graph_scale_dynamics.observability import work_left as W

def _finished(seconds, count=10):
    return [{"wall_seconds": seconds, "exit_code": 0} for _ in range(count)]


def test_queued_seeds_are_priced_by_what_a_seed_took_at_their_rung_and_analyses_at_the_campaigns_ratio():
    result = W.estimate(spec={}, queued_by_n={4096: 10, 65536: 2, 1048576: 1},
                        durations_by_n={4096: _finished(36.0), 65536: _finished(1800.0)}, laws_total=0,
                        law_budget=None, simulation_core_seconds=100.0, analysis_core_seconds=25.0,
                        pace_core_seconds=3600.0 * 2, share_cores=4)
    assert result["graphs_queued"] == 13 and result["queued_core_hours"] == pytest.approx(1.1)
    assert result["unpriced_rungs"] == [1048576], "a rung with no finished seed is named, not guessed"
    assert result["core_hours_left"] == pytest.approx(1.1 * 1.25, abs=0.01)
    assert result["hours_at_last_hours_pace"] == pytest.approx(1.1 * 1.25 / 2, abs=0.05)
    assert result["hours_at_fair_share"] == pytest.approx(1.1 * 1.25 / 4, abs=0.05)
    assert result["laws_to_budget"] == 0, "no budget (the standing controls): the queued seeds are the work"


def test_a_rung_whose_seeds_mostly_reach_their_budget_s_estimate_is_priced_at_a_floor():
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    spec = shipped_spec()
    spec["engine"]["policy"]["work_budgets"] = [[4096, 10 ** 12]]
    spec["engine"]["policy"]["seconds_a_unit"] = 1e-10
    rows = [{"wall_seconds": 99.0, "exit_code": 1}] * 8 + _finished(20.0, 2)
    seconds, floor = W.seed_seconds(spec, 4096, rows)
    assert floor and seconds >= 99.0


def test_nothing_queued_and_no_budget_is_done_now():
    result = W.estimate(spec={}, queued_by_n={}, durations_by_n={}, laws_total=5, law_budget=None,
                        simulation_core_seconds=10.0, analysis_core_seconds=0.0, pace_core_seconds=0.0, share_cores=None)
    assert result["core_hours_left"] == 0.0 and result["hours_at_last_hours_pace"] == 0.0


def test_a_fair_share_is_the_declared_one_or_an_equal_part_of_what_the_shares_leave():
    rows = [{"campaign_id": "1", "status": "active", "state": "active", "worker_share": 8},
            {"campaign_id": "2", "status": "active", "state": "active", "worker_share": "all"},
            {"campaign_id": "3", "status": "active", "state": "active", "worker_share": "all"},
            {"campaign_id": "4", "status": "active", "state": "done", "worker_share": "all"},
            {"campaign_id": "5", "status": "active", "state": "paused", "worker_share": 0}]
    assert W._share_cores(rows, 32) == {"1": 8, "2": 12.0, "3": 12.0}


DEEP = {16384: _finished(100.0, 9) + _finished(700.0, 1), 65536: _finished(540.0, 8) + _finished(1400.0, 2)}
LADDER = [64, 256, 1024, 4096, 16384, 65536]


def _to_come(**changes):
    given = {"climbing_by_n": {16384: 509, 65536: 248}, "measured_by_n": {4096: 1057, 16384: 345, 65536: 66},
             "bought_by_n": {4096: 1057, 16384: 906, 65536: 314}, "durations_by_n": DEEP, "seeds": 3, "ladder": LADDER}
    return W.sizes_to_come(**{**given, **changes})


def test_the_sizes_to_come_are_the_share_of_laws_that_went_on_times_a_seeds_mean_time_there():
    to_come = _to_come()
    assert to_come["mean_seed_seconds"] == {16384: pytest.approx(160.0), 65536: pytest.approx(712.0)}, (
        "the mean, which the slow seeds raise above the median of 100 and 540: a sum over many laws follows it")
    assert to_come["seconds"] == pytest.approx(509 * (314 / 345) * 3 * 712.0), (
        "509 laws with seeds at 16,384, 314 of the 345 measured there went on, three seeds a law at 65,536")
    assert to_come["unpriced"] == []


def test_a_law_at_the_largest_size_buys_nothing_more_and_a_share_is_never_above_one():
    assert _to_come(climbing_by_n={65536: 248})["seconds"] == 0.0
    more = _to_come(climbing_by_n={16384: 10}, bought_by_n={16384: 906, 65536: 400})
    assert more["seconds"] == pytest.approx(10 * 3 * 712.0), "more laws bought than measured below is every law, not more"


def test_a_size_no_seed_finished_at_or_no_law_was_measured_below_is_named_and_not_guessed():
    unseen = _to_come(climbing_by_n={4096: 10}, durations_by_n={65536: DEEP[65536]})
    assert unseen["seconds"] == 0.0 and unseen["unpriced"] == [16384], "no seed has finished at 16,384"
    unmeasured = _to_come(climbing_by_n={4096: 10}, measured_by_n={16384: 345})
    assert unmeasured["seconds"] == 0.0 and unmeasured["unpriced"] == [16384], "no law is measured at 4,096"
    few = _to_come(climbing_by_n={16384: 10}, durations_by_n={65536: _finished(540.0, 4)})
    assert few["seconds"] == 0.0 and few["unpriced"] == [65536], "four finished seeds price no size, as for the queue"
    beyond = _to_come(climbing_by_n={16384: 10}, ladder=LADDER + [262144])
    assert beyond["unpriced"] == [262144], "the size the ladder declares above the last one a seed finished at"
    assert beyond["seconds"] == pytest.approx(10 * (314 / 345) * 3 * 712.0), "what can be priced below it still is"


def test_the_work_expected_takes_the_queued_seeds_at_their_mean_and_adds_the_sizes_to_come():
    to_come = _to_come()
    result = W.estimate(spec={}, queued_by_n={16384: 1351, 65536: 726}, durations_by_n=DEEP, laws_total=2500,
                        law_budget=2500, simulation_core_seconds=1000.0, analysis_core_seconds=300.0,
                        pace_core_seconds=3600.0 * 16, share_cores=None, laws_climbing=757, to_come=to_come)
    at_the_median = 1351 * 100.0 + 726 * 540.0
    at_the_mean = 1351 * 160.0 + 726 * 712.0
    assert result["core_hours_left"] == pytest.approx(at_the_median * 1.3 / 3600.0, abs=0.01), "at least, as before"
    assert result["queued_core_hours_at_the_mean"] == pytest.approx(at_the_mean / 3600.0, abs=0.01)
    assert result["sizes_to_come_core_hours"] == pytest.approx(to_come["seconds"] / 3600.0, abs=0.01)
    expected = (at_the_mean + to_come["seconds"]) * 1.3 / 3600.0
    assert result["core_hours_expected"] == pytest.approx(expected, abs=0.01)
    assert result["hours_expected_at_last_hours_pace"] == pytest.approx(expected / 16.0, abs=0.05)
    assert result["core_hours_expected"] > 3 * result["core_hours_left"], (
        "study 172 at its progress bundle: 191 core-hours queued at the median, 622 expected, 673 forecast by hand")


def test_with_no_sizes_to_come_the_work_expected_is_the_work_queued():
    result = W.estimate(spec={}, queued_by_n={4096: 10}, durations_by_n={4096: _finished(36.0)}, laws_total=0,
                        law_budget=None, simulation_core_seconds=100.0, analysis_core_seconds=25.0,
                        pace_core_seconds=7200.0, share_cores=4)
    assert result["core_hours_expected"] == result["core_hours_left"] and result["sizes_to_come_core_hours"] == 0.0
    assert result["sizes_to_come_unpriced"] == []


def test_the_sizes_a_study_declares_are_its_ladder_and_every_size_it_budgets():
    spec = {"ladder": [64, 256, 1024, 4096],
            "engine": {"policy": {"work_budgets": [[4096, 10 ** 12], [16384, 8 * 10 ** 12], [65536, 24 * 10 ** 12]]}}}
    assert W._sizes_declared(spec) == [64, 256, 1024, 4096, 16384, 65536]
    assert W._sizes_declared({}) == []

