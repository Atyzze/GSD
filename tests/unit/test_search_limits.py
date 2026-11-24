from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.scheduling.campaign import validate_campaign
from graph_scale_dynamics.scheduling.limits import (
    DEFAULT_LIMITS, describe, limits, mean_degree_window, validate_limits,
)
from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json"


def _spec():
    return json.loads(CONFIG.read_text())


def test_default_campaign_validates_clean():
    assert validate_campaign(freeze_campaign_spec(_spec())) == []


def test_limits_block_is_required():
    spec = _spec()
    spec.pop("limits")
    problems = validate_campaign(freeze_campaign_spec(spec))
    assert any("limits block is required" in p for p in problems)


def test_window_must_be_ordered_and_finite():
    assert validate_limits({"limits": {"mean_degree_window": {"min": 16, "max": 16}, "connectivity_floor": 0.9}})
    assert validate_limits({"limits": {"mean_degree_window": {"min": 0, "max": float("nan")},
                                       "connectivity_floor": 0.9}})
    assert validate_limits({"limits": DEFAULT_LIMITS}) == []


def test_reverse_scan_is_two_numbers():
    spec = _spec()
    spec["limits"]["mean_degree_window"] = {"min": 16.0, "max": 32.0}
    assert validate_campaign(freeze_campaign_spec(spec)) == []
    assert mean_degree_window(spec) == (16.0, 32.0)


def test_description_names_every_knob():
    text = describe(_spec())
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(_spec())
    assert "[0, 16]" in text and "0.9" in text
    assert all(f"N={n} {policy.work_budget(n):,}" in text for n in policy.ladder()) and "no clock" in text


def test_defaults_fill_in_when_a_field_is_missing():
    eff = limits({"limits": {"mean_degree_window": {"max": 8}}})
    assert eff["mean_degree_window"] == {"min": 0.0, "max": 8.0}
    assert eff["connectivity_floor"] == 0.9
