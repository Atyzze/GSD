from __future__ import annotations

from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.services.api.fleet_snapshots import _capacity_diagnosis

BASE = dict(paused=False, resources={"cpu_percent": 4.0}, active_slots=0, scheduler_slots=40,
            runnable_simulations=0, runnable_analyses=0, blocked_simulations=0,
            deferred_analyses=0, memory_deferred_analyses=0, stranded_nonterminal=0,
            nonterminal_observed=5, governor={})


def diagnose(supply=None):
    return _capacity_diagnosis(**BASE, supply=supply)


def test_without_an_explanation_it_stays_a_warning():
    state, severity, explanation = diagnose(None)
    assert state == "WORK_SUPPLY_STARVED" and severity == "warning"
    assert "No campaign explains it" in explanation


def test_a_cause_the_operator_chose_is_a_status_and_not_a_warning():
    state, severity, explanation = diagnose({
        "expected": True,
        "reading": "campaign 1 is paused with 62 job(s) still queued; campaign 2 has proposed "
                   "every law its term set can write (23) and holds 5 at a gate"})
    assert state == "WORK_SUPPLY_STARVED"
    assert severity == "normal", (
        "a paused campaign and a completed survey are both the operator's own "
        "doing; calling them warnings is how a warning stops meaning anything")
    assert "62" in explanation and "23" in explanation


def test_an_unexplained_campaign_keeps_the_warning():
    state, severity, _ = diagnose({
        "expected": False,
        "reading": "campaign 2 is active with nothing queued and nothing held"})
    assert state == "WORK_SUPPLY_STARVED" and severity == "warning"


def test_the_reading_reaches_the_operator_verbatim():
    _state, _severity, explanation = diagnose({"expected": True, "reading": "campaign 4 is paused"})
    assert explanation.endswith("campaign 4 is paused.")


class FakeRepo:
    def __init__(self, campaigns, allocation, held=(), surveyed=()):
        self._campaigns = campaigns
        self._allocation = allocation
        self._held = {str(k): v for k, v in held}
        self._surveyed = {str(c) for c in surveyed}
        self.conn = self

    def all_campaigns(self):
        return self._campaigns

    def worker_allocation(self):
        return self._allocation

    def get_flag(self, key, default=""):
        if key.startswith(control.SURVEYED_PREFIX):
            cid = key[len(control.SURVEYED_PREFIX):]
            return ('{"held": 23}' if cid in self._surveyed else default)
        return default

    def execute(self, sql, params=()):
        return self

    def fetchall(self):
        return [{"campaign_id": cid, "held": n} for cid, n in self._held.items()]


def campaign(cid, *, status="active", target=None):
    return {"campaign_id": cid, "status": status, "workers_target": target,
            "spec": {"mode": "continuous"}}


def test_the_folder_he_was_looking_at_explains_itself():
    from graph_scale_dynamics.services.api.campaign_manager import work_supply
    repo = FakeRepo(
        campaigns=[campaign("1", target=0), campaign("2")],
        allocation=[{"campaign_id": "1", "workers_target": 0, "leased": 0, "queued": 62},
                    {"campaign_id": "2", "workers_target": None, "leased": 0, "queued": 0}],
        held=[("2", 5)], surveyed=["2"])
    supply = work_supply(repo)
    assert supply["expected"] is True, "both causes are their own"
    assert "campaign 1 is paused with 62 job(s) still queued" in supply["reading"]
    assert "campaign 2 has proposed every law" in supply["reading"] and "holds 5 at a gate" in supply["reading"]


def test_an_active_campaign_with_nothing_to_show_is_not_expected():
    from graph_scale_dynamics.services.api.campaign_manager import work_supply
    repo = FakeRepo(campaigns=[campaign("2")],
                    allocation=[{"campaign_id": "2", "workers_target": None,
                                 "leased": 0, "queued": 0}])
    supply = work_supply(repo)
    assert supply["expected"] is False
    assert "the proposer should have filled" in supply["reading"]


def test_a_closed_campaign_is_not_a_cause():
    from graph_scale_dynamics.services.api.campaign_manager import work_supply
    repo = FakeRepo(campaigns=[campaign("1", status="closed")], allocation=[])
    assert work_supply(repo)["causes"] == []
    assert work_supply(repo)["reading"] == "no campaign is active"
