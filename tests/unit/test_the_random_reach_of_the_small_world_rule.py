from __future__ import annotations

from graph_scale_dynamics.research import small_world_reach as W


def test_the_random_start_reads_the_random_reach_the_small_world_rule_assumes():
    random = W.random_rows(sizes=(1024,), degrees=(3.0, 12.0), seeds=(0,))
    assert len(random) == 2 and all(abs(row["off"]) <= W.WITHIN for row in random)
    found = W.judge(random, [{"start": "square", "n": 1024, "reach": 16.0, "random_reach": 5.13, "ratio": 3.12}])
    assert found["random_within"] and found["random_inside_the_band"] and found["lattices_inside_the_band"] == []


def test_a_lattice_inside_the_band_is_named():
    found = W.judge([], [{"start": "tesseract", "n": 4096, "reach": 8.0, "random_reach": 4.3, "ratio": 1.86}])
    assert found["lattices_inside_the_band"] == [["tesseract", 4096, 1.86]]
    assert not found["random_within"] and not found["random_inside_the_band"], "no random graph read is no pass"
