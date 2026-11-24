from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

G = 10 ** 9
LANE = 1048576
ASKS = {LANE: int(15.4 * G), 65536: int(0.4 * G)}
QUANTILES = {("simulation", LANE): (int(12.5 * G), int(14.0 * G)), ("simulation", 65536): (int(0.3 * G), int(0.4 * G))}
OLD = "2026-01-01T00:00:00Z"


@pytest.fixture
def fleet(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.services.worker import main as W
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "a refused seed"}, search_seed=11)["campaign_id"])
    law = "law-refused".ljust(64, "0")
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    for job_id, n in (("running", LANE), ("lane-a", LANE), ("lane-b", LANE), ("small", 65536)):
        repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}",
                        n=n, seed=0, replicate=0, spec={}, priority=100_000_000 + n, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status='leased',lease_owner='executor-1',memory_reservation_bytes=?,"
                      "lease_generation=1,updated_utc=? WHERE job_id='running'", (int(17.3 * G), OLD))
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "admission_quantiles", lambda conn, observations=None: dict(QUANTILES))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: ASKS[int(kw["n"])])
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    yield repo, monkeypatch, M, W
    repo.close()


def _host(M, monkeypatch, available):
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=int(available)))


def _deferred(repo):
    return [json.loads(r["payload_json"]) for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic='memory_admission_deferred' ORDER BY event_id").fetchall()]


def test_a_lane_seed_that_fits_beside_the_running_children_is_admitted_though_it_is_the_one_asking(fleet):
    repo, monkeypatch, M, W = fleet
    _host(M, monkeypatch, 47 * G)
    job = W.claim_simulation_for_owner(repo, "executor-2")
    assert job is not None and job["job_id"] == "lane-a", _deferred(repo)
    row = repo.conn.execute("SELECT memory_reservation_bytes FROM jobs WHERE job_id='lane-a'").fetchone()
    assert int(row["memory_reservation_bytes"]) == ASKS[LANE]


def test_a_lane_seed_refused_for_memory_hands_the_worker_to_a_seed_that_fits(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, monkeypatch, M, W = fleet
    _host(M, monkeypatch, 40 * G)
    job = W.claim_simulation_for_owner(repo, "executor-2")
    assert job is not None and job["job_id"] == "small"
    [refused] = _deferred(repo)
    assert (refused["job_id"], refused["refusal"]) == ("lane-a", "transient_memory_floor")
    assert H.active(repo.conn)["job_id"] == "lane-a", "the lane's room is held, and the small seed fits beside it"
    states = {r["job_id"]: r["status"] for r in repo.conn.execute("SELECT job_id,status FROM jobs").fetchall()}
    assert states == {"running": "leased", "lane-a": "queued", "lane-b": "queued", "small": "leased"}


def test_with_nothing_below_that_fits_the_worker_waits_and_each_size_is_asked_once(fleet):
    repo, monkeypatch, M, W = fleet
    _host(M, monkeypatch, 13 * G)
    assert W.claim_simulation_for_owner(repo, "executor-2") is None
    assert [e["job_id"] for e in _deferred(repo)] == ["lane-a", "small"]
    leased = [r["job_id"] for r in repo.conn.execute("SELECT job_id FROM jobs WHERE status='leased'").fetchall()]
    assert leased == ["running"]


def test_a_lane_seed_that_cannot_fit_once_the_fleet_drains_is_not_held_for_and_a_smaller_seed_runs(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, monkeypatch, M, W = fleet
    _host(M, monkeypatch, 20 * G)
    job = W.claim_simulation_for_owner(repo, "executor-2")
    assert job is not None and job["job_id"] == "small", "748 held 15.4 GB for lane-a here and the worker waited"
    assert [e["job_id"] for e in _deferred(repo)] == ["lane-a"]
    row = H.read(repo.conn)
    assert row["state"] == "unheld" and H.active(repo.conn) is None
    assert (row["unfit"]["job_id"], row["unfit"]["reach_bytes"]) == ("lane-a", 20 * G - 10 * (1 << 30)), \
        "20 GB available, no child's memory measured, nothing the relief may move, less the floor"
