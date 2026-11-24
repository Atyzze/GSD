from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

GIB = 1 << 30
LAW = "law-memory".ljust(64, "0")
OLD = "2026-09-16T00:00:00Z"


def _leased(repo, campaign_id, job_id, owner, reserved, *, n=1048576, started=None):
    repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                    stage=f"rung_n{n}", n=n, seed=0, replicate=0, spec={}, priority=n,
                    requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status='leased',lease_owner=?,memory_reservation_bytes=?,updated_utc=? "
                      "WHERE job_id=?", (owner, int(reserved), OLD, job_id))
    if started:
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc) VALUES(?,?,?,?,?)",
                          (f"att-{job_id}", job_id, 1, owner, started))


def _heartbeat(repo, service, detail):
    from graph_scale_dynamics.domain.model import utc_now
    repo.conn.execute("INSERT INTO service_heartbeats(service,pid,sampled_utc,detail_json) VALUES(?,?,?,?)",
                      (service, 1, utc_now(), detail if isinstance(detail, str) else json.dumps(detail)))


@pytest.fixture
def fleet(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign_id = str(repo.create_campaign({"name": "memory"}, search_seed=1)["campaign_id"])
    repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    _leased(repo, campaign_id, "deep-measured", "executor-1", 6 * GIB, started=OLD)
    _heartbeat(repo, "executor-1", {"job": "deep-measured", "pss": int(2.5 * GIB), "rss": int(2.8 * GIB),
                                    "pss_now": 2 * GIB})
    _leased(repo, campaign_id, "young", "executor-2", 1 * GIB)
    _leased(repo, campaign_id, "stale-heartbeat", "executor-3", 2 * GIB)
    _heartbeat(repo, "executor-3", {"job": "an-earlier-job", "pss": int(1.5 * GIB)})
    _leased(repo, campaign_id, "odd-detail", "executor-4", 1 * GIB)
    _heartbeat(repo, "executor-4", "not json")
    now = utc_now()
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("art-probe", 1, "application/json", "deep-measured", "{}", now))
    repo.conn.execute(
        "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,producer_job,"
        "status,lease_owner,memory_reservation_bytes,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, "art-probe", ANALYSIS_VERSION, LAW, 1048576, 0, "deep-measured", "leased", "analyzer-1",
         3 * GIB, OLD, OLD))
    _heartbeat(repo, "analyzer-1", {"artifact": "art-probe", "pss": 1 * GIB, "pss_now": int(0.5 * GIB)})
    import time as _time
    soon = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() + 5))
    for job_id, next_attempt in (("deferred", soon), ("claimable", None), ("parked", "2999-01-01T00:00:00Z")):
        repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n4096", n=4096, seed=1, replicate=0, spec={}, priority=4096,
                        requested_by="test", sealed=False)
        repo.conn.execute("UPDATE jobs SET next_attempt_utc=? WHERE job_id=?", (next_attempt, job_id))
    yield repo
    repo.close()


def test_each_child_is_read_with_what_its_supervisor_last_measured(fleet):
    from graph_scale_dynamics.scheduling.memory import lease_memory_observations
    rows = {row["id"]: row for row in lease_memory_observations(fleet.conn)}
    assert set(rows) == {"deep-measured", "young", "stale-heartbeat", "odd-detail", "art-probe"}
    assert rows["deep-measured"]["observed_bytes"] == int(2.5 * GIB) and rows["deep-measured"]["started_utc"] == OLD
    assert rows["deep-measured"]["current_bytes"] == 2 * GIB
    assert rows["young"]["observed_bytes"] is None and rows["stale-heartbeat"]["observed_bytes"] is None
    assert rows["young"]["current_bytes"] is None and rows["odd-detail"]["observed_bytes"] is None
    assert (rows["art-probe"]["kind"], rows["art-probe"]["current_bytes"]) == ("analysis", int(0.5 * GIB))


def test_headroom_and_the_refusal_come_from_the_same_reading(fleet):
    from graph_scale_dynamics.scheduling.memory import (
        MemorySnapshot, admission_headroom, admit_recorded_claim, memory_deferred_simulations)
    from graph_scale_dynamics.scheduling.memory import reset_prediction_caches
    reset_prediction_caches()
    mem = MemorySnapshot(total=92 * GIB, available=30 * GIB)
    got = admission_headroom(fleet.conn, snapshot=mem)
    still = (6 * GIB - 2 * GIB) + 1 * GIB + 2 * GIB + 1 * GIB + (3 * GIB - int(0.5 * GIB))
    assert (got["floor_bytes"], got["unrealised_bytes"]) == (10 * GIB, still)
    assert got["headroom_bytes"] == 30 * GIB - 10 * GIB - still
    assert got["budget_bytes"] == got["reserved_bytes"] + got["headroom_bytes"] == 13 * GIB + got["headroom_bytes"]
    assert memory_deferred_simulations(fleet.conn) == 1

    job = fleet.conn.execute("SELECT lease_generation FROM jobs WHERE job_id='young'").fetchone()

    def claim(reservation):
        return admit_recorded_claim(fleet.conn, kind="simulation", reservation_bytes=int(reservation),
                                    budget_bytes=got["budget_bytes"], job_id="young", owner="executor-2",
                                    lease_generation=int(job["lease_generation"]), snapshot=mem)

    over = claim(got["headroom_bytes"] + GIB)
    assert (over["refusal"], over["permanent"]) == ("transient_memory_floor", False), over
    never = claim(90 * GIB)
    assert (never["refusal"], never["permanent"]) == ("permanent_over_budget", True), never
    fits = claim(got["headroom_bytes"] - GIB)
    assert fits["recorded"] is True, fits


def test_the_shed_set_is_the_cheapest_way_back_to_the_floor(fleet):
    from graph_scale_dynamics.scheduling.memory import PREEMPT_MEMORY_FLOOR, MemorySnapshot, memory_shed_reason
    mem = MemorySnapshot(total=92 * GIB, available=7 * GIB)
    shed = {job: memory_shed_reason(fleet.conn, {"job_id": job}, snapshot=mem)
            for job in ("deep-measured", "young", "stale-heartbeat", "odd-detail")}
    assert memory_shed_reason(fleet.conn, {"job_id": "art-probe"}, snapshot=mem, kind="analysis") == \
        PREEMPT_MEMORY_FLOOR
    assert shed == {"odd-detail": PREEMPT_MEMORY_FLOOR, "stale-heartbeat": PREEMPT_MEMORY_FLOOR,
                    "young": None, "deep-measured": None}, shed
    assert memory_shed_reason(fleet.conn, {"job_id": "young"}, snapshot=MemorySnapshot(92 * GIB, 9 * GIB)) is None


def test_a_rung_with_finished_runs_is_expected_to_reach_their_peak(fleet):
    from graph_scale_dynamics.scheduling.memory import (
        EXPECTED_PEAK_SLACK, MemorySnapshot, admission_headroom, lease_memory_observations, reset_prediction_caches)
    campaign_id = fleet.conn.execute("SELECT campaign_id FROM jobs WHERE job_id='young'").fetchone()["campaign_id"]
    mib = 1 << 20
    for i in range(6):
        job = f"done-4096-{i}"
        fleet.insert_job(job_id=job, campaign_id=campaign_id, candidate_id=LAW, kind="simulate", stage="rung_n4096",
                         n=4096, seed=i, replicate=0, spec={}, priority=4096, requested_by="test", sealed=False)
        fleet.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job,))
        fleet.conn.execute(
            "INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,peak_pss_bytes) "
            "VALUES(?,?,?,?,?,?,?,?)", (f"att-{job}", job, 1, "w", OLD, OLD, 0, 100 * mib))
    _leased(fleet, campaign_id, "running-4096", "executor-9", 1 * GIB, n=4096, started=OLD)
    _heartbeat(fleet, "executor-9", {"job": "running-4096", "pss": 60 * mib, "pss_now": 50 * mib})
    reset_prediction_caches()
    mem = MemorySnapshot(total=92 * GIB, available=30 * GIB)
    rows = {row["id"]: row for row in lease_memory_observations(fleet.conn)}
    got = admission_headroom(fleet.conn, snapshot=mem, observations=[rows["running-4096"]])
    assert abs(got["unrealised_bytes"] - (int(100 * mib * EXPECTED_PEAK_SLACK) - 50 * mib)) <= 1, got
    reset_prediction_caches()
    import json as _json
    from graph_scale_dynamics.scheduling.memory import predicted_claim_peak_bytes
    spec = _json.loads((Path(__file__).resolve().parents[2]
                        / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    opening = predicted_claim_peak_bytes(fleet.conn, kind="simulation", campaign_id=campaign_id, candidate_id=LAW,
                                         n=4096, spec=spec)
    assert abs(opening - int(100 * mib * EXPECTED_PEAK_SLACK)) <= 1, opening
    reset_prediction_caches()


def test_an_analysis_is_ordered_by_its_attempt_start(fleet):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.scheduling.memory import lease_memory_observations
    campaign_id = fleet.conn.execute("SELECT campaign_id FROM analysis_queue WHERE input_artifact='art-probe'"
                                     ).fetchone()["campaign_id"]
    fleet.conn.execute(
        "INSERT INTO analysis_attempts(analysis_attempt_id,campaign_id,input_artifact,analysis_version,attempt_number,"
        "owner,started_utc) VALUES(?,?,?,?,?,?,?)", ("aa-1", campaign_id, "art-probe", ANALYSIS_VERSION, 1,
                                                  "analyzer-1", "2026-09-16T01:00:00Z"))
    rows = {row["id"]: row for row in lease_memory_observations(fleet.conn)}
    assert rows["art-probe"]["started_utc"] == "2026-09-16T01:00:00Z"
