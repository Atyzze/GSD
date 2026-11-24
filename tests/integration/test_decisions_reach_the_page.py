from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "e".ljust(64, "0")


def _record(repo, campaign_id, decision_id, **fields):
    from graph_scale_dynamics.domain.model import utc_now
    row = {"at_n": None, "next_n": None, "priority": None, "queue_order": None, "jobs_created": 0,
           "rows_changed": 0, "released_hold": False, "jobs_seen": "0:", "engine": "decision-engine-1",
           "facts": {}} | fields
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,priority,"
        "queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, decision_id, LAW, row["at_n"], row["next_n"], row["action"], row["rule"], row["reason"],
         row["priority"], row["queue_order"], row["jobs_created"], row["rows_changed"], row["released_hold"],
         row["jobs_seen"], row["engine"], json.dumps(row["facts"]), utc_now()))


@pytest.fixture
def a_law_the_engine_decided(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "decided"}, search_seed=1)["campaign_id"])
        spec = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
                "dynamics": {"kind": "metropolis", "beta": 1.0}}
        repo.insert_candidate(LAW, campaign_id, spec, "metropolis", 1, "BASE_BLOCK_RUNNING")
        _record(repo, campaign_id, "0000000000000000001-a", next_n=64, action="run_next", rule="start",
                reason="no rung measured yet", jobs_created=3)
        _record(repo, campaign_id, "0000000000000000002-b", at_n=4096, next_n=16384, action="run_next",
                rule="settled", reason="d_s and mean degree both settled at the last step", priority=1,
                jobs_created=3, facts={"d_s_step": 0.01, "d_s_sigma": 0.2})
    return isolated_postgres_schema.dsn, campaign_id


def test_the_repository_reads_a_laws_trail_and_its_latest_decision(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        trail = repo.engine_decisions(campaign_id, LAW)
        latest = repo.latest_engine_decisions(campaign_id)
        grouped = repo.campaign_engine_decisions(campaign_id)
    assert [row["rule"] for row in trail] == ["start", "settled"]
    assert trail[-1]["facts"] == {"d_s_step": 0.01, "d_s_sigma": 0.2}
    assert latest[LAW]["rule"] == "settled" and latest[LAW]["priority"] == 1 and "facts" not in latest[LAW]
    assert [row["rule"] for row in grouped[LAW]] == ["start", "settled"]


def test_the_overview_carries_each_laws_latest_decision(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.overview import build_overview
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        overview = build_overview(repo, campaign_id)
    entry = next(row for row in overview["active"] if row["candidate_id"] == LAW)
    assert entry["engine_decision"]["rule"] == "settled"
    assert entry["engine_decision"]["next_n"] == 16384


def test_the_proposers_admission_read_sees_each_live_laws_latest_decision(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.proposer.main import admission
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        live = repo.live_laws_latest_decision(campaign_id)
        assert [(row["candidate_id"], row["action"], row["next_n"]) for row in live] == [(LAW, "run_next", 16384)]
        window = admission(live, pool_min=32, max_active=48, top_base_n=4096)
        assert window["open"] and window["counts"]["above_base_block"] == 1
        repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE campaign_id=? AND candidate_id=?",
                          (campaign_id, LAW))
        assert repo.live_laws_latest_decision(campaign_id) == []


def test_the_ladder_counts_a_law_the_engine_stopped_at_its_rung(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        repo.insert_job(job_id="job-over-budget", campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n16384_x1", n=16384, seed=0, replicate=0, spec={}, priority=10, sealed=False,
                        requested_by="decider")
        _record(repo, campaign_id, "0000000000000000003-c", at_n=16384, action="stop", rule="over_budget",
                reason="its first chunk at N=65,536 is predicted past the size's budget")
        rows = {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id)}
    assert rows[16384]["stopped"] == 1 and rows[16384]["stopped_by_rule"] == {"over_budget": 1}
    assert all(r["stopped"] == 0 for n, r in rows.items() if n != 16384)


def test_the_ladder_counts_each_seed_that_ended_at_its_budget_once_at_its_rung(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        repo.insert_job(job_id="job-at-its-budget", campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n4096_x1", n=4096, seed=0, replicate=0, spec={}, priority=10, sealed=False,
                        requested_by="decider")
        ended = {"budget_ended": {"seeds": [0, 2], "of": 3, "at_n": 4096}}
        _record(repo, campaign_id, "0000000000000000003-c", at_n=4096, next_n=16384, action="run_next",
                rule="dimension_shows", reason="read on past its budget", facts=ended)
        _record(repo, campaign_id, "0000000000000000004-d", at_n=4096, next_n=16384, action="run_next",
                rule="dimension_shows", reason="the same seeds, read again", facts=ended)
        rows = {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id)}
    assert rows[4096]["budget_ended_seeds"] == 2, "two seeds counted once, however many decisions name them"
    assert rows[4096]["stopped_by_rule"] == {} and rows[4096]["stopped"] == 0, "a seed at its budget stops no law"


def test_an_interrupted_run_is_counted_apart_and_kept_out_of_timing(a_law_the_engine_decided):
    from graph_scale_dynamics.db.repo import ATTEMPT_CLASS_FLEET_PAUSED, Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    dsn, campaign_id = a_law_the_engine_decided
    with Repo(dsn) as repo:
        repo.insert_job(job_id="job-interrupted", campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n4096_x16", n=4096, seed=0, replicate=0, spec={"execution": {"sweeps_multiplier": 16}},
                        priority=10, sealed=False, requested_by="decider")
        for attempt, error_class, wall in (("att-paused", ATTEMPT_CLASS_FLEET_PAUSED, 3345.0), ("att-done", None, 20.0)):
            repo.record_attempt(attempt, "job-interrupted", 1, "executor-test")
            repo.close_attempt(attempt, -9 if error_class else 0, 1000, wall,
                               "preempted: fleet stopped" if error_class else None, {}, error_class=error_class)
        samples = repo.rung_attempt_durations(campaign_id)
        rows = {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id, samples)}
        compute = {int(r["n"]): r for r in repo.candidate_rung_compute(campaign_id, LAW)}
        history_before = repo.fleet_ladder_hourly(campaign_id)
        from graph_scale_dynamics.observability.ladder_history import LadderRecorder
        assert LadderRecorder().maybe_record(repo, campaign_id, now_monotonic=0.0)
        history = repo.fleet_ladder_hourly(campaign_id)
        events = repo.campaign_events(campaign_id)
    assert [s["wall_seconds"] for rows_ in samples.values() for s in rows_] == [20.0]
    assert (rows[4096]["interrupted"], rows[4096]["interrupted_seconds"], rows[4096]["attempts"]) == (1, 3345.0, 1)
    assert (compute[4096]["interrupted_attempts"], compute[4096]["interrupted_seconds"]) == (1, 3345.0)
    assert compute[4096]["failed_seconds"] == 0.0
    assert history_before["snapshots"] == 0 and history["snapshots"] == 1
    assert history["hours"][0]["rows"][0]["n"] and "candidates_by_state" in history["hours"][0]
    assert all(event["event_type"] != "fleet_ladder_snapshot" for event in events)
