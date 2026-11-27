from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "8addbb0c".ljust(64, "0")
BELOW, HERE = 262144, 1048576
SECONDS = 5861.0


def _utc(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _attempt(repo, job: str, number: int, *, wall: float | None, code: int | None, hours_ago: float) -> None:
    repo.conn.execute(
        "INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,wall_seconds) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (f"a{number}-{job}", job, number, "executor-1-1", _utc(hours_ago),
         None if wall is None else _utc(hours_ago - wall / 3600.0), code, wall))


@pytest.fixture
def pushed(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign = str(repo.create_campaign({"name": "the laws pushed", "ladder": [BELOW, HERE]}, search_seed=1)[
            "campaign_id"])
        repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        for seed in range(16):
            job = f"below-{seed}"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage="extend",
                            n=BELOW, seed=seed, replicate=0, spec={}, priority=1, requested_by="test")
            artifact = f"art-{seed:02d}-{job}".ljust(64, "0")
            repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                              "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job, "{}", _utc(7)))
            repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (artifact, job))
            if seed == 6:
                _attempt(repo, job, 1, wall=4000.0, code=-9, hours_ago=9.0)
                _attempt(repo, job, 2, wall=SECONDS - 4000.0, code=0, hours_ago=7.0)
            else:
                _attempt(repo, job, 1, wall=SECONDS, code=0, hours_ago=8.0)
        repo.conn.execute("INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)", (campaign, LAW, BELOW, ANALYSIS_VERSION, "{}", _utc(6)))
        for seed in range(8):
            job = f"here-{seed}"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage="extend",
                            n=HERE, seed=seed, replicate=0, spec={}, priority=1, requested_by="test")
            if seed < 3:
                repo.conn.execute("UPDATE jobs SET status='leased', lease_owner=?, lease_expires_utc=? WHERE job_id=?",
                                  (f"executor-{seed}-1", "2099-01-01T00:00:00Z", job))
                _attempt(repo, job, 1, wall=None, code=None, hours_ago=3.5)
    return isolated_postgres_schema.dsn, campaign


def test_a_seed_s_rough_time_is_its_law_s_time_below_over_the_seeds_that_ran_there(pushed):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview
    dsn, campaign = pushed
    with Repo(dsn) as repo:
        overview = build_fast_overview(repo, campaign)
    law = next(e for e in overview["active"] if e["candidate_id"] == LAW)
    assert next(r for r in law["rungs"] if r["n"] == BELOW)["seeds"] == 16
    running = [r for r in law["running"] if r["n"] == HERE]
    assert len(running) == 3
    eta = running[0]["eta"]
    assert eta["extrapolated"] and eta["median_seconds"] == pytest.approx(SECONDS * 4, rel=1e-3), (
        "178 at 17:26Z: a seed of 1,048,576 read ~34 h 44 min rough, its law's whole time at 262,144 over 3 seeds "
        "where the N-push ran 16, times 4; one seed's time is the whole over 16")
    assert 0.5 < eta["progress"]["elapsed_seconds"] / eta["median_seconds"] < 0.6, "3.5 h of about 6.5 h, not of 34"


def test_the_ladder_counts_a_size_s_graphs_bought_apart_from_those_grown(pushed):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview
    dsn, campaign = pushed
    with Repo(dsn) as repo:
        rows = {int(r["n"]): r for r in build_fast_overview(repo, campaign)["rung_distribution"]}
    starts = rows[HERE]["chains_per_seed"]
    assert rows[HERE]["graphs"] == 8 and rows[HERE]["completed"] == 0 and rows[HERE]["running_graphs"] == 3 * starts, (
        "the eight seeds bought are counted as graphs and none is grown: in 178, eight starts a seed, the page "
        "showed 64 where it now shows 0 of 64, 24 now")
    assert rows[BELOW]["graphs"] == rows[BELOW]["completed"] == 16
