from __future__ import annotations

import numpy as np

from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.observability.chain_mixing import rung_mixing
from graph_scale_dynamics.observability.meeting_reading import (
    CONTRACT, MIN_POINTS, READINGS, rung_meeting_reading, seed_meeting_reading)
from graph_scale_dynamics.scaleflow import engine_door
from tests.support import chains as SC

N = 64
LAW = {"dsl_version": 1, "init": "empty",
       "dynamics": {"kind": "equilibrium", "beta": 1.0, "sweeps": 400,
                    "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}},
       "terms": [{"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 1.0, "scale": "one"}}]}


def _rows(values_energy, values_degree, *, moving=True, edges=100):
    rows, accepted = [], 0
    for i, (e, d) in enumerate(zip(values_energy, values_degree, strict=True)):
        accepted += 20 if moving else 0
        rows.append({"move": i * 100, "energy": float(e) * N, "mean_degree": float(d),
                     "edges": edges + (i % 3 if moving else 0), "accepted_add": accepted,
                     "accepted_delete": 0, "accepted_swap": 0})
    return rows


def _envelope(from_empty, given):
    return SC.pair(N, from_empty, given)


def test_a_real_run_of_an_equilibrium_law_reads_agreeing():
    envelope = engine_door.run_simulation(LAW, N, 11, record_points=80)
    reading = seed_meeting_reading(envelope)
    assert reading["contract"] == CONTRACT
    assert reading["reading"] in ("agreeing", "converging"), reading
    assert all(reading["moving"].values()), "both chains of an equilibrium law move"


def test_two_chains_frozen_in_different_states_read_frozen():
    from_empty = _rows([-1.0] * 60, [4.0] * 60, moving=False)
    given = _rows([-0.5] * 60, [6.0] * 60, moving=False, edges=190)
    reading = seed_meeting_reading(_envelope(from_empty, given))
    assert reading["reading"] == "frozen" and reading["frozen"] == ["empty", "given"]


def test_a_gap_that_halves_while_both_move_reads_converging():
    rng = np.random.default_rng(1)
    t = np.arange(120)
    given_energy = -1.0 + 0.6 * np.exp(-t / 25.0) + rng.normal(0, 0.002, 120)
    from_empty = _rows(-1.0 + rng.normal(0, 0.002, 120), 4.0 + rng.normal(0, 0.01, 120))
    given = _rows(given_energy, 4.0 + 1.0 * np.exp(-t / 25.0) + rng.normal(0, 0.01, 120))
    assert seed_meeting_reading(_envelope(from_empty, given))["reading"] == "converging"


def test_a_gap_that_holds_while_both_move_reads_disagreeing_while_moving():
    rng = np.random.default_rng(2)
    from_empty = _rows(-1.0 + rng.normal(0, 0.01, 120), 4.0 + rng.normal(0, 0.02, 120))
    given = _rows(-0.7 + rng.normal(0, 0.01, 120), 5.0 + rng.normal(0, 0.02, 120))
    assert seed_meeting_reading(_envelope(from_empty, given))["reading"] == "disagreeing_while_moving"


def test_agreeing_chains_and_chains_frozen_in_the_same_state_read_agreeing():
    rng = np.random.default_rng(3)
    same = seed_meeting_reading(_envelope(_rows(-1.0 + rng.normal(0, 0.01, 120), 4.0 + rng.normal(0, 0.02, 120)),
                                       _rows(-1.0 + rng.normal(0, 0.01, 120), 4.0 + rng.normal(0, 0.02, 120))))
    assert same["reading"] == "agreeing"
    empty = seed_meeting_reading(_envelope(_rows([0.0] * 60, [0.0] * 60, moving=False),
                                        _rows([0.0] * 60, [0.0] * 60, moving=False)))
    assert empty["reading"] == "agreeing"


def test_too_few_points_or_no_given_chain_is_refused_not_guessed():
    short = _rows([-1.0] * (2 * MIN_POINTS), [4.0] * (2 * MIN_POINTS))
    assert seed_meeting_reading(_envelope(short, short))["reading"] == "not_enough_points"
    alone = seed_meeting_reading(SC.pair(N, _rows([-1.0] * 60, [4.0] * 60)))
    assert alone["reading"] == "not_enough_points" and "no trajectory of the given chain" in alone["why"]


def test_the_rung_names_its_most_common_seed_reading_ties_to_the_more_severe():
    seeds = [{"meeting_reading": {"reading": r}} for r in ("agreeing", "frozen", "frozen", "converging")]
    assert rung_meeting_reading(seeds)["reading"] == "frozen"
    tie = [{"meeting_reading": {"reading": r}} for r in ("agreeing", "disagreeing_while_moving")]
    assert rung_meeting_reading(tie)["reading"] == "disagreeing_while_moving"
    assert rung_meeting_reading([{}])["reading"] is None
    assert set(rung_meeting_reading(seeds)["counts"]) == set(READINGS)
    assert rung_mixing(seeds)["meeting_reading"]["reading"] == "frozen", "the rung diagnostics carry it"


def test_nothing_decides_on_it():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "graph_scale_dynamics"
    for folder in ("decisions", "scaleflow", "measurements", "research"):
        for path in (root / folder).rglob("*.py"):
            assert "meeting_reading" not in path.read_text(encoding="utf-8"), path
