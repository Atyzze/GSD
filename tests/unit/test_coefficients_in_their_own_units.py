from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
TABLE = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "calibration" / "operator_units.json")
                   .read_text(encoding="utf-8"))
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
NATURAL = dict(SURVEY["search_policy"]["grid"], units="natural", unit_table=TABLE["version"],
               magnitudes={"min": 0.01, "max": 100.0, "spacing": "log"})


def test_the_table_has_every_operator_in_its_own_unit():
    assert TABLE["version"] == "operator-units-1" and set(TABLE["units"]) == set(dsl.OPERATORS)
    assert all(value > 0 for value in TABLE["units"].values())
    assert TABLE["units"]["edge_count"] == 1.0
    reference = TABLE["reference"]
    assert (reference["n"], reference["mean_degree"], reference["anchor_k"]) == (4096, 4.0, 4)
    assert reference["move_mix"] == {"global_add": 0.5, "local_add": 0.25, "delete": 0.25}
    review = {"degree_anchor_abs": 1.5, "degree_anchor": 6.7, "wedge_count": 9, "degree_square_sum": 20,
              "degree_neighbor_gradient": 46, "degree_cube_sum": 187, "degree_fourth_sum": 1860,
              "triangle_count": 0.49, "square_count": 0.13}
    for op, value in review.items():
        assert value / 1.15 < TABLE["units"][op] < value * 1.15, (op, TABLE["units"][op], value)


def test_the_tool_measures_the_table_it_wrote():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import operator_units
    finally:
        sys.path.pop(0)
    short = operator_units.measure(moves=4000)
    assert short["reference"]["n"] == TABLE["reference"]["n"] and short["version"] == TABLE["version"]
    for op, value in TABLE["units"].items():
        if TABLE["share_of_moves_unchanged"][op] < 0.5:
            assert abs(short["units"][op] / value - 1) < 0.2, (op, short["units"][op], value)


def test_a_natural_grid_needs_the_631_sampler_and_names_the_table():
    assert blind.validate_grid(NATURAL) == []
    assert any("unit_table" in p for p in blind.validate_grid(dict(NATURAL, unit_table="operator-units-0")))
    old = dict(NATURAL)
    old.pop("sampler")
    assert any("needs sampler" in p for p in blind.validate_grid(old))
    assert any("must be 'natural'" in p for p in blind.validate_grid(dict(NATURAL, units="si")))


def test_each_drawn_magnitude_is_divided_by_its_operator_s_unit():
    grid = dict(blind.DEFAULT_GRID, **dict(NATURAL, magnitudes=[1.0], signs=[1]))
    rng = random.Random(4)
    for op in dsl.OPERATORS:
        term = blind._draw_term(rng, op, grid)
        assert term["coeff"]["c0"] == pytest.approx(1.0 / TABLE["units"][op], rel=1e-5), op
    plain = dict(grid)
    plain.pop("units")
    assert blind._draw_term(random.Random(4), "degree_fourth_sum", plain)["coeff"]["c0"] == 1.0


def test_a_law_drawn_in_natural_units_carries_its_actual_coefficients():
    rng = random.Random(6)
    for _ in range(200):
        law = blind.blind_law(rng, SURVEY["operator_whitelist"], NATURAL, complexity_budget=7)
        assert dsl.validate(law, complexity_budget=7) == []
        for term in law["terms"]:
            typical = abs(term["coeff"]["c0"]) * TABLE["units"][term["op"]]
            assert 0.01 * 0.999 <= typical <= 100 * 1.001, term


def test_a_coefficient_past_the_dsl_s_bound_is_refused_not_clamped():
    grid = dict(NATURAL, magnitudes=[100.0, 1.0], signs=[1], term_counts=[2])
    ledger: list = []
    rng = random.Random(8)
    law = blind.blind_law(rng, ["degree_fourth_sum", "square_edge_overlap"], grid, complexity_budget=7,
                          ledger=ledger)
    assert all(abs(t["coeff"]["c0"]) <= dsl._COEF_BOUND for t in law["terms"])
    assert "invalid:coefficient_bound" in {code for code, _ in ledger}
    assert all(abs(t["coeff"]["c0"]) > dsl._COEF_BOUND for code, bad in ledger
               if code == "invalid:coefficient_bound" for t in bad["terms"] if t["op"] == "square_edge_overlap")
