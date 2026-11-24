from __future__ import annotations

from dataclasses import replace

from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions.engine import Policy, Rung

TODAY = Policy(dense_cap=32.0)
THREE = replace(TODAY, fact_sizes_in_a_row=3)


def _ladder(*points):
    sizes = (64, 256, 1024, 4096, 16384)
    return [Rung(n=sizes[i], mean_degree=d, connected_fraction=c) for i, (d, c) in enumerate(points)]


def _verdicts(rungs, policy):
    return {gate for gate, verdict in E.FINAL_VERDICTS if verdict(rungs, policy)}


def test_without_the_field_every_gate_decides_as_before():
    assert TODAY.fact_sizes_in_a_row == 0
    assert _verdicts(_ladder((0.0, 0.02), (0.0, 0.004)), TODAY) == {"empty"}
    assert _verdicts(_ladder((22.7, 1.0), (32.01, 1.0)), TODAY) == {"too_dense"}
    assert _verdicts(_ladder((1.6, 0.2), (1.8, 0.15), (1.9, 0.09)), TODAY) == {"disconnected"}


def test_two_sizes_are_not_a_trend():
    assert _verdicts(_ladder((0.0, 0.02), (0.0, 0.004)), THREE) == set()
    assert _verdicts(_ladder((32.03, 1.0), (32.01, 1.0)), THREE) == set()


def test_three_sizes_in_a_row_decide_from_1024():
    empty = _ladder((0.0, 0.02), (0.0, 0.004), (0.0, 0.001))
    assert _verdicts(empty, THREE) == {"empty", "disconnected"}
    assert "3 sizes in a row" in E._empty(empty, THREE) and "N=64, 256 and 1,024" in E._empty(empty, THREE)
    assert _verdicts(_ladder((32.03, 1.0), (32.01, 1.0), (32.0, 1.0)), THREE) == {"too_dense"}


def test_a_size_out_of_the_zone_breaks_the_row():
    bcc = _ladder((22.67, 1.0), (25.6, 1.0), (32.0, 1.0), (8.25, 1.0))
    assert _verdicts(bcc[:3], TODAY) == {"too_dense"}, "169's 2ccc10742c72 on bcc: one size stopped a scoring law"
    assert _verdicts(bcc[:3], THREE) == set()
    assert _verdicts(bcc, THREE) == set()


def test_a_rising_row_is_not_empty_and_a_growing_one_not_disconnected():
    rising = _ladder((0.0, 0.01), (0.01, 0.01), (0.04, 0.02))
    assert "empty" not in _verdicts(rising, THREE)
    falling = _ladder((0.04, 0.01), (0.01, 0.01), (0.0, 0.002))
    assert "empty" in _verdicts(falling, THREE)
    growing = _ladder((1.25, 0.109), (1.59, 0.082), (1.79, 0.083))
    assert "disconnected" not in _verdicts(growing, THREE)
    shrinking = _ladder((1.25, 0.109), (1.59, 0.082), (1.79, 0.07))
    assert "disconnected" in _verdicts(shrinking, THREE)
    once_connected = _ladder((1.6, 0.9), (1.8, 0.15), (1.9, 0.09))
    assert "disconnected" not in _verdicts(once_connected, THREE)


def test_the_rule_is_in_the_fingerprint_only_where_a_design_sets_it():
    assert E.policy_fingerprint(THREE) != E.policy_fingerprint(TODAY)
    assert ("fact_sizes_in_a_row", 0) in E.SET_FIELDS, "an older decision's fingerprint holds (170 replays, same rules)"
