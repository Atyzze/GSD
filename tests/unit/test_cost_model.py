from __future__ import annotations

import json
import math

import pytest

from graph_scale_dynamics.research.cost_model import build_cost_model


def _sig(ops):
    return json.dumps([{"op": op, "params": {}} for op in sorted(ops)],
                      separators=(",", ":"))


def _table(rows):
    return {"operators": [
        {"operator_signature": _sig(ops), "attempts": attempts, "candidates": 3,
         "wall_seconds_per_attempted_move_proxy": rate}
        for ops, attempts, rate in rows]}


BASE, COSTS = 1e-06, {"cheap": 0.5, "mid": 2.0, "dear": 8.0}


def _synthetic():
    import itertools
    rows = []
    names = sorted(COSTS)
    for size in (1, 2, 3):
        for combo in itertools.combinations(names, size):
            rate = BASE
            for op in combo:
                rate *= COSTS[op]
            rows.append((combo, 500, rate))
    return rows * 3


def test_the_model_recovers_multipliers_it_was_not_told():
    model = build_cost_model(_table(_synthetic()))
    assert model["available"] is True
    for op, factor in COSTS.items():
        assert model["operator_multipliers"][op] == pytest.approx(factor, rel=0.02), op
    assert model["base_rate_per_attempted_move"] == pytest.approx(BASE, rel=0.02)


def test_a_prediction_is_the_base_rate_times_the_product_of_its_terms():
    model = build_cost_model(_table(_synthetic()))
    predicted = model["base_rate_per_attempted_move"]
    for op in ("cheap", "dear"):
        predicted *= model["operator_multipliers"][op]
    assert predicted == pytest.approx(BASE * COSTS["cheap"] * COSTS["dear"], rel=0.05)


def test_the_holdout_is_scored_and_deterministic():
    model = build_cost_model(_table(_synthetic()))
    assert model["signatures_held_out"] > 0
    assert model["held_out_accuracy"]["n"] == model["signatures_held_out"]
    assert model["held_out_accuracy"]["median_factor_error"] == pytest.approx(1.0, abs=0.1)
    assert build_cost_model(_table(_synthetic())) == model, (
        "the split is on the sorted signature so a bundle is reproducible and "
        "nobody can shop for a seed")


def test_a_thin_table_refuses_rather_than_fitting_noise():
    thin = build_cost_model(_table([(("cheap",), 10, 1e-6), (("dear",), 10, 8e-6)]))
    assert thin["available"] is False
    assert "at least 12" in thin["reason"]
    assert build_cost_model({})["available"] is False
    assert build_cost_model({"operators": []})["available"] is False


def test_unusable_rows_are_dropped_rather_than_coerced():
    rows = _synthetic()
    table = _table(rows)
    table["operators"] += [
        {"operator_signature": "not json", "attempts": 99,
         "wall_seconds_per_attempted_move_proxy": 1e-6},
        {"operator_signature": _sig(("cheap",)), "attempts": 99,
         "wall_seconds_per_attempted_move_proxy": 0.0},
        {"operator_signature": _sig(("cheap",)), "attempts": 0,
         "wall_seconds_per_attempted_move_proxy": 1e-6},
    ]
    model = build_cost_model(table)
    assert model["available"] is True
    assert all(math.isfinite(math.log(v)) for v in model["operator_multipliers"].values())


def test_the_model_states_what_it_is_not_about():
    model = build_cost_model(_table(_synthetic()))
    assert "science" in model["reading"]
    assert "not_a_claim_about" in model
