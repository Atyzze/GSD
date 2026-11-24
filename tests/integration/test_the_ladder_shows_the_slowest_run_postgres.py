from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "slow".ljust(64, "0")
MIB = 1 << 20


def _job(repo, campaign_id: str, job_id: str, n: int, seed: int) -> None:
    repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                    stage=f"rung_n{n}", n=n, seed=seed, replicate=0, spec={}, priority=10, sealed=False,
                    requested_by="test")


def _ran(repo, job_id: str, number: int, wall: float, peak: int, error_class: str | None = None) -> None:
    attempt = f"{job_id}-{number}"
    repo.record_attempt(attempt, job_id, number, "worker-test")
    repo.close_attempt(attempt, -9 if error_class else 0, peak, wall,
                       "preempted: the campaign paused" if error_class else None, {}, error_class=error_class)


def _measured(repo, campaign_id: str, job_id: str, seed: int, n: int, terminal: dict) -> None:
    artifact = f"art-{job_id}".ljust(64, "0")
    now = "2026-11-16T00:00:00Z"
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                      "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job_id, "{}", now))
    repo.conn.execute("UPDATE jobs SET status='done',result_artifact=? WHERE job_id=?", (artifact, job_id))
    repo.conn.execute(
        "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
        "metrics_json,curves_artifact,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, f"an-{job_id}", LAW, n, seed, "analysis-5.3.0", artifact,
         json.dumps({"health": {"rung_terminal": terminal}}), None, now))


@pytest.fixture
def a_slow_law(isolated_postgres_schema, monkeypatch, tmp_path):
    from graph_scale_dynamics.artifact_store import resume_state as R
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_CAMPAIGN_PAUSED
    from graph_scale_dynamics.observability import live_panel as L
    monkeypatch.setattr(L, "RESUME_ROOT", tmp_path)
    monkeypatch.setattr(L, "_resume_root", lambda root: Path(root) / "volatile")
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "a slow law"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "EXTENDING")
        for seed, (wall, peak) in enumerate(((2.0, 30 * MIB), (3.0, 40 * MIB), (4.0, 50 * MIB), (5.0, 60 * MIB),
                                             (600.0, 900 * MIB))):
            _job(repo, campaign_id, f"fast-{seed}", 4096, seed)
            _ran(repo, f"fast-{seed}", 1, wall, peak)
        _job(repo, campaign_id, "paused-then-done", 4096, 5)
        _ran(repo, "paused-then-done", 1, 3000.0, 1200 * MIB, ATTEMPT_CLASS_CAMPAIGN_PAUSED)
        _ran(repo, "paused-then-done", 2, 20.0, 1100 * MIB)
        _measured(repo, campaign_id, "paused-then-done", 5, 4096,
                  {"wall_seconds": 3020.0, "resumed": {"attempts_before": 1, "seconds_before": 3000.0}})
        _job(repo, campaign_id, "running", 16384, 0)
        repo.record_attempt("running-1", "running", 1, "worker-test")
        started = (datetime.now(timezone.utc) - timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        saved = (datetime.now(timezone.utc) - timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo.conn.execute("UPDATE attempts SET started_utc=? WHERE attempt_id='running-1'", (started,))
        repo.conn.execute("UPDATE jobs SET status='leased' WHERE job_id='running'")
        path = R.resume_path(tmp_path / "volatile", "running")
        path.parent.mkdir(parents=True, exist_ok=True)
        R.resume_note_path(path).write_text(json.dumps({"seconds_spent": 5000.0, "chunks": 3,
                                                        "in_chunk": True, "saved_utc": saved}))
        _job(repo, campaign_id, "paused", 65536, 0)
        _ran(repo, "paused", 1, 7400.0, 2000 * MIB, ATTEMPT_CLASS_CAMPAIGN_PAUSED)
        _job(repo, campaign_id, "paused-unsaved", 65536, 1)
        _ran(repo, "paused-unsaved", 1, 9000.0, 2000 * MIB, ATTEMPT_CLASS_CAMPAIGN_PAUSED)
        _job(repo, campaign_id, "done-at-65536", 65536, 2)
        _ran(repo, "done-at-65536", 1, 700.0, 1800 * MIB)
        spilled = R.resume_path(tmp_path, "paused")
        spilled.parent.mkdir(parents=True, exist_ok=True)
        R.resume_note_path(spilled).write_text(json.dumps({"seconds_spent": 7480.0, "chunks": 9,
                                                           "in_chunk": True, "saved_utc": saved}))
    return isolated_postgres_schema.dsn, campaign_id


def _ladder(dsn: str, campaign_id: str) -> dict:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    with Repo(dsn) as repo:
        return {int(r["n"]): r for r in rung_distribution_for(repo, campaign_id,
                                                              repo.rung_attempt_durations(campaign_id))}


def test_time_per_run_is_the_fastest_the_median_the_slowest_5_percent_and_the_slowest(a_slow_law):
    rung = _ladder(*a_slow_law)[4096]
    assert (rung["min_seconds"], rung["median_seconds"], rung["p95_seconds"], rung["max_seconds"]) == (
        2.0, 4.0, 3020.0, 3020.0)
    assert rung["max_unfinished"] is False


def test_a_seed_paused_and_resumed_counts_both_stretches_and_etime_each_once(a_slow_law):
    rung = _ladder(*a_slow_law)[4096]
    assert rung["max_seconds"] == 3020.0, "the run's own time, not its last 20 seconds"
    assert rung["attempts"] == 6
    assert rung["simulation_seconds_total"] == 634.0, "etime adds the attempts that ran to an end, as before"
    assert (rung["interrupted"], rung["interrupted_seconds"]) == (1, 3000.0)


def test_a_seed_still_running_is_the_slowest_at_its_time_so_far_and_says_so(a_slow_law):
    rung = _ladder(*a_slow_law)[16384]
    assert rung["min_seconds"] is None and rung["median_seconds"] is None
    assert 5085.0 <= rung["max_seconds"] <= 5120.0, "90 seconds of this lease and 5,000 saved before it"
    assert rung["max_unfinished"] is True and rung["running"] == 1
    assert rung["running_laws"] == 1, "the ladder counts laws beside seeds: one law with a seed running"


def test_a_seed_stopped_and_queued_again_is_the_slowest_at_the_time_its_runs_took_saved_or_not(a_slow_law):
    rung = _ladder(*a_slow_law)[65536]
    assert (rung["min_seconds"], rung["median_seconds"], rung["max_seconds"]) == (700.0, 700.0, 9000.0), (
        "the seed stopped before it could save ran 9,000 seconds, more than the 7,480 the other one saved: "
        "its time does not vanish from the slowest")
    assert rung["max_unfinished"] is True
    assert rung["running"] == 0 and rung["interrupted"] == 2 and rung["running_laws"] == 0


def test_a_saved_seed_counts_its_save_when_that_is_more_than_its_stopped_runs(a_slow_law):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = a_slow_law
    with Repo(dsn) as repo:
        repo.conn.execute("DELETE FROM attempts WHERE job_id='paused-unsaved'")
        repo.conn.execute("DELETE FROM jobs WHERE job_id='paused-unsaved'")
    rung = _ladder(dsn, campaign_id)[65536]
    assert rung["max_seconds"] == 7480.0, "a paused seed's save, here on the disk root, is its time so far"


@pytest.fixture
def a_killed_seed(isolated_postgres_schema, monkeypatch, tmp_path):
    from graph_scale_dynamics.artifact_store import resume_state as R
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_CAMPAIGN_PAUSED
    from graph_scale_dynamics.observability import live_panel as L
    monkeypatch.setattr(L, "RESUME_ROOT", tmp_path)
    monkeypatch.setattr(L, "_resume_root", lambda root: Path(root) / "volatile")
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "a killed seed"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "EXTENDING")
        _job(repo, campaign_id, "killed-running", 65536, 0)
        _ran(repo, "killed-running", 1, 18720.0, 2000 * MIB, ATTEMPT_CLASS_CAMPAIGN_PAUSED)
        repo.record_attempt("killed-running-2", "killed-running", 2, "worker-test")
        started = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        saved = (datetime.now(timezone.utc) - timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo.conn.execute("UPDATE attempts SET started_utc=? WHERE attempt_id='killed-running-2'", (started,))
        repo.conn.execute("UPDATE jobs SET status='leased' WHERE job_id='killed-running'")
        path = R.resume_path(tmp_path / "volatile", "killed-running")
        path.parent.mkdir(parents=True, exist_ok=True)
        R.resume_note_path(path).write_text(json.dumps({"seconds_spent": 1060.0, "chunks": 1, "in_chunk": False,
                                                        "saved_utc": saved}))
        _job(repo, campaign_id, "killed-done", 16384, 0)
        _ran(repo, "killed-done", 1, 18720.0, 2000 * MIB, ATTEMPT_CLASS_CAMPAIGN_PAUSED)
        _ran(repo, "killed-done", 2, 4000.0, 2000 * MIB)
        _measured(repo, campaign_id, "killed-done", 0, 16384,
                  {"wall_seconds": 5060.0, "resumed": {"attempts_before": 1, "seconds_before": 1060.0}})
    return isolated_postgres_schema.dsn, campaign_id


def test_a_seed_killed_inside_a_long_chunk_keeps_the_hours_it_ran_while_it_runs_again(a_killed_seed):
    rung = _ladder(*a_killed_seed)[65536]
    assert 18775.0 <= rung["max_seconds"] <= 18815.0, (
        "study 172's law 3df93c635ccd: 5.2 hours in a chunk, 1,060 seconds of it saved; the page showed the save "
        "and the 60 seconds since, and the hours were nowhere")
    assert rung["max_unfinished"] is True and rung["running"] == 1


def test_a_seed_killed_and_then_finished_took_every_second_its_runs_took(a_killed_seed):
    rung = _ladder(*a_killed_seed)[16384]
    assert (rung["min_seconds"], rung["median_seconds"], rung["max_seconds"]) == (22720.0, 22720.0, 22720.0), (
        "18,720 seconds stopped and 4,000 to the end, not the 5,060 its result knows of")
    assert rung["max_unfinished"] is False
    assert rung["simulation_seconds_total"] == 4000.0 and rung["interrupted_seconds"] == 18720.0, (
        "etime and the interrupted seconds are counted as they were")


@pytest.fixture
def probed_seeds(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "probed seeds"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "EXTENDING")
        times = ((2.0, 0.5, 0.0, 1.0), (4.0, 0.7, 0.0, 3.0), (6.0, 0.9, 0.0, 5.0), (8.0, 1.1, 3.0, 7.0),
                 (10.0, 1.3, 5.0, 9.0))
        for seed, (d_s, d_v, d_b, d_w) in enumerate(times):
            job = f"probed-{seed}"
            _job(repo, campaign_id, job, 4096, seed)
            _ran(repo, job, 1, 5.0, 30 * MIB)
            _measured(repo, campaign_id, job, seed, 4096, {})
            repo.conn.execute(
                "UPDATE measurements SET probe_seconds_d_s=?,probe_seconds_d_v=?,probe_seconds_d_b=?,"
                "probe_seconds_d_w=? WHERE analysis_id=?", (d_s, d_v, d_b, d_w, f"an-{job}"))
        _job(repo, campaign_id, "untimed", 4096, 5)
        _ran(repo, "untimed", 1, 5.0, 30 * MIB)
        _measured(repo, campaign_id, "untimed", 5, 4096, {})
    return isolated_postgres_schema.dsn, campaign_id


def test_a_probes_time_is_also_given_over_the_seeds_it_ran_on_with_how_many_those_were(probed_seeds):
    rung = _ladder(*probed_seeds)[4096]
    assert rung["d_B_median_seconds"] == 0.0, "over every timed seed, as before: it refused at once on three of five"
    assert (rung["d_B_ran"], rung["d_B_timed"], rung["d_B_ran_median_seconds"]) == (2, 5, 4.0)
    assert (rung["d_s_ran"], rung["d_s_timed"], rung["d_s_ran_median_seconds"]) == (5, 5, 6.0)
    assert rung["d_s_median_seconds"] == 6.0 and rung["probe_timed_measurements"] == 5, "the untimed seed is no zero"
    assert (rung["d_V_ran"], rung["d_w_ran"]) == (5, 5) and rung["d_B_seconds_total"] == 8.0


def test_every_batch_shown_adds_the_seeds_a_probe_ran_on():
    from graph_scale_dynamics.services.api.study_scope import merge_ladder
    one = {"n": 4096, "completed": 3, "d_B_ran": 2, "d_B_timed": 5, "d_B_ran_median_seconds": 4.0}
    two = {"n": 4096, "completed": 1, "d_B_ran": 1, "d_B_timed": 7, "d_B_ran_median_seconds": 8.0}
    merged = merge_ladder([[one], [two]])[0]
    assert (merged["d_B_ran"], merged["d_B_timed"]) == (3, 12)
    assert merged["d_B_ran_median_seconds"] == pytest.approx(5.0), "medians weighted by the graphs each batch completed"


def test_memory_is_the_lightest_the_median_the_heaviest_5_percent_and_the_heaviest(a_slow_law):
    rung = _ladder(*a_slow_law)[4096]
    assert (rung["peak_bytes_min"], rung["peak_bytes_max"]) == (30 * MIB, 1100 * MIB)
    assert rung["memory_timed_attempts"] == 6, "a paused attempt's peak is kept out, as its time is"


def test_every_batch_shown_keeps_the_fastest_and_the_slowest_and_whose_run_that_is():
    from graph_scale_dynamics.services.api.study_scope import merge_ladder
    one = {"n": 4096, "completed": 3, "min_seconds": 2.0, "max_seconds": 600.0, "max_unfinished": False,
           "peak_bytes_min": 10, "peak_bytes_max": 50}
    two = {"n": 4096, "completed": 3, "min_seconds": 1.0, "max_seconds": 900.0, "max_unfinished": True,
           "peak_bytes_min": 20, "peak_bytes_max": 40}
    merged = merge_ladder([[one], [two]])[0]
    assert (merged["min_seconds"], merged["max_seconds"], merged["max_unfinished"]) == (1.0, 900.0, True)
    assert (merged["peak_bytes_min"], merged["peak_bytes_max"]) == (10, 50)
    assert merge_ladder([[dict(one, max_seconds=1000.0)], [two]])[0]["max_unfinished"] is False
