from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


class _Log:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _law(name: str) -> str:
    return f"law-parked-{name}".ljust(64, "0")


def _decide(repo, campaign, law, *, rule, n=4096):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{time.time_ns():020d}-{law[-6:]}", law, n, None, "stop", rule, f"{rule} at {n}", None, None,
         0, 1, False, "3:mark", "decision-engine-2", "{}", "2026-10-08T09:00:00Z"))


@pytest.fixture
def world(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "parked laws"}, search_seed=7)["campaign_id"])
    other = str(repo.create_campaign({"name": "another campaign"}, search_seed=8)["campaign_id"])
    yield repo, campaign, other
    repo.close()


def test_the_laws_a_rule_parked_with_nothing_in_flight_are_the_ones_decided_again(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    repo, campaign, other = world
    rows = {"d_s_park": ("PARKED", "no_reading"), "starts_park": ("PARKED", "starts_alike"),
            "verdict_under_a_park": ("PARKED", "no_finite_dimension"), "stopped": ("STOPPED", "disconnected"),
            "working": ("PARKED", "unsettled_twice")}
    laws = {name: _law(name) for name in rows}
    for name, (state, rule) in rows.items():
        repo.insert_candidate(laws[name], campaign, {"terms": []}, "equilibrium", 1, state)
        _decide(repo, campaign, laws[name], rule=rule)
    repo.insert_job(job_id="working-queued", campaign_id=campaign, candidate_id=laws["working"], kind="simulate",
                    stage="rung_n16384", n=16384, seed=0, replicate=0, spec={}, priority=16384, requested_by="test",
                    sealed=False)
    elsewhere = _law("elsewhere")
    repo.insert_candidate(elsewhere, other, {"terms": []}, "equilibrium", 1, "PARKED")
    _decide(repo, other, elsewhere, rule="no_reading")

    store = DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}})
    assert sorted(store.parked_laws(campaign)) == sorted([laws["d_s_park"], laws["starts_park"]])
    assert store.parked_laws(other) == [elsewhere]


def test_a_park_of_a_parked_law_says_it_changed_nothing(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    repo, campaign, _other = world
    parked, running = _law("again"), _law("first")
    repo.insert_candidate(parked, campaign, {"terms": []}, "equilibrium", 1, "PARKED")
    repo.insert_candidate(running, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    store = DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}})
    assert store.set_law_state(campaign, parked, "PARKED", rule="starts_alike", next_n=None) == 0
    assert store.set_law_state(campaign, running, "PARKED", rule="starts_alike", next_n=None) == 1
    state = repo.conn.execute("SELECT state FROM campaign_candidates WHERE candidate_id=?", (running,)).fetchone()
    assert state["state"] == "PARKED"


def test_a_parked_law_decided_again_into_a_verdict_leaves_parked(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    repo, campaign, _other = world
    verdict, done, park = _law("verdict"), _law("done"), _law("park-again")
    for law in (verdict, done, park):
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "PARKED")
    store = DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}})
    assert store.set_law_state(campaign, verdict, "STOPPED", rule="no_finite_dimension", next_n=None) == 1
    assert store.set_law_state(campaign, done, "DONE", rule="ladder_complete", next_n=None) == 1
    assert store.set_law_state(campaign, park, "PARKED", rule="nothing_read", next_n=None) == 0
    states = {row["candidate_id"]: row["state"] for row in repo.conn.execute(
        "SELECT candidate_id,state FROM campaign_candidates WHERE campaign_id=?", (campaign,)).fetchall()}
    assert (states[verdict], states[done], states[park]) == ("STOPPED", "DONE", "PARKED")
    stopped = _law("stopped")
    repo.insert_candidate(stopped, campaign, {"terms": []}, "equilibrium", 1, "STOPPED")
    assert store.set_law_state(campaign, stopped, "DONE", rule="ladder_complete", next_n=None) == 0, (
        "a verdict's stop stays")
    assert repo.terminalize_candidate(campaign, _law("verdict"), "PARKED", "not the engine")["state_changed"] == 0
