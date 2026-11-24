from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.research.family_classification import classify_law
from graph_scale_dynamics.research.measured_anchors import (
    MIN_SEEDS_FOR_ANCHOR, SPREAD_FLOOR, anchor_at, anchor_distance, anchors_for_table,
    measured_anchors)

ROOT = Path(__file__).resolve().parents[2]


def _cell(family, n, seed, **values):
    return {"family": family, "n": n, "seed": seed, "status": "ok",
            "channels": {p: ({"valid": True, "value": v} if v is not None
                             else {"valid": False, "value": None, "reason": "x"})
                         for p, v in values.items()}}


def _table():
    cells = {}
    for seed in range(10):
        cells[f"periodic_honeycomb_lattice:128:{seed}"] = _cell(
            "periodic_honeycomb_lattice", 16384, seed,
            d_s=2.01 + 0.02 * seed, d_V=1.976, d_B=1.86 + 0.01 * (seed % 3), d_w=1.96)
        cells[f"periodic_square_lattice:128:{seed}"] = _cell(
            "periodic_square_lattice", 16384, seed,
            d_s=2.02, d_V=1.98, d_B=1.95 + 0.01 * (seed % 4), d_w=2.0)
        cells[f"sierpinski_carpet:5:{seed}"] = _cell(
            "sierpinski_carpet", 32768, seed, d_s=1.75, d_V=1.71, d_B=1.68, d_w=2.1)
        cells[f"sierpinski_carpet:4:{seed}"] = _cell(
            "sierpinski_carpet", 4096, seed, d_s=1.69, d_V=1.45, d_B=1.62, d_w=2.15)
    cells["periodic_ring:64:0"] = _cell("periodic_ring", 64, 0, d_s=1.0, d_V=None, d_B=None, d_w=None)
    return {"cells": cells, "written_utc": "2026-09-09T00:00:00Z"}


def test_anchors_are_measured_means_with_measured_spread():
    anchors = measured_anchors(_table())
    hc = anchors["periodic_honeycomb_lattice"][16384]
    assert hc["d_V"]["mean"] == pytest.approx(1.976)
    assert hc["d_V"]["spread"] == SPREAD_FLOOR, "ten identical seeds hit the floor, not zero"
    assert hc["d_B"]["seeds"] == 10
    assert hc["d_s"]["spread"] > SPREAD_FLOOR


def test_too_few_seeds_yield_no_anchor():
    anchors = measured_anchors(_table())
    ring = anchors["periodic_ring"][64]
    assert ring["d_s"]["mean"] is None
    assert ring["d_s"]["seeds"] == 1 < MIN_SEEDS_FOR_ANCHOR
    assert ring["d_V"]["refused"] == 1


def test_an_anchor_is_taken_at_or_below_the_laws_rung_never_above():
    anchors = measured_anchors(_table())
    assert anchor_at(anchors, "sierpinski_carpet", 1024, "d_s") is None, (
        "the carpet's smallest rung is 4,096; a law at 1,024 cannot borrow it")
    assert anchor_at(anchors, "sierpinski_carpet", 16384, "d_s")["n"] == 4096, (
        "the largest rung not above the law's")
    assert anchor_at(anchors, "sierpinski_carpet", 40000, "d_s")["n"] == 32768


def test_calibrated_distance_is_in_units_of_measured_spread():
    anchor = {"mean": 1.86, "spread": 0.05}
    assert anchor_distance(1.86, anchor) == 0.0
    assert anchor_distance(1.91, anchor) == pytest.approx(1.0)


def test_a_honeycomb_shaped_reading_is_a_honeycomb_against_measurement():
    law = {"d_s": 2.02, "d_V": 1.976, "d_B": 1.865, "d_w": 1.96}
    against_theory = classify_law(law, n=16384, mean_degree=3.0)
    against_measured = classify_law(law, n=16384, mean_degree=3.0,
                                    anchors=measured_anchors(_table()))
    assert against_theory["basis"] == "theory"
    assert against_measured["basis"] == "measured"
    assert against_measured["geometries"][0]["family"] == "periodic_honeycomb_lattice"
    term = against_measured["geometries"][0]["per_probe"]["d_B"]
    assert term["basis"] == "measured"
    assert "distance_to_theory" in term and "distance_to_anchor" in term, (
        "both distances are recorded so the improvement is visible, not asserted")


@pytest.mark.skipif(not (ROOT / "calibration" / "probe_calibration.json").is_file(),
                    reason="needs the host's calibration table")
def test_on_the_hosts_own_table_theory_misnames_a_honeycomb_reading():
    table = json.loads((ROOT / "calibration" / "probe_calibration.json").read_text())
    law = {"d_s": 2.02, "d_V": 1.97, "d_B": 1.86, "d_w": 1.95}
    measured = classify_law(law, n=16384, mean_degree=3.0, anchors=anchors_for_table(table))
    assert measured["geometries"][0]["family"] == "periodic_honeycomb_lattice"


def test_one_ranking_uses_one_basis():
    table = _table()
    for key in [k for k in table["cells"] if k.startswith("sierpinski_carpet:4:")]:
        del table["cells"][key]
    law = {"d_s": 2.02, "d_V": 1.976, "d_B": 1.865, "d_w": 1.96}
    result = classify_law(law, n=16384, mean_degree=3.0, anchors=measured_anchors(table))
    names = [g["family"] for g in result["geometries"]]
    assert "sierpinski_carpet" not in names, "unmeasured at this rung, so not ranked here"
    assert result["geometries"][0]["family"] == "periodic_honeycomb_lattice"
