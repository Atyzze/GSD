from __future__ import annotations

import pytest

from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.services.api.campaign_manager import ACTIONS


def campaign(campaign_id, *, status="active", mode="continuous", created="2026-01-01T00:00:00Z"):
    return {"campaign_id": campaign_id, "status": status, "created_utc": created,
            "spec": {"mode": mode}}


class FakeRepo:
    def __init__(self, campaigns, flag=""):
        self.campaigns = {str(c["campaign_id"]): c for c in campaigns}
        self.flags = {control.FOCUS_FLAG: flag}
        self.links: dict[str, object] = {}

    def get_flag(self, key, default=""):
        return self.flags.get(key) or default

    def set_flag(self, key, value):
        self.flags[key] = value

    def campaign(self, campaign_id):
        return self.campaigns.get(str(campaign_id))

    def active_campaigns(self):
        return [c for c in self.campaigns.values() if c["status"] == "active"]

    def campaign_link(self, campaign_id):
        return self.links.get(str(campaign_id))


def test_the_stored_pointer_wins_while_it_names_a_live_campaign():
    repo = FakeRepo([campaign("1"), campaign("2", created="2026-02-01T00:00:00Z")], flag="1")
    assert control.reporting_focus(repo) == "1"


def test_an_unset_pointer_resolves_to_the_newest_active_campaign():
    repo = FakeRepo([campaign("1"), campaign("2", created="2026-02-01T00:00:00Z")])
    assert control.reporting_focus(repo) == "2"


def test_a_stale_pointer_resolves_rather_than_stranding_the_folder():
    repo = FakeRepo([campaign("2")], flag="1")
    assert control.reporting_focus(repo) == "2"


def test_a_pointer_at_a_closed_campaign_resolves_to_a_live_one():
    repo = FakeRepo([campaign("1", status="closed"), campaign("2")], flag="1")
    assert control.reporting_focus(repo) == "2"


def test_a_folder_with_nothing_active_has_no_focus_rather_than_a_wrong_one():
    repo = FakeRepo([campaign("1", status="closed")])
    assert control.reporting_focus(repo) is None


def test_a_bounded_campaign_is_not_picked_by_the_fallback():
    repo = FakeRepo([campaign("1", mode="bounded")])
    assert control.reporting_focus(repo) is None


def test_the_focus_can_be_pointed_and_cleared():
    repo = FakeRepo([campaign("1"), campaign("2", created="2026-02-01T00:00:00Z")])
    control.set_reporting_focus(repo, "1")
    assert control.reporting_focus(repo) == "1"
    control.set_reporting_focus(repo, None)
    assert control.reporting_focus(repo) == "2", "clearing it must resolve, not strand"


@pytest.mark.parametrize("kwargs,expected", [
    ({"status": "closed"}, "is closed"),
    ({"mode": "bounded"}, "continuous"),
])
def test_a_campaign_that_cannot_be_the_focus_says_why(kwargs, expected):
    repo = FakeRepo([campaign("1", **kwargs)])
    problem = control.focus_problem(repo, repo.campaign("1"))
    assert problem and expected in problem


def test_a_linked_confirmation_campaign_reports_with_its_parent():
    repo = FakeRepo([campaign("1")])
    repo.links["1"] = {"parent_campaign_id": "0"}
    assert "confirms" in control.focus_problem(repo, repo.campaign("1"))


def test_a_live_continuous_campaign_has_no_problem():
    repo = FakeRepo([campaign("1")])
    assert control.focus_problem(repo, repo.campaign("1")) is None


def test_the_page_cannot_set_a_home_campaign():
    assert "use" not in ACTIONS
    assert "archive" not in ACTIONS
