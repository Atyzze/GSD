from __future__ import annotations

from pathlib import Path

import numpy as np

from graph_scale_dynamics.measurements import known_answers as K
from graph_scale_dynamics.measurements.box_covering import box_covering_profile, fit_box_dimension
from graph_scale_dynamics.measurements.estimators import build_adjacency, largest_component, volume_growth
from graph_scale_dynamics.research import lattice_starts_known_answers as L

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "graph_scale_dynamics" / "resources" / "readings"
SMALL = {"contract": "made for a test", "sizes": [64, 256], "seeds": [0, 1], "probes": ["d_s", "d_B"],
         "bands": {"2": [1.5, 2.5]}, "d_w_band": [1.5, 2.5], "d_s_within_at_the_top": 0.15,
         "lattices": [{"name": "square", "family": K.SQUARE_TORUS, "dimension": 2, "neighbours": 4}],
         "predicted_to_refuse": [{"lattice": "square", "n": 64, "probe": "d_B"}]}


def _row(n: int, seed: int, d_s, d_b) -> dict:
    def block(value):
        return {"value": value, "refusal": None if value is not None else "WINDOW_TOO_SHORT"}
    return {"lattice": "square", "family": K.SQUARE_TORUS, "n": n, "seed": seed, "built": True,
            "probes": {"d_s": block(d_s), "d_B": block(d_b)}}


def _rows(**changed) -> list[dict]:
    given = {(64, "d_s"): 2.0, (64, "d_B"): None, (256, "d_s"): 2.0, (256, "d_B"): 2.0}
    given.update({(int(key.split("_", 1)[0][1:]), key.split("_", 1)[1]): value for key, value in changed.items()})
    return [_row(n, seed, given[(n, "d_s")], given[(n, "d_B")]) for n in (64, 256) for seed in (0, 1)]


def test_a_reading_passes_when_every_probe_reads_or_refuses_as_predicted_and_in_its_band():
    judged = L.judge(SMALL, _rows())
    assert judged["passes"] and judged["read"] == 3 and judged["of"] == 4 and not judged["misses"]
    assert "It passes" in L.render(judged) and "refused (WINDOW_TOO_SHORT)" in L.render(judged)


def test_each_way_a_cell_can_miss_is_named():
    def misses(**changed):
        return [(miss["n"], miss["probe"], miss["miss"]) for miss in L.judge(SMALL, _rows(**changed))["misses"]]
    assert misses(n256_d_B=None) == [(256, "d_B", "refused where a reading was predicted")]
    assert misses(n64_d_B=2.0) == [(64, "d_B", "read where a refusal was predicted")]
    assert misses(n64_d_s=2.7) == [(64, "d_s", "outside its band")]
    assert misses(n256_d_s=2.2) == [(256, "d_s", "d_s further from the dimension at the largest size than allowed")]
    assert not L.judge(SMALL, _rows(n256_d_B=None))["passes"]


def test_a_probe_reads_a_cell_only_when_it_reads_every_seed():
    rows = _rows()
    rows[2]["probes"]["d_B"] = {"value": None, "refusal": "NOT_POWER_LAW"}
    cell = next(cell for cell in L.judge(SMALL, rows)["cells"] if cell["n"] == 256 and cell["probe"] == "d_B")
    assert not cell["reads"] and cell["refusals"] == ["NOT_POWER_LAW"] and cell["median"] is None


def test_a_start_is_read_as_the_fleet_reads_a_chain_from_a_given_start():
    row = L.read_start(K.SQUARE_TORUS, "square", 1024, 0)
    assert row["built"] and row["edges"] == 2048 and sorted(row["probes"]) == ["d_B", "d_V", "d_s", "d_w"]
    assert abs(row["probes"]["d_s"]["value"] - 2.0) < 0.15, "the square start read by d_s at 1,024 nodes"
    assert L.read_start(K.SQUARE_TORUS, "square", 1000, 0) == {
        "lattice": "square", "family": K.SQUARE_TORUS, "n": 1000, "seed": 0, "built": False}


def test_the_fault_this_reading_found_is_mended_by_refusing_where_the_cover_has_no_window():
    n = 1024
    adjacency = build_adjacency(n, K.edges(K.BODY_CENTRED_CUBIC, n))
    component = largest_component(n, adjacency)
    ball = volume_growth(adjacency, component, np.random.default_rng(0))["mean_ball"]
    profile = box_covering_profile(adjacency, component, np.random.default_rng(0), ball)
    assert not profile["valid"] and profile["refusal"] == "WINDOW_TOO_SHORT", (
        "at 1,024 nodes this start read 0.22 on the cover's flat end (build 759's notes, section 3); a ball of radius "
        "4 holds more than an eighth of it, so no four radii are left and the probe says so")
    assert fit_box_dimension(profile)["refusal"] == "WINDOW_TOO_SHORT"
