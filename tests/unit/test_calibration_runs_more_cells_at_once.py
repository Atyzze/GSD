from __future__ import annotations

import pytest

from graph_scale_dynamics.calibration import admission as A
from tests.support import pacing_sim as P

GIB = P.GIB
PEAKS = {"in proportion": None,
         "like the host's honeycomb": {"periodic_square_lattice": 5.5 * GIB,
                                       "periodic_triangular_lattice": 6.0 * GIB}}


@pytest.fixture(scope="module", params=sorted(PEAKS))
def both(request):
    peaks = PEAKS[request.param]
    old = P.simulate(P.operators_21(peaks=peaks), rule="526", available=int(66.8 * GIB), tick=4.0)
    new = P.simulate(P.operators_21(peaks=peaks), rule="527", available=int(66.8 * GIB), tick=4.0)
    return old, new


def test_every_cell_finishes_and_none_is_ended(both):
    _old, new = both
    assert new["finished"] == 21 and new["blocked"] == 0 and new["ended"] == 0, new


def test_the_run_takes_at_most_two_thirds_of_526s_time(both):
    old, new = both
    assert new["hours"] <= 0.67 * old["hours"], (old, new)


def test_half_as_many_cells_again_run_at_once_and_hold_half_as_much_memory_again(both):
    old, new = both
    assert new["mean_running"] >= 1.5 * old["mean_running"], (old, new)
    assert new["mean_held_gib"] >= 1.5 * old["mean_held_gib"], (old, new)
    assert new["most_running"] >= old["most_running"] + 3, (old, new)


def test_the_host_never_goes_under_its_floor(both):
    _old, new = both
    assert new["lowest_available_gib"] >= 10.0, new


def test_the_rules_the_simulation_chose_are_the_ones_the_suite_runs():
    assert A.SPIKE_OVERLAP == 1 and A.TYPICAL_SHARE == 0.4 and A.PAUSE_MARGIN_BYTES == 2 * GIB
