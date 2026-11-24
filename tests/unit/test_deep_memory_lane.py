from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.scheduling.memory import (  # noqa: E402
    SINGLE_JOB_CEILING_FRACTION, effective_hard_fraction,
)


SPEC = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))


def test_the_configured_value_stays_observable_when_the_lane_fires():
    lane = {"resource_limits": {"deep_from_n": 262144,
                                "deep_single_job_fraction_total": 0.55,
                                "hard_single_job_fraction_total": 0.25},
            "rung_extension": {"hard_single_job_fraction_total": 0.25}}
    configured, effective = effective_hard_fraction(lane, 1048576)
    assert configured == 0.25 and effective == SINGLE_JOB_CEILING_FRACTION


def test_the_ceiling_is_the_same_at_every_rung_and_stage_but_the_deepest():
    lane = {"resource_limits": {"deep_from_n": 262144, "deep_single_job_fraction_total": 0.55,
                                "hard_single_job_fraction_total": 0.08}}
    assert SINGLE_JOB_CEILING_FRACTION == 0.25
    assert {effective_hard_fraction(lane, n)[1] for n in (None, 64, 16384, 262144, 1048576, 4194304)} == {0.25}


def test_the_deep_seed_budget_grows_with_the_size():
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(SPEC)
    budgets = [policy.work_budget(n) for n in policy.ladder()]
    assert all(later >= earlier for earlier, later in zip(budgets, budgets[1:], strict=False)), (
        "a larger graph is never given less work than a smaller one")
