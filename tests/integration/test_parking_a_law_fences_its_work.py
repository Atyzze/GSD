from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law-parked".ljust(64, "0")


def _job(repo, campaign_id, job_id, stage, n, seed, status):
    repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                    stage=stage, n=n, seed=seed, replicate=0, spec={}, priority=n,
                    requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))


def _probe(repo, campaign_id, artifact, producer, n, seed, status, version):
    from graph_scale_dynamics.domain.model import utc_now
    now = utc_now()
    repo.conn.execute(
        "INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING", (artifact, 1, "application/json", producer, "{}", now))
    repo.conn.execute(
        "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
        "producer_job,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, artifact, version, LAW, n, seed, producer, status, now, now))


@pytest.fixture
def parked_law(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION

    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "parked"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "PARKED")
        _job(repo, campaign_id, "deep-queued", "rung_n262144", 262144, 0, "queued")
        _job(repo, campaign_id, "deep-done", "rung_n65536", 65536, 0, "done")
        _job(repo, campaign_id, "base-queued", "rung_n16384", 16384, 2, "queued")
        _probe(repo, campaign_id, "a-deep", "deep-done", 65536, 0, "queued", ANALYSIS_VERSION)
    return isolated_postgres_schema.dsn, campaign_id, ANALYSIS_VERSION


def _status(repo, table, where, value):
    return repo.conn.execute(f"SELECT status FROM {table} WHERE {where}=?", (value,)).fetchone()["status"]


def test_parking_again_fences_every_job_and_probe_of_the_law(parked_law):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id, _version = parked_law
    with Repo(dsn) as repo:
        result = repo.terminalize_candidate(campaign_id, LAW, "PARKED", "parked again after a rung")
        assert _status(repo, "jobs", "job_id", "deep-queued") == "cancelled"
        assert _status(repo, "analysis_queue", "input_artifact", "a-deep") == "cancelled"
        assert _status(repo, "jobs", "job_id", "base-queued") == "cancelled"
        assert result["jobs_cancelled"] == 2


def test_a_rejection_that_moves_a_live_law_still_fences_everything(parked_law):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id, _version = parked_law
    with Repo(dsn) as repo:
        repo.conn.execute("UPDATE campaign_candidates SET state='BASE_BLOCK_RUNNING' "
                          "WHERE campaign_id=? AND candidate_id=?", (campaign_id, LAW))
        repo.terminalize_candidate(campaign_id, LAW, "REJECTED_SCALING", "rejected")
        assert _status(repo, "jobs", "job_id", "deep-queued") == "cancelled"
        assert _status(repo, "analysis_queue", "input_artifact", "a-deep") == "cancelled"


def test_the_fleet_ladder_counts_chains_still_running(parked_law):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    from datetime import datetime, timedelta, timezone
    dsn, campaign_id, _version = parked_law
    started = (datetime.now(timezone.utc) - timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with Repo(dsn) as repo:
        repo.conn.execute("UPDATE jobs SET status='leased' WHERE job_id='deep-queued'")
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc) VALUES(?,?,?,?,?)",
                          ("att-running", "deep-queued", 1, "w1", started))
        rows = {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id)}
    assert rows[262144]["running"] == 1 and rows[262144]["laws"] == 1
    assert 80 <= rows[262144]["running_seconds"] <= 600


def test_the_ladder_memory_columns_leave_interrupted_runs_out(parked_law):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    dsn, campaign_id, _version = parked_law
    gib = 1 << 30
    with Repo(dsn) as repo:
        rows = [(f"real-{i}", 4 * gib, 5 * gib, None) for i in range(2)]
        rows += [(f"cut-{i}", 64 << 20, 5 * gib, INTERRUPTED_ATTEMPT_CLASSES[i % len(INTERRUPTED_ATTEMPT_CLASSES)])
                 for i in range(6)]
        for number, (attempt, peak, reserved, error_class) in enumerate(rows, start=1):
            repo.conn.execute(
                "INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,wall_seconds,"
                "peak_rss_bytes,peak_pss_bytes,memory_reservation_bytes,error_class) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (attempt, "deep-queued", number, "w1", "2026-09-16T00:00:00Z", "2026-09-16T00:10:00Z", 600.0,
                 peak, peak, reserved, error_class))
        rung = {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id)}[262144]
    assert rung["memory_timed_attempts"] == 2, rung["memory_timed_attempts"]
    assert rung["peak_bytes_median"] == 4 * gib and rung["peak_bytes_p05"] == 4 * gib
    assert rung["reserved_over_observed"] == 1.25, rung["reserved_over_observed"]
    assert rung["interrupted"] == 6, "the interrupted runs are still counted, in their own column"


HOME_OVERVIEW_FIELDS = {
    "rung_distribution": ("n", "measured", "laws", "attempts", "stopped", "stopped_by_rule", "graphs", "running",
                          "running_seconds", "queued", "analysing", "queued_analyses",
                          "simulation_seconds_total", "probe_seconds_total", "rung_seconds_total",
                          "compute_share", "min_seconds", "median_seconds", "p95_seconds", "max_seconds",
                          "max_unfinished",
                          "d_s_median_seconds", "d_V_median_seconds", "d_B_median_seconds",
                          "d_w_median_seconds", "d_s_seconds_total", "d_V_seconds_total",
                          "d_B_seconds_total", "d_w_seconds_total", "peak_bytes_min",
                          "peak_bytes_median", "peak_bytes_p95", "peak_bytes_max", "reserved_over_observed"),
    "active": ("candidate_id", "state", "law", "terms", "rungs", "running", "probing", "queued",
               "ladder", "compute_seconds"),
    "active.running": ("n", "seed", "lane", "since_s", "started_utc", "budget_seconds", "budget_units", "eta"),
}


def test_the_home_page_contract_holds_on_the_overview(parked_law):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview
    dsn, campaign_id, _version = parked_law
    with Repo(dsn) as repo:
        repo.conn.execute("UPDATE jobs SET status='leased' WHERE job_id='deep-queued'")
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc) VALUES(?,?,?,?,?)",
                          ("att-contract", "deep-queued", 1, "w1", "2026-09-15T00:00:00Z"))
        overview = build_fast_overview(repo, campaign_id)
    assert "compute_utilization" in overview
    rows = {"rung_distribution": overview.get("rung_distribution") or [],
            "active": overview.get("active") or []}
    rows["active.running"] = [job for row in rows["active"] for job in (row.get("running") or [])]
    for surface, fields in HOME_OVERVIEW_FIELDS.items():
        assert rows[surface], f"no {surface} rows to check the Home contract against"
        for row in rows[surface]:
            missing = [f for f in fields if f not in row]
            assert not missing, f"{surface} rows lost fields the Home page reads: {missing}"
