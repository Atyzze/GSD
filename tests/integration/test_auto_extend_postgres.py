from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SLICE = json.loads((ROOT / "tests" / "fixtures" / "campaign_slice_engine.json").read_text())


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, event, **fields):
        self.lines.append((event, fields))


def _batch_spec() -> dict:
    from graph_scale_dynamics.operations import study_design as SD
    design = SD.design_for(ROOT, "171")
    base = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json").read_text())
    spec = SD.campaign_spec(design, SD.without_terms(design, base, log=lambda *_a: None), design["campaigns"][0], 0)
    assert spec["mode"] == "continuous", "a study's batch is a continuous campaign: it is never completed"
    return spec


def _law(tag: str, n: int) -> tuple[str, dict]:
    return f"{tag}l{n}".ljust(64, "3"), {"terms": [{"op": "edge_count", "params": {}, "coeff": {
        "c0": 0.1 + n / 100 + len(tag), "scale": "one"}}], "dynamics": {"kind": "metropolis", "beta": 1.0}}


def _batch(repo, tag: str, *, spec: dict, laws: int, budget: int | None, state: str = "DONE") -> str:
    from graph_scale_dynamics.operations.study import budget_room, set_law_budget
    campaign_id = str(repo.create_campaign(dict(spec, name=f"batch {tag}"), search_seed=len(tag) + laws)["campaign_id"])
    for n in range(laws):
        law, law_spec = _law(tag, n)
        repo.insert_candidate(law, campaign_id, law_spec, "metropolis", 1, state)
    if budget is not None:
        assert set_law_budget(repo, campaign_id, budget)["ok"]
        budget_room(repo, campaign_id, laws)
    return campaign_id


def _add(repo, campaign_id: str, tag: str, n: int, state: str = "DONE") -> None:
    from graph_scale_dynamics.operations.study import budget_room, laws_held
    law, law_spec = _law(tag, n)
    repo.insert_candidate(law, campaign_id, law_spec, "metropolis", 1, state)
    budget_room(repo, campaign_id, laws_held(repo, campaign_id))


def _pass(repo, log=None):
    from graph_scale_dynamics.services.controller import main as controller
    return controller.finish_pass(repo, log or _Log(), repo.active_campaigns())


def test_off_a_finished_study_is_left_as_it_is(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import auto_extend
    from graph_scale_dynamics.operations.study import budget_state, law_budget
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = _batch_spec()
        first = _batch(repo, "a", spec=spec, laws=3, budget=3)
        second = _batch(repo, "b", spec=spec, laws=3, budget=3)
        assert budget_state(repo, first)["done"] and budget_state(repo, second)["done"]
        assert auto_extend.state(repo) == {"on": False, "laws": 50, "last": None}, "off unless ticked"
        assert _pass(repo) is None
        assert (law_budget(repo, first), law_budget(repo, second)) == (3, 3)


def test_on_a_study_whose_batches_are_all_done_gets_fifty_laws_a_batch(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import auto_extend
    from graph_scale_dynamics.operations.study import budget_room, budget_state, law_budget
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = _batch_spec()
        first = _batch(repo, "a", spec=spec, laws=3, budget=3)
        second = _batch(repo, "b", spec=spec, laws=2, budget=3)
        controls = _batch(repo, "c", spec=spec, laws=2, budget=None, state="BASE_BLOCK_RUNNING")
        assert auto_extend.switch(repo, True)["auto_extend"]["on"] is True
        assert _pass(repo) is None, "one batch is still under its budget: nothing is extended"
        _add(repo, second, "b", 2)
        assert budget_state(repo, second)["done"]
        log = _Log()
        extended = _pass(repo, log)
        assert extended and sorted(extended["campaigns"]) == sorted([first, second]), (
            "every batch with a law budget, and not a campaign without one, however busy it is")
        assert (law_budget(repo, first), law_budget(repo, second), law_budget(repo, controls)) == (53, 53, None)
        assert not budget_state(repo, first)["reached"] and budget_room(repo, first, 3) == 50, (
            "the proposer draws again: the budget is no longer reached")
        assert [str(c["campaign_id"]) for c in repo.active_campaigns()] == sorted([first, second, controls]), (
            "a study's batches stay active, so the fleet runs on")
        assert repo.fleet_has_work()
        assert log.lines == [("study_auto_extended", {"laws": 50, "campaigns": sorted([first, second])})]
        assert auto_extend.state(repo)["last"]["campaigns"][first] == {"from": 3, "to": 53, "held": 3}
        assert _pass(repo) is None, "the next pass waits for the 50 laws to be drawn and decided"


def test_on_a_batch_with_a_law_in_flight_is_not_finished(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import auto_extend
    from graph_scale_dynamics.operations.study import law_budget
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = _batch_spec()
        first = _batch(repo, "a", spec=spec, laws=3, budget=3)
        second = _batch(repo, "b", spec=spec, laws=2, budget=3)
        _add(repo, second, "b", 2, state="BASE_BLOCK_RUNNING")
        auto_extend.switch(repo, True)
        assert _pass(repo) is None and law_budget(repo, first) == 3
        auto_extend.switch(repo, False)
        repo.conn.execute("UPDATE campaign_candidates SET state='DONE' WHERE campaign_id=?", (second,))
        assert _pass(repo) is None, "switched off, nothing is extended"


def test_on_a_bounded_campaign_with_a_budget_is_extended_and_not_completed(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import auto_extend
    from graph_scale_dynamics.operations.study import law_budget
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        bounded = _batch(repo, "a", spec=SLICE, laws=3, budget=3)
        auto_extend.switch(repo, True)
        assert _pass(repo)["campaigns"] == {bounded: {"from": 3, "to": 53, "held": 3}}
        assert str(repo.campaign(bounded)["status"]) == "active" and repo.fleet_has_work()
        assert law_budget(repo, bounded) == 53
    with Repo(isolated_postgres_schema.dsn) as repo:
        auto_extend.switch(repo, False)
        other = _batch(repo, "z", spec=SLICE, laws=1, budget=1)
        _pass(repo)
        assert str(repo.campaign(other)["status"]) == "completed", "off, a bounded campaign completes as before"


def test_the_campaigns_page_switches_it_and_shows_it(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.services.api import campaign_manager
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        _batch(repo, "a", spec=SLICE, laws=1, budget=1)
        body, status = campaign_manager.handle(repo, {"action": "auto_extend", "on": True})
        assert status == 200 and body["auto_extend"]["on"] is True and "50 more laws" in body["reading"]
        topics = [row["topic"] for row in repo.conn.execute("SELECT topic FROM events").fetchall()]
        assert topics.count("study_auto_extend_switched") == 1
        body, status = campaign_manager.handle(repo, {"action": "auto_extend", "on": False})
        assert status == 200 and body["auto_extend"]["on"] is False
