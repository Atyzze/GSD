from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.campaign_limits import (
    DEFAULT_WALL_SECONDS, campaign_max_n, campaign_wall_seconds,
)
from graph_scale_dynamics.scheduling.campaign import validate_campaign

CONFIG_DIR = Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "configs"
CAMPAIGNS = sorted(path for path in CONFIG_DIR.glob("campaign_*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_current_packaged_campaign_passes_budget_consumers():
    assert [path.name for path in CAMPAIGNS] == ["campaign_engine_survey.json"]
    for path in CAMPAIGNS:
        spec = _load(path)
        assert validate_campaign(spec) == [], path.name
        wall = campaign_wall_seconds(spec)
        assert wall is None or wall > 0
        max_n = campaign_max_n(spec)
        assert max_n is None or spec["ladder"][0] <= max_n
        assert not (spec.get("confirmation") or {}).get("enabled")


def test_wall_seconds_null_absent_and_concrete_are_distinct():
    assert campaign_wall_seconds({"budgets": {}}) == DEFAULT_WALL_SECONDS
    assert campaign_wall_seconds({}) == DEFAULT_WALL_SECONDS
    assert campaign_wall_seconds({"budgets": {"wall_seconds": None}}) is None
    assert campaign_wall_seconds({"budgets": {"wall_seconds": 900}}) == 900.0


@pytest.mark.parametrize("bad", [0, -5, "soon", float("inf"), float("nan")])
def test_unusable_wall_values_fall_back_rather_than_crash(bad):
    assert campaign_wall_seconds({"budgets": {"wall_seconds": bad}}) == DEFAULT_WALL_SECONDS


def test_static_max_n_disappears_when_rung_extension_is_enabled():
    bounded = {"ladder": [256], "budgets": {"max_n": 4096}}
    assert campaign_max_n(bounded) == 4096
    extended = bounded | {"rung_extension": {"enabled": True, "factor": 4}}
    assert campaign_max_n(extended) is None
