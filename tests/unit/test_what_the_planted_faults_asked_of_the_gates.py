from __future__ import annotations

import json
from dataclasses import replace

import pytest

from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions.decider import decide_pass
from graph_scale_dynamics.decisions.engine import Policy, Rung, Seed
from graph_scale_dynamics.decisions.replay import replay_matches
from tests.unit.test_decider import FakeStore, entry

THREE = replace(Policy(dense_cap=32.0), fact_sizes_in_a_row=3)
SIZES = (64, 256, 1024)


def _row(*degrees: float) -> list[Rung]:
    return [Rung(n=n, mean_degree=d, connected_fraction=1.0) for n, d in zip(SIZES, degrees, strict=True)]


def test_a_law_just_above_the_empty_mark_is_not_empty_and_one_at_it_is():
    mark = THREE.empty_mean_degree
    assert E._empty(_row(2.4 * mark, 2.2 * mark, 2.0 * mark), THREE) is None, "twice the mark is not empty"
    assert E._empty(_row(1.2 * mark, 1.1 * mark, 1.05 * mark), THREE) is None, "just above the mark is not empty"
    assert E._empty(_row(mark, 0.9 * mark, 0.8 * mark), THREE) is not None, "at the mark and below, falling"


def _seeded(n: int, units: int, moves: int, multiplier: int) -> Rung:
    seed = Seed(first_chunk_units=units, first_chunk_moves=moves, first_multiplier=multiplier)
    return Rung(n=n, mean_degree=4.0, connected_fraction=1.0, seeds=(seed, seed, seed))


def test_a_first_chunk_predicted_past_the_budget_does_not_fit_and_one_within_it_does():
    policy = replace(THREE, work_budgets=((1024, 1_000_000), (4096, 4_000_000)))
    within = E.first_chunk_prediction([_seeded(1024, 750_000, 1000, 1)], policy, 4096)
    assert within["predicted"] == 3_000_000 and within["budget"] == 4_000_000 and within["fits"] is True
    past = E.first_chunk_prediction([_seeded(1024, 1_500_000, 1000, 1)], policy, 4096)
    assert past["predicted"] == 6_000_000 and past["fits"] is False, "half again the budget does not fit"
    at = E.first_chunk_prediction([_seeded(1024, 1_000_000, 1000, 1)], policy, 4096)
    assert at["predicted"] == at["budget"] and at["fits"] is True, "exactly the budget fits"


def _recorded() -> dict:
    store = FakeStore(["law-new"], entries={"law-new": {n: entry(2.5, d_s=1.0, se=0.01) for n in (64, 256)}})
    decide_pass(store, "1", Policy(promising_bar=False))
    row = json.loads(json.dumps(store.decisions[0], default=str))
    return dict(row, facts_json=json.dumps(row["facts"]))


@pytest.mark.parametrize("key,other", [("action", "stop"), ("rule", "empty"), ("next_n", 1048576), ("priority", 99),
                                       ("reason", "another reason")])
def test_a_record_that_says_another_decision_than_its_inputs_give_does_not_replay(key, other):
    row = _recorded()
    assert replay_matches(row)["matches"] is True
    changed = replay_matches(dict(row, **{key: other}))
    assert changed["matches"] is False and any(d.startswith(f"{key}: ") for d in changed["differences"]), changed
