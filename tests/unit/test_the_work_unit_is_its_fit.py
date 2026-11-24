from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.scaleflow.one_shot import WORK_PARTS
from graph_scale_dynamics.scheduling.limits import work_unit
from tests.support.engines import require_rust_engine

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json"


def _tool():
    spec = importlib.util.spec_from_file_location("work_unit_fit_under_test", ROOT / "tools" / "work_unit_fit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_unit_and_the_policy_s_are_the_committed_fit_s():
    tool = _tool()
    reading = json.loads(tool.READING.read_text(encoding="utf-8"))
    weights, a_unit = reading["fit"]["weights"], reading["fit"]["seconds_a_unit"]
    assert tuple(tool.PARTS) == tuple(WORK_PARTS)
    assert dict(Policy().work_unit) == weights and Policy().seconds_a_unit == a_unit
    shipped = work_unit(json.loads(SHIPPED.read_text(encoding="utf-8")))
    assert shipped["weights"] == weights and shipped["seconds_a_unit"] == a_unit


def test_the_fit_of_the_committed_rows_gives_the_committed_unit():
    tool = _tool()
    reading = json.loads(tool.READING.read_text(encoding="utf-8"))
    again = tool.fit(reading["rows"])
    assert again["weights"] == reading["fit"]["weights"]
    assert again["seconds_a_unit"] == reading["fit"]["seconds_a_unit"]
    assert again["seeds"] == len(reading["rows"]) == 288 and again["laws"] == 48
    for size in again["sizes"].values():
        assert size["spread_95_over_5"] < 2.5 < 30 < size["per_move_spread_95_over_5"], (
            "the weighted unit holds a seed's seconds within 2.5x from the 5th to the 95th percentile, where moves "
            "alone spread them past 30x")


def test_a_sampled_seed_s_parts_are_the_parts_its_work_record_counts(tmp_path):
    require_rust_engine()
    tool = _tool()
    spec = tool.campaign_spec()
    law = tool.draw(spec, 1)[0]
    row = tool.run_seed(spec, law, 64, 0)
    weights = dict(Policy().work_unit)
    assert set(row["parts"]) == set(WORK_PARTS) and row["parts"]["moves"] > 0
    assert row["work"]["units"] == tool.units_of(row["parts"], weights)
    assert row["work"]["budget"] == tool.SAMPLE_BUDGET
    again = tool.run_seed(spec, law, 64, 0)
    assert again["parts"] == row["parts"], "the same seed counts the same work whatever its seconds"
