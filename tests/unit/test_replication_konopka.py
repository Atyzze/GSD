from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import replication_konopka as K  # noqa: E402


def test_a_closed_path_uses_no_edge_twice_and_is_counted_both_ways():
    ring = K._graph()
    for i in range(7):
        K._add(ring, i, (i + 1) % 7)
    assert K.closed_trails(ring, 0, 10) == [0] * 7 + [2, 0, 0, 0], "one cycle of seven, in two directions"
    k4 = K._graph()
    for a in range(4):
        for b in range(a + 1, 4):
            K._add(k4, a, b)
    counts = K.closed_trails(k4, 0, 6)
    assert counts[2] == 0, "a path of two uses its edge twice: normal ordering removes it (equation (14))"
    assert counts[3] == 6 and counts[4] == 6, "three triangles and three squares through a vertex of K4, both ways"


def test_the_honeycomb_s_cycles_are_the_paper_s():
    counts = K.closed_trails(K.honeycomb(40, 40), (0, 0), 14)
    assert [counts[L] for L in (6, 8, 10, 12, 14)] == [6, 0, 30, 24, 168]
    weights = {L: K.coupling(7.0, L) * counts[L] for L in (6, 10, 12, 14)}
    assert max(weights, key=weights.get) == 10, "cycles of length 10 contribute the most for |r| near 6 or 7 (p. 12)"
    assert weights[14] > weights[6] and weights[14] > weights[12], "and 14 more than 6 or 12"


def test_the_named_graphs_draw_figure_3():
    line = K.per_vertex("line")
    hept = K.per_vertex("hept")
    hexa = K.per_vertex("hex")
    assert line[4] == 2 and line[6] == 12 and line[8] == 0 and line[10] == 40, "figure 2(b)'s braided line"
    assert hept[7] == 6 and not any(hept[:7]), "three heptagons at every vertex and nothing shorter"
    unit = abs(K.loop_energy(hexa, K.R_FIGURE))
    for name, counts in (("hex", hexa), ("line", line), ("hept", hept)):
        for L, px in K.FIGURE_3[name].items():
            share = abs(K.loop_energy(counts, K.R_FIGURE, L)) / unit
            assert share == pytest.approx(px / K.FIGURE_3["hex"][K.CUTOFF], abs=0.01), (name, L)
    assert K.crossing_cutoff(hexa, line, K.R_FIGURE) == 16
    assert 7.0 < K.crossing_r(hexa, line) < 7.1


def test_the_heptagonal_tiling_is_three_regular_inside():
    adj, root = K.heptagonal(8)
    inner = K._bfs(adj, root, 7)
    assert {len(adj[v]) for v in inner} == {3}


def test_an_exchange_s_energy_change_is_the_whole_graph_s():
    rng = random.Random(4)
    adj = K.random_cubic(40, rng)

    def total(g, r, cutoff):
        plain = {v: list(ns) for v, ns in g.items()}
        return sum(K.loop_energy(K.closed_trails(plain, v, cutoff), r, cutoff) for v in plain)

    checked = 0
    while checked < 4:
        move = K.propose(adj, list(adj), rng)
        if move is None:
            continue
        before = total(adj, -7.1, 10)
        delta = K.exchange_delta(adj, move, -7.1, 10)
        assert set(len(ns) for ns in adj.values()) == {3}, "an exchange keeps every valence (equation (27))"
        assert delta == pytest.approx(total(adj, -7.1, 10) - before, rel=1e-9, abs=1e-6)
        K.undo(adj, move)
        assert total(adj, -7.1, 10) == pytest.approx(before)
        checked += 1


def test_the_two_exchanges_of_figure_1():
    adj = K.honeycomb(12, 12)
    a, b = (6, 6), (6, 7)
    for kind in ("I", "II"):
        moved, (a_, b_, c, d) = K.defect(adj, a, b, kind)
        assert K._same_hexagon(adj, a, b, c, d) == (kind == "II")
        assert {len(ns) for ns in moved.values()} == {3}


def test_a_prediction_is_judged_by_its_rule():
    criterion = {"predictions": [
        {"id": "A", "reading": "x", "rule": {"between": [1, 2]}},
        {"id": "B", "reading": "x", "rule": {"below": "y"}, "expect": "missed"},
        {"id": "C", "reading": "z", "rule": {"at_least": 0}}]}
    verdicts = K.judge({"x": 1.5, "y": 1.0}, criterion)
    assert [v["verdict"] for v in verdicts] == ["held", "missed", "unread"]
    assert [v["as_expected"] for v in verdicts] == [True, True, False]
    assert K.parse_chains("-7.1:512x4,7.3:256") == [(-7.1, 512, 4), (7.3, 256, 1)]
