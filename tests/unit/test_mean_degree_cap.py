from __future__ import annotations

from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.scheduling.limits import limits, mean_degree_cap_armed

BASE = [64, 256, 1024, 4096, 16384]
WINDOW = {"mean_degree_window": {"min": 1.5, "max": 8.0}}


def test_the_cap_is_armed_from_the_first_rung_by_default():
    assert limits({})["mean_degree_cap_armed_from_n"] == 0
    for n in BASE:
        assert mean_degree_cap_armed({"limits": WINDOW}, n) is True
        assert one_shot_policy({"limits": WINDOW}, n)["mean_degree_cap"] == 8.0


def test_arming_the_cap_late_withholds_it_below_that_rung():
    spec = {"limits": dict(WINDOW, mean_degree_cap_armed_from_n=1024)}
    assert one_shot_policy(spec, 64)["mean_degree_cap"] is None
    assert one_shot_policy(spec, 256)["mean_degree_cap"] is None
    assert one_shot_policy(spec, 1024)["mean_degree_cap"] == 8.0
    assert one_shot_policy(spec, 16384)["mean_degree_cap"] == 8.0


def test_the_window_itself_is_unchanged_by_arming():
    spec = {"limits": dict(WINDOW, mean_degree_cap_armed_from_n=4096)}
    assert limits(spec)["mean_degree_window"] == {"min": 1.5, "max": 8.0}
