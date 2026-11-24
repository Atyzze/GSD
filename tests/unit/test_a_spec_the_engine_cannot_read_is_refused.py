from __future__ import annotations

import copy

from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.scheduling.campaign import validate_campaign


def _spec(**policy) -> dict:
    spec = copy.deepcopy(control.shipped_spec())
    spec.setdefault("engine", {}).setdefault("policy", {}).update(policy)
    return spec


def test_the_shipped_survey_spec_is_valid():
    assert validate_campaign(control.shipped_spec()) == []


def test_a_policy_field_the_engine_does_not_have_is_refused():
    problems = validate_campaign(_spec(time_window=[[64, 60.0]]))
    assert any("engine.policy cannot be read by the engine" in p and "time_window" in p for p in problems), problems


def test_a_budget_unit_seed_count_or_share_out_of_range_is_refused():
    budgets = [list(w) for w in control.shipped_spec()["engine"]["policy"]["work_budgets"]]
    budgets[0][1] = 60.5
    assert any("whole number of units of work" in p for p in validate_campaign(_spec(work_budgets=budgets)))
    unit = [list(w) for w in control.shipped_spec()["engine"]["policy"]["work_unit"]]
    unit[0][1] = -1
    assert any("work_unit weighs each" in p for p in validate_campaign(_spec(work_unit=unit)))
    assert any("learn_in_batches_of" in p for p in validate_campaign(_spec(learn_in_batches_of=0)))
    assert any("seeds must be a whole number" in p for p in validate_campaign(_spec(seeds=0)))
    assert any("audit_fraction must be a share" in p for p in validate_campaign(_spec(audit_fraction=7)))
