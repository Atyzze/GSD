from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import steady_chain as SC
from graph_scale_dynamics.decisions.engine import RUN_NEXT, STOP, Decision, Policy
from graph_scale_dynamics.reporting.every_chain_report import VALUE_COLUMNS

REFS = {"fcc": {1024: {"start": {"mean_degree": {"mean": 12.0}}}, 4096: {"start": {"mean_degree": {"mean": 12.0}}}}}


def _row(n, *, k, giant=1.0, reach=5.0, squares=20.0):
    cells = dict(n=n, mean_degree=k, giant_fraction=giant, reach=reach, squares_per_node=squares)
    return [cells.get(name) for name in VALUE_COLUMNS]


def _chain(k=(11.05, 11.05), giant=(1.0, 1.0), reach=(5.0, 8.0), squares=(22.0, 23.0)):
    return [_row(n, k=a, giant=b, reach=c, squares=d) for n, a, b, c, d in zip((1024, 4096), k, giant, reach, squares, strict=True)]


def _block(chains):
    from graph_scale_dynamics.observability import starts_reading
    names = {name: family for name, family in starts_reading.NAMED.items() if name == "fcc"}
    refs = {family: REFS["fcc"] for family in names.values()}
    return SC.block(chains, VALUE_COLUMNS, refs)


def test_a_chain_the_law_moved_and_that_keeps_its_degree_and_grows_its_reach_is_steady():
    found = _block({"fcc": _chain()})
    assert found["steady"] == [["fcc", "moved"]] and found["moved"] == ["fcc"], "an fcc chain moved to degree 11.05 and steady there"


def test_a_lattice_no_edge_of_which_changed_is_steady_but_a_known_answer():
    found = _block({"fcc": _chain(k=(12.0, 12.0), squares=(30.0, 30.0))})
    assert found["steady"] == [["fcc", "frozen"]] and found["moved"] == []


def test_rings_pieces_the_cap_a_reach_that_does_not_grow_and_hubs_are_not_steady():
    for chain in (_chain(k=(2.0, 2.0)), _chain(giant=(0.4, 0.4)), _chain(k=(16.0, 16.0)), _chain(reach=(5.0, 5.0)),
                  _chain(k=(6.0, 8.0))):
        assert _block({"empty": chain})["steady"] == []
    found = _block({"empty": _chain(k=(6.0, 6.0), squares=(1800.0, 4000.0))})
    assert found["over_squares"] == ["empty"] and found["steady"] == []
    assert _block({"empty": [_row(1024, k=6.0)]}) is None, "nothing read at both sizes: no block"


POLICY = Policy(steady_chain_gate=True, audit_fraction=0.0)
BUYS = Decision(law="l", action=RUN_NEXT, rule="complete_rung", reason="read", at_n=4096, next_n=16384, priority=1)


def test_a_law_with_no_steady_chain_moved_by_it_is_parked_at_4096():
    reading = {"steady": _block({"fcc": _chain(k=(12.0, 12.0)), "empty": _chain(k=(2.0, 2.0))})}
    parked = SC.gate("l", BUYS, reading, POLICY)
    assert (parked.action, parked.rule, parked.at_n, parked.next_n) == (STOP, SC.GATE, 4096, None)
    assert "fcc steady, no edge of it changed" in parked.reason and parked.facts["refused"]["next_n"] == 16384
    kept = SC.gate("l", BUYS, {"steady": _block({"fcc": _chain()})}, POLICY)
    assert kept is BUYS


def test_the_gate_acts_at_4096_only_when_the_policy_turns_it_on_and_lets_its_share_through():
    reading = {"steady": _block({"empty": _chain(k=(2.0, 2.0))})}
    assert SC.gate("l", BUYS, reading, replace(POLICY, steady_chain_gate=False)) is BUYS
    lower = replace(BUYS, at_n=1024, next_n=4096)
    assert SC.gate("l", lower, reading, POLICY) is lower
    assert SC.gate("l", BUYS, {}, POLICY) is BUYS, "no block read: nothing to judge"
    through = SC.gate("l", BUYS, reading, replace(POLICY, audit_fraction=1.0))
    assert through.action == RUN_NEXT and SC.GATE in through.facts["salted"]
