from __future__ import annotations

import random

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.services.proposer.blind import blind_batch

WHITELIST = ["edge_count", "degree_anchor", "triangle_count", "degree_fourth_sum", "degree_square_sum"]


def _batch(seed, ledger=None, existing=None):
    return blind_batch(random.Random(seed), 6, WHITELIST, None, set(existing or ()), set(),
                       fingerprint=dsl.fingerprint, physical_identity=dsl.fingerprint, ledger=ledger)


def test_recording_the_draws_does_not_change_them():
    ledger: list = []
    assert _batch(7) == _batch(7, ledger=ledger)
    assert [row["draw_index"] for row in ledger] == list(range(len(ledger)))
    admitted = [row for row in ledger if row["outcome"] == "admitted"]
    assert len(admitted) == 6 and all(row["candidate_id"] for row in admitted)


def test_a_rejected_draw_names_why():
    ledger: list = []
    _batch(11, ledger=ledger)
    codes = {row["outcome"] for row in ledger}
    assert codes <= {"admitted", "duplicate_law", "duplicate_identity", "invalid:no_terms", "invalid:over_budget",
                     "invalid:duplicate_term", "invalid:no_sparse_phase", "invalid:unbounded_below"}
    assert any(code.startswith("invalid:") for code in codes), codes


def test_a_duplicate_is_recorded_as_one():
    first = _batch(3)
    ledger: list = []
    _batch(3, ledger=ledger, existing={dsl.fingerprint(law) for law in first[:2]})
    assert sum(row["outcome"] == "duplicate_law" for row in ledger) >= 2


