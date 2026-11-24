from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.operations.campaign_control import shipped_spec


def test_the_first_study_is_four_quadrants_that_differ_only_on_their_two_axes():
    base = shipped_spec()
    quadrants = S.quadrant_specs(base)
    assert [label for label, _ in quadrants] == [
        "zero temperature, mean degree to 16", "zero temperature, mean degree to 32",
        "finite temperature, mean degree to 16", "finite temperature, mean degree to 32"]
    for label, spec in quadrants:
        grid = spec["search_policy"]["grid"]
        assert grid["zero_temperature"] == [label.startswith("zero")]
        cap = 16.0 if label.endswith("16") else 32.0
        assert Policy.from_spec(spec).dense_cap == cap, "the engine's stop"
        assert spec["limits"]["mean_degree_window"]["max"] == cap, "and the sampler's, which stops the chain first"
        assert label in spec["name"] and label in spec["description"]
        rest = {k: v for k, v in spec.items() if k not in ("search_policy", "engine", "limits", "name", "description")}
        assert rest == {k: v for k, v in base.items() if k in rest}, "everything else is the shipped spec"
        assert {k: v for k, v in grid.items() if k != "zero_temperature"} == {
            k: v for k, v in base["search_policy"]["grid"].items() if k != "zero_temperature"}
    with pytest.raises(ValueError, match="no such axis"):
        S.quadrant_specs(base, axes=("zero_temperature", "locality"))


def test_every_quadrant_is_a_valid_engine_campaign_and_says_which_it_is():
    from graph_scale_dynamics.scheduling.campaign import validate_campaign
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    for label, spec in S.quadrant_specs(shipped_spec()):
        frozen = freeze_campaign_spec(spec)
        assert validate_campaign(frozen) == []
        assert S.quadrant_label(frozen) == label, "the Campaigns page shows it under the id"
        assert S.quadrant_of(frozen)["label"] == label
    assert S.quadrant_label(shipped_spec()) is None, "a campaign not made as a quadrant says nothing"


class Conn:
    def __init__(self, held=0, in_flight=False):
        self.held, self.in_flight = held, in_flight

    def execute(self, sql, params=()):
        class Result:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row
        if "COUNT(*)" in sql:
            return Result({"c": self.held})
        return Result({"1": 1} if self.in_flight else None)


class Repo:
    def __init__(self, held=0, pending=False, in_flight=False):
        self.flags, self.events = {}, []
        self.conn = Conn(held, in_flight)
        self.pending = pending

    def get_flag(self, key, default=None):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id, "status": "active"}

    def record_campaign_event(self, campaign_id, kind, detail):
        self.events.append((campaign_id, kind, detail))

    def campaign_pending_work(self, campaign_id):
        return self.pending


def test_a_law_budget_closes_a_campaign_once_and_reopens_when_raised():
    repo = Repo(held=4990)
    assert S.budget_room(repo, "1", 4990) is None, "no budget, no limit"
    assert S.set_law_budget(repo, "1", 5000)["ok"]
    assert S.budget_room(repo, "1", 4990) == 10 and not S.budget_reached(repo, "1")
    assert S.budget_room(repo, "1", 5000) == 0
    reached = S.budget_reached(repo, "1")
    assert reached["budget"] == 5000 and reached["laws_held"] == 5000
    assert S.budget_room(repo, "1", 5000) == 0
    assert [kind for _, kind, _ in repo.events].count("campaign_law_budget_reached") == 1, "written once"
    repo.conn.held = 5000
    raised = S.set_law_budget(repo, "1", 6000)
    assert raised["ok"] and not S.budget_reached(repo, "1"), "raised past what it holds: open again"
    assert "1,000" not in raised["reading"] and "5,000 of 6,000" in raised["reading"]
    assert not S.set_law_budget(repo, "1", 0)["ok"] and not S.set_law_budget(repo, "1", "many")["ok"]
    assert S.set_law_budget(repo, "1", None)["ok"] and S.law_budget(repo, "1") is None


def test_a_campaign_at_its_budget_is_done_only_when_nothing_of_it_is_in_flight():
    busy = Repo(held=5000, in_flight=True)
    S.set_law_budget(busy, "1", 5000)
    S.budget_room(busy, "1", 5000)
    state = S.budget_state(busy, "1")
    assert (state["reached"], state["done"], state["state"]) == (True, False, S.AT_BUDGET)
    busy.conn.in_flight = False
    busy.pending = True
    assert S.budget_state(busy, "1")["state"] == S.AT_BUDGET, "a job still queued or leased"
    busy.pending = False
    assert S.budget_state(busy, "1")["state"] == S.DONE
    assert S.budget_state(Repo(), "2") is None, "no budget: no state of its own"


def test_the_proposer_stops_at_the_budget_before_it_loads_a_single_law():
    from graph_scale_dynamics.services.proposer import main as P
    source = (P.__file__ and open(P.__file__, encoding="utf-8").read())
    body = source[source.index("def top_up("):]
    body = body[:body.index("\ndef ")] if "\ndef " in body else body
    assert body.index("study.budget_reached(repo, campaign_id)") < body.index("repo.candidates(campaign_id)")
    assert "min(pool_min - proposed_count, room)" in body, "the last pool is clamped to the room left"


def test_a_worker_with_nothing_under_any_share_borrows_a_slot_for_any_campaign_with_work(monkeypatch):
    from graph_scale_dynamics.services.worker import main as W

    calls = []

    class Fleet:
        def worker_allocation(self, **_):
            return [{"campaign_id": "1", "workers_target": 8, "leased": 8, "queued": 0},
                    {"campaign_id": "2", "workers_target": 8, "leased": 8, "queued": 40}]

        def leased_count(self, **_):
            return 99

        def claim_job(self, owner, kinds, **kwargs):
            calls.append(kwargs.get("campaigns"))
            return None

    assert W.claim_simulation_for_owner(Fleet(), "exec-1") is None
    assert calls == [None] * 3, calls


def test_the_study_record_says_what_it_created():
    lines = []

    class Created:
        def __init__(self):
            self.count, self.flags, self.events = 0, {}, []
            self.conn = Conn(0)

        def get_flag(self, key, default=None):
            return self.flags.get(key, default)

        def set_flag(self, key, value):
            self.flags[key] = value

        def campaign(self, campaign_id):
            return {"campaign_id": campaign_id}

        def record_campaign_event(self, *args):
            self.events.append(args)

    repo = Created()
    made = []

    def create(_repo, spec, *, reason, search_seed):
        repo.count += 1
        made.append((spec["search_policy"]["grid"]["zero_temperature"], search_seed, reason))
        return {"campaign_id": str(repo.count)}

    import graph_scale_dynamics.operations.campaign_control as control
    original = control.create_campaign
    control.create_campaign = create
    try:
        first = S.start_study(repo, shipped_spec(), search_seed=100, log=lines.append)
    finally:
        control.create_campaign = original
    assert first == "1" and [seed for _, seed, _ in made] == [100, 101, 102, 103]
    assert [flag for flag in repo.flags if flag.startswith(S.LAW_BUDGET_PREFIX)] == [
        f"{S.LAW_BUDGET_PREFIX}{i}" for i in "1234"]
    assert all(json.loads(repo.flags[f"{S.LAW_BUDGET_PREFIX}{i}"]) == S.DEFAULT_LAW_BUDGET for i in "1234")
    assert lines[0].startswith("the let-through: every gate learns from this study's own decisions alone"), (
        "786: the default study is on 784's rule")
    assert "zero temperature, mean degree to 16" in lines[1] and "law budget 10,000" in lines[1]
