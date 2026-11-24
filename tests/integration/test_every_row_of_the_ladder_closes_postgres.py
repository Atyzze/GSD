from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LADDER = (64, 256, 1024, 4096, 16384)
LAWS = {
    "empty-at-256": ("STOPPED", 256, {"action": "stop", "rule": "empty", "at_n": 256}),
    "dense-at-1024": ("STOPPED", 1024, {"action": "stop", "rule": "too_dense", "at_n": 1024}),
    "alike-a": ("PARKED", 4096, {"action": "stop", "rule": "starts_alike", "at_n": 4096}),
    "alike-b": ("PARKED", 4096, {"action": "stop", "rule": "starts_alike", "at_n": 4096}),
    "apart-by-history": ("PARKED", 4096, {"action": "stop", "rule": "starts_apart_by_history", "at_n": 4096}),
    "disconnected-at-4096": ("STOPPED", 4096, {"action": "stop", "rule": "disconnected", "at_n": 4096}),
    "running-at-4096": ("BASE_BLOCK_RUNNING", 4096, {"action": "run_next", "rule": "start", "at_n": None, "next_n": 64}),
    "undecided-at-4096": ("BASE_BLOCK_RUNNING", 4096, None),
    "held-at-4096": ("HELD", 4096, {"action": "hold", "rule": "deep_lane_full", "at_n": 4096, "next_n": 16384}),
    "bought-16384": ("EXTENDING", 16384, {"action": "run_next", "rule": "starts_shape", "at_n": 4096,
                                           "next_n": 16384}),
    "done-at-16384": ("DONE", 16384, {"action": "done", "rule": "ladder_complete", "at_n": 16384}),
    "apart-twice-at-16384": ("PARKED", 16384, {"action": "stop", "rule": "starts_apart_twice", "at_n": 16384}),
}


def _law(name: str) -> str:
    return name.ljust(64, "0")


def _decide(repo, campaign_id, law, index, decision):
    from graph_scale_dynamics.domain.model import utc_now
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,priority,"
        "queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, f"{index:019d}-x", law, decision.get("at_n"), decision.get("next_n"), decision["action"],
         decision["rule"], "a test's decision", None, None, 0, 0, False, "0:", "decision-engine-1", json.dumps({}),
         utc_now()))


@pytest.fixture
def a_ladder_of_twelve_laws(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "a ladder"}, search_seed=1)["campaign_id"])
        for index, (name, (state, top, decision)) in enumerate(LAWS.items(), start=1):
            law = _law(name)
            repo.insert_candidate(law, campaign_id, {"terms": []}, "equilibrium", 1, state)
            for n in LADDER:
                if n > top:
                    break
                for seed in range(3):
                    repo.insert_job(job_id=f"{name}-{n}-{seed}", campaign_id=campaign_id, candidate_id=law,
                                    kind="simulate", stage=f"rung_n{n}", n=n, seed=seed, replicate=0, spec={},
                                    priority=n, requested_by="test", sealed=False)
            if decision is not None:
                _decide(repo, campaign_id, law, index, decision)
    return isolated_postgres_schema.dsn, campaign_id


def _rows(dsn, campaign_id) -> dict:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    with Repo(dsn) as repo:
        return {int(row["n"]): row for row in rung_distribution_for(repo, campaign_id, spec={})}


def test_every_row_closes_on_real_rows_and_the_parks_are_counted_by_what_they_are(a_ladder_of_twelve_laws):
    rows = _rows(*a_ladder_of_twelve_laws)
    assert [rows[n]["laws"] for n in LADDER] == [12, 12, 11, 10, 3]
    for n, following in zip(LADDER, LADDER[1:] + (None,), strict=True):
        row = rows[n]
        assert row["laws"] == row["left"] + row["still_here"] + (rows[following]["laws"] if following else 0), n
    at = rows[4096]
    assert at["left"] == 4 and at["left_by_rule"] == {"starts_alike": 2, "starts_apart_by_history": 1,
                                                     "disconnected": 1}
    assert at["parked_by_rule"] == {"starts_alike": 2, "starts_apart_by_history": 1}
    assert at["still_here"] == 3, "running, not yet decided and held are all still here"
    assert at["stopped"] == 4 and at["stopped_by_rule"] == at["left_by_rule"]
    top = rows[16384]
    assert top["left"] == 2 and top["left_by_rule"] == {"ladder_complete": 1, "starts_apart_twice": 1}
    assert top["stopped"] == 1 and top["stopped_by_rule"] == {"starts_apart_twice": 1}, (
        "a law that ran the ladder to its end left it, and no rule stopped it")
    assert top["parked_by_rule"] == {"starts_apart_twice": 1} and top["still_here"] == 1


def test_a_law_is_counted_where_its_largest_graph_is_whatever_its_last_decision_names(a_ladder_of_twelve_laws):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = a_ladder_of_twelve_laws
    with Repo(dsn) as repo:
        _decide(repo, campaign_id, _law("bought-16384"), 99, {"action": "stop", "rule": "too_dense", "at_n": 4096})
        _decide(repo, campaign_id, _law("undecided-at-4096"), 100, {"action": "stop", "rule": "failed", "at_n": None})
    rows = _rows(dsn, campaign_id)
    for n, following in zip(LADDER, LADDER[1:] + (None,), strict=True):
        row = rows[n]
        assert row["laws"] == row["left"] + row["still_here"] + (rows[following]["laws"] if following else 0), (
            n, "787: every row closes by construction, a decision at another N or at none counted where its graphs end")
    assert rows[16384]["stopped_by_rule"]["too_dense"] == 1 and rows[4096]["stopped_by_rule"]["failed"] == 1


def test_the_batches_ladders_add_their_counts_by_rule(a_ladder_of_twelve_laws):
    from graph_scale_dynamics.services.api.study_scope import merge_ladder
    rows = list(_rows(*a_ladder_of_twelve_laws).values())
    merged = {int(row["n"]): row for row in merge_ladder([rows, rows])}
    assert merged[4096]["left"] == 8 and merged[4096]["still_here"] == 6
    assert merged[4096]["parked_by_rule"] == {"starts_alike": 4, "starts_apart_by_history": 2}
    assert merged[16384]["left_by_rule"] == {"ladder_complete": 2, "starts_apart_twice": 2}


def test_a_law_that_ran_the_ladder_is_done_and_not_stopped(a_ladder_of_twelve_laws):
    rows = _rows(*a_ladder_of_twelve_laws)
    last = rows[16384]
    assert last["done"] == 1 and last["done_by_rule"] == {"ladder_complete": 1}
    assert last["stopped"] == 1 and last["stopped_by_rule"] == {"starts_apart_twice": 1}
    assert last["left"] == last["stopped"] + last["done"]
    for n in LADDER:
        row = rows[n]
        assert row["left"] == row["stopped"] + row["done"], n
        assert row["work_budget"] and row["work_budget"] > 0 and row["budget_seconds"] > 0, n
        assert row["fallback_reservation_bytes"] and row["fallback_reservation_bytes"] > 0, n


def test_a_finished_fleet_keeps_its_evolution_times(a_ladder_of_twelve_laws):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.overview import build_fast_overview
    dsn, campaign_id = a_ladder_of_twelve_laws
    with Repo(dsn) as repo:
        for name in LAWS:
            for seed in range(3):
                job = f"{name}-64-{seed}"
                repo.record_attempt(f"{job}-a", job, 1, "worker-test")
                repo.close_attempt(f"{job}-a", 0, 50 * 1024 ** 2, 2.0 + seed, None)
        repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=?", (campaign_id,))
        repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE campaign_id=?", (campaign_id,))
        payload = build_fast_overview(repo, campaign_id)
    row = {int(r["n"]): r for r in payload["rung_distribution"]}[64]
    assert not payload["active"], "the test's fleet has no law left alive"
    assert row["attempts"] == 3 * len(LAWS)
    assert row["median_seconds"] == 3.0
    assert row["simulation_seconds_total"] == round(3 * len(LAWS) * 3.0, 1)
    assert row["rung_seconds_total"] >= row["simulation_seconds_total"]
