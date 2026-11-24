from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.observability.chain_mixing import (
    CONTRACT, MIN_POINTS, rung_mixing, seed_chain_moments, split_rhat)
from tests.support import chains as SC


def _chain(rng, points, shift=0.0, n=64):
    return [{"energy": float(rng.normal(-1.0 + shift, 0.1)) * n, "mean_degree": float(rng.normal(3.0, 0.05)),
             "isolated_fraction": 0.0} for _ in range(points)]


def _envelope(rng, *, shift=0.0, points=240, given_points=80, timing=(1.0, 0.5)):
    return {**SC.pair(64, _chain(rng, points, shift), _chain(rng, given_points)),
            "rung_terminal": {"timing": {"chain_seconds": {"empty": timing[0], "given": timing[1]}}}}


def _seed(rng, **kwargs):
    return {"chain_mixing": seed_chain_moments(_envelope(rng, **kwargs))}


def test_agreeing_chains_sit_at_their_equilibrium_value():
    rng = np.random.default_rng(7)
    body = rung_mixing([_seed(rng) for _ in range(3)])
    energy = body["observables"]["energy_per_node"]
    assert body["contract"] == CONTRACT and energy["half_chains"] == 12
    assert abs(energy["split_rhat"] - 1.0) < 0.03
    assert abs(energy["excess"]) < 0.03
    assert math.isclose(energy["equilibrium_rhat"], math.sqrt(1 + 2 / energy["effective_samples_per_chain"]),
                        rel_tol=1e-4)


def test_one_chain_stuck_two_standard_deviations_away_shows_as_excess():
    rng = np.random.default_rng(7)
    stuck = rung_mixing([_seed(rng, shift=0.2)] + [_seed(rng) for _ in range(2)])
    agreeing = rung_mixing([_seed(rng) for _ in range(3)])
    assert stuck["observables"]["energy_per_node"]["excess"] > 0.1
    assert stuck["observables"]["energy_per_node"]["excess"] > agreeing["observables"]["energy_per_node"]["excess"] + 0.1


def test_a_constant_observable_reads_one_and_a_short_chain_reads_nothing():
    rng = np.random.default_rng(3)
    body = rung_mixing([_seed(rng) for _ in range(3)])
    assert body["observables"]["isolated_fraction"]["split_rhat"] == 1.0
    short = rung_mixing([_seed(rng, points=2 * MIN_POINTS - 2, given_points=2 * MIN_POINTS - 2)])
    assert short["observables"]["energy_per_node"] == {
        "split_rhat": None, "half_chains": 0, "effective_samples_per_chain": None,
        "equilibrium_rhat": None, "excess": None}


def test_a_seed_without_moments_is_counted_as_such():
    rng = np.random.default_rng(5)
    body = rung_mixing([_seed(rng), {"health": {}}])
    assert (body["seeds"], body["seeds_with_moments"]) == (2, 1)


def test_given_chain_verdicts_and_the_chain_time_split_travel_beside_it():
    rng = np.random.default_rng(11)
    disagreed = _seed(rng, timing=(2.0, 1.0)) | {"health": {"rung_terminal": {"failures": [
        {"code": "STARTS_DISAGREED"}]}}}
    body = rung_mixing([disagreed, _seed(rng, timing=(1.0, 0.5))])
    assert body["chain_seconds"] == {"empty": 3.0, "given": 1.5}
    from graph_scale_dynamics.scaleflow.equilibration import CHAINS_DISAGREED_CODES
    assert "STARTS_DISAGREED" in CHAINS_DISAGREED_CODES
    assert body["seeds_with_chains_disagreement"] == 1


def test_split_rhat_is_the_textbook_formula():
    halves = [{"count": 10, "mean": 0.0, "variance": 1.0}, {"count": 10, "mean": 1.0, "variance": 1.0}]
    within, between = 1.0, 10 * np.var([0.0, 1.0], ddof=1)
    assert math.isclose(split_rhat(halves), math.sqrt((9 / 10 * within + between / 10) / within))
    assert split_rhat(halves[:1]) is None
