from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling import campaign as campaign_module
from graph_scale_dynamics.scheduling.campaign import (
    _whitelist_problems, validate_campaign,
)

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs"
                     / "campaign_engine_survey.json").read_text(encoding="utf-8"))

ONE_TERM = dict(SURVEY, operator_whitelist=["degree_square_sum"])

UNDRAWABLE = dict(SURVEY, operator_whitelist=["triangle_count", "square_count"])


def test_the_campaign_that_drained_the_fleet_starts():
    assert validate_campaign(ONE_TERM, stored=True) == []


def test_a_selection_that_cannot_draw_is_still_refused_at_creation():
    problems = validate_campaign(UNDRAWABLE)
    assert any("sparse phase" in problem for problem in problems), problems


def test_the_same_selection_is_admitted_when_it_is_already_frozen():
    assert validate_campaign(UNDRAWABLE, stored=True) == []


def test_a_stored_spec_does_not_reach_the_selection_checks_at_all(monkeypatch):
    def explode(spec):
        raise AssertionError("a stored spec was re-checked against the term "
                             "selection rules; the whitelist is immutable, so "
                             "this can only ever strand a live campaign")

    monkeypatch.setattr(campaign_module, "selection_problems", explode)
    assert _whitelist_problems(ONE_TERM, stored=True) == []
    assert validate_campaign(SURVEY, stored=True) == []
    with pytest.raises(AssertionError):
        _whitelist_problems(ONE_TERM, stored=False)


@pytest.mark.parametrize("spec", [ONE_TERM, UNDRAWABLE, SURVEY])
def test_structural_problems_are_checked_whenever_the_spec_is_read(spec):
    broken = dict(spec, operator_whitelist=["no_such_operator"])
    assert any("unknown operators" in problem
               for problem in validate_campaign(broken, stored=True))
    assert "operator_whitelist must be a non-empty list" in validate_campaign(
        dict(spec, operator_whitelist=[]), stored=True)
