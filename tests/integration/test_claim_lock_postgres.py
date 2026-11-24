from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

GIB = 1 << 30
LAW = "law-claim-lock".ljust(64, "0")
OLD = "2026-09-16T00:00:00Z"
SPEC = json.loads((Path(__file__).resolve().parents[2]
                   / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
HISTORY_SCAN = "ORDER BY a.finished_utc DESC"


class _Recording:
    def __init__(self, inner):
        self.inner, self.log = inner, []

    def execute(self, sql, args=()):
        self.log.append(sql)
        return self.inner.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.inner, name)


@pytest.fixture
def fleet(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.scheduling import memory
    monkeypatch.setattr(memory, "system_memory", lambda: memory.MemorySnapshot(total=92 * GIB, available=60 * GIB))
    monkeypatch.setattr(memory, "memory_pressure_snapshot",
                        lambda: {"available": False, "some_avg10": None, "full_avg10": None})
    memory.reset_prediction_caches()
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    holder = Repo(isolated_postgres_schema.dsn)
    campaign_id = str(repo.create_campaign({"name": "claim-lock"}, search_seed=1)["campaign_id"])
    repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    for i in range(6):
        job = f"done-64-{i}"
        repo.insert_job(job_id=job, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n64", n=64, seed=100 + i, replicate=0, spec=SPEC, priority=64,
                        requested_by="test", sealed=False)
        repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job,))
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,"
                          "peak_pss_bytes) VALUES(?,?,?,?,?,?,?,?)", (f"att-{job}", job, 1, "w", OLD, OLD, 0, 90 << 20))
    repo.insert_job(job_id="queued-64", campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                    stage="rung_n64", n=64, seed=1, replicate=0, spec=SPEC, priority=64,
                    requested_by="test", sealed=False)
    yield repo, holder, campaign_id
    memory.reset_prediction_caches()
    holder.close()
    repo.close()


def _job(repo, job_id):
    return dict(repo.conn.execute("SELECT status,attempts,lease_generation,lease_owner,memory_reservation_bytes,"
                                  "error FROM jobs WHERE job_id=?", (job_id,)).fetchone())


def _events(repo, topic):
    return [json.loads(r["payload_json"]) for r in
            repo.conn.execute("SELECT payload_json FROM events WHERE topic=? ORDER BY event_id", (topic,)).fetchall()]


def test_a_claim_that_dies_waiting_for_the_claim_lock_goes_back_to_the_queue(fleet):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    from graph_scale_dynamics.scheduling.memory import MEMORY_CLAIM_LOCK
    from graph_scale_dynamics.services.worker.main import claim_simulation_for_owner
    repo, holder, _ = fleet
    holder.acquire_blocking_lock(MEMORY_CLAIM_LOCK)
    repo.conn.execute("SELECT set_config('lock_timeout', '300ms', false)")
    with pytest.raises(DatabaseOperationalError) as died:
        claim_simulation_for_owner(repo, "executor-7-4242")
    assert died.value.sqlstate == "55P03"
    after = _job(repo, "queued-64")
    assert (after["status"], after["attempts"], after["lease_generation"], after["lease_owner"]) == \
        ("queued", 0, 1, None), after
    [event] = _events(repo, "claim_failed_before_child")
    assert (event["kind"], event["job_id"], event["released"]) == ("simulation", "queued-64", True)
    assert "55P03" in event["error"]

    holder.release_service_lock(MEMORY_CLAIM_LOCK)
    admitted = claim_simulation_for_owner(repo, "executor-7-4242")
    assert admitted is not None and admitted["job_id"] == "queued-64"
    after = _job(repo, "queued-64")
    assert (after["status"], after["attempts"], after["lease_generation"]) == ("leased", 1, 2), after
    assert after["memory_reservation_bytes"] > 0


def test_an_analysis_claim_that_dies_there_goes_back_too(fleet, tmp_path):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.observability.log import Log
    from graph_scale_dynamics.scheduling.memory import MEMORY_CLAIM_LOCK
    from graph_scale_dynamics.services.analyzer.main import process_new
    repo, holder, campaign_id = fleet
    repo.conn.execute("UPDATE jobs SET status='done',result_artifact='art-claim-lock' WHERE job_id='done-64-0'")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("art-claim-lock", 1, "application/json", "done-64-0", "{}", utc_now()))
    repo.conn.execute(
        "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,producer_job,"
        "status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, "art-claim-lock", ANALYSIS_VERSION, LAW, 64, 100, "done-64-0", "queued", OLD, OLD))
    holder.acquire_blocking_lock(MEMORY_CLAIM_LOCK)
    repo.conn.execute("SELECT set_config('lock_timeout', '300ms', false)")
    with pytest.raises(DatabaseOperationalError):
        process_new(repo, None, Log(tmp_path, "executor-8-4343"), "executor-8-4343", max_jobs=1)
    row = repo.conn.execute("SELECT status,attempts,lease_owner,claim_token FROM analysis_queue "
                            "WHERE input_artifact='art-claim-lock'").fetchone()
    assert (row["status"], row["attempts"], row["lease_owner"], row["claim_token"]) == ("queued", 0, None, None)
    [event] = _events(repo, "claim_failed_before_child")
    assert (event["kind"], event["artifact"], event["released"]) == ("analysis", "art-claim-lock", True)
    holder.release_service_lock(MEMORY_CLAIM_LOCK)


def test_the_claim_lock_covers_no_history_scan(fleet):
    from graph_scale_dynamics.scheduling import memory
    repo, _, _ = fleet
    claimed = repo.claim_job("executor-9-5555", ("simulate",))
    assert claimed is not None
    recording = _Recording(repo.conn)
    repo.conn = recording
    try:
        got = memory.locked_admission(repo, kind="simulation", reservation_bytes=100 << 20,
                                      job_id=claimed["job_id"], owner="executor-9-5555",
                                      lease_generation=int(claimed["lease_generation"]))
    finally:
        repo.conn = recording.inner
    assert got["recorded"] is True, got
    log = recording.log
    start = next(i for i, sql in enumerate(log) if "pg_advisory_lock" in sql)
    end = next(i for i, sql in enumerate(log) if "pg_advisory_unlock" in sql)
    held = log[start + 1:end]
    assert held and not [sql for sql in held if HISTORY_SCAN in sql], held
    assert [sql for sql in log[:start] if HISTORY_SCAN in sql], "the history was read before the lock"


def test_a_seed_whose_worker_vanished_is_queued_again_and_says_why(fleet):
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_WORKER_VANISHED
    repo, _, campaign_id = fleet
    for seed, (job_id, attempts) in enumerate((("never-started", 3), ("child-died", 3), ("retried", 1)), 201):
        repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n64", n=64, seed=seed, replicate=0, spec=SPEC,
                        priority=64, requested_by="test", sealed=False)
        repo.conn.execute("UPDATE jobs SET status='leased',lease_owner='executor-1-1',attempts=?,"
                          "lease_generation=?,lease_expires_utc=? WHERE job_id=?", (attempts, attempts, OLD, job_id))
    repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc) VALUES(?,?,?,?,?)",
                      ("att-child-died", "child-died", 3, "executor-1-1", OLD))
    assert repo.reclaim_expired() == 3
    assert {_job(repo, job)["status"] for job in ("never-started", "child-died", "retried")} == {"queued"}
    attempt = repo.conn.execute("SELECT finished_utc,error_class,error FROM attempts WHERE attempt_id='att-child-died'"
                                ).fetchone()
    assert attempt["finished_utc"] and attempt["error_class"] == ATTEMPT_CLASS_WORKER_VANISHED
    assert "the law is not charged for it" in attempt["error"]
    vanished = {event["job_id"]: event for event in _events(repo, "worker_vanished")}
    assert set(vanished) == {"never-started", "child-died", "retried"} and not _events(repo, "job_lost")
    assert vanished["child-died"]["times"] == 1 and vanished["child-died"]["wait_seconds"] == 60.0


def test_a_retried_failure_is_not_a_lapsed_lease(fleet):
    repo, _, campaign_id = fleet
    repo.insert_job(job_id="two-failures", campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                    stage="rung_n64", n=64, seed=301, replicate=0, spec=SPEC, priority=64, requested_by="test",
                    sealed=False)
    repo.conn.execute("UPDATE jobs SET status='leased',lease_owner='executor-1-1',attempts=3,"
                      "lease_generation=3,lease_expires_utc=? WHERE job_id='two-failures'", (OLD,))
    for number in (1, 2):
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc) "
                          "VALUES(?,?,?,?,?,?)", (f"att-fail-{number}", "two-failures", number, "executor-1-1", OLD, OLD))
    repo.reclaim_expired()
    assert _job(repo, "two-failures")["status"] == "queued", "one lapse in three claims: queued again"
