from __future__ import annotations

from graph_scale_dynamics.domain.model import (
    ATTEMPT_CLASS_CAMPAIGN_PAUSED, INTERRUPTED_ATTEMPT_CLASSES, interrupted_sql)
from graph_scale_dynamics.operations.campaign_control import pause_attempt_class


def test_a_campaign_pause_closes_its_attempts_as_an_interruption():
    assert pause_attempt_class("campaign paused") == ATTEMPT_CLASS_CAMPAIGN_PAUSED == "preempted_campaign_paused"
    assert ATTEMPT_CLASS_CAMPAIGN_PAUSED in INTERRUPTED_ATTEMPT_CLASSES
    assert "'preempted_campaign_paused'" in interrupted_sql("a")
    assert pause_attempt_class("fleet stopped") in INTERRUPTED_ATTEMPT_CLASSES
