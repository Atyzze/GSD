from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

GIB = 1 << 30
DEEP = 4194304


@pytest.fixture
def fleet(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "the lanes"}, search_seed=11)["campaign_id"])
    law = "law-lane".ljust(64, "0")
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    for job_id, n, priority in (("deep", DEEP, 200_000_000 + DEEP), ("small", 16384, 100_016_384)):
        repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}",
                        n=n, seed=0, replicate=0, spec={}, priority=priority, requested_by="test", sealed=False)
    yield repo, campaign
    repo.close()


def _events(repo, topic):
    import json
    return [json.loads(r["payload_json"]) for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic=? ORDER BY event_id", (topic,)).fetchall()]


def test_the_held_room_is_lent_to_no_other_claim_and_the_held_seed_is_claimed_first(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    started = H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    assert started["new"] and H.active(repo.conn)["job_id"] == "deep"
    assert [e["job_id"] for e in _events(repo, "memory_hold_started")] == ["deep"]
    assert H.held_bytes(repo.conn, job_id="small") == 20 * GIB, "a simulation leaves the held room free"
    assert H.held_bytes(repo.conn, job_id="deep") == 0, "the held seed's own claim counts it once, as its own"
    assert H.start(repo.conn, job_id="small", campaign_id=campaign, n=16384, requested_bytes=GIB) is None, \
        "one hold at a time"
    claimed = repo.claim_job("w", ("simulate",), job_id="deep")
    assert claimed["job_id"] == "deep", "the held seed, though the other ranks first"
    assert H.active(repo.conn)["job_id"] == "deep" and H.held_bytes(repo.conn, job_id="small") == 20 * GIB
    repo.conn.execute("UPDATE jobs SET memory_reservation_bytes=? WHERE job_id='deep'", (20 * GIB,))
    assert H.held_bytes(repo.conn, job_id="small") == 0, "admitted, its room is its own reservation"
    assert H.active(repo.conn) is None and H.read(repo.conn)["ended"] == "admitted"
    assert [e["why"] for e in _events(repo, "memory_hold_ended")] == ["admitted"]


def test_a_seed_refused_again_keeps_its_hours_hold_and_does_not_start_a_new_one(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    t0 = 1_800_000_000.0
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB, now=t0)
    held = H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=22 * GIB, now=t0 + 30)
    assert held["requested_bytes"] == 22 * GIB and H.held_bytes(repo.conn, job_id="small", now=t0 + 31) == 22 * GIB, \
        "refused again asking for more, it holds the more"
    H.end(repo.conn, "deep", "admitted", now=t0 + 60)
    again = H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB, now=t0 + 120)
    assert not again.get("new") and again["until_epoch"] == t0 + H.HOLD_MAX_SECONDS, "the same hour"
    started = _events(repo, "memory_hold_started")
    assert [e.get("resumed") for e in started] == [None, True], "taken up again, and said so"
    assert started[0]["until_utc"] == started[1]["until_utc"]


def test_a_hold_that_runs_out_rests_the_fleet_so_holds_cannot_chain(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    t0 = 1_800_000_000.0
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB, now=t0)
    assert H.active(repo.conn, now=t0 + H.HOLD_MAX_SECONDS + 1) is None
    assert H.read(repo.conn)["state"] == "rested" and H.held_bytes(repo.conn, job_id="small") == 0
    for job_id in ("deep", "small"):
        assert H.start(repo.conn, job_id=job_id, campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB,
                       now=t0 + H.HOLD_MAX_SECONDS + 2) is None, f"{job_id}: no seed is held while the fleet rests"
    later = t0 + H.HOLD_MAX_SECONDS + H.HOLD_REST_SECONDS + 3
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB, now=later)
    assert [e["why"] for e in _events(repo, "memory_hold_ended")] == ["ran out"]
    out = later + H.HOLD_MAX_SECONDS + 1
    assert H.active(repo.conn, now=out) is None
    assert H.read(repo.conn)["rest_until_epoch"] == out + 2 * H.HOLD_REST_SECONDS
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB,
                   now=out + H.HOLD_REST_SECONDS + 1) is None, "still resting"
    after = out + 2 * H.HOLD_REST_SECONDS + 1
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB, now=after)
    H.end(repo.conn, "deep", "admitted", now=after + 5)
    assert H.read(repo.conn)["run_outs"] == 0
    assert H.rest_seconds(1) == H.HOLD_REST_SECONDS and H.rest_seconds(99) == H.HOLD_REST_MAX_SECONDS


def test_a_seed_no_longer_waiting_ends_its_hold(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    repo.conn.execute("UPDATE jobs SET status='cancelled' WHERE job_id='deep'")
    assert H.held_bytes(repo.conn, job_id="small") == 0
    assert H.active(repo.conn) is None and H.read(repo.conn)["ended"] == "not waiting"


def test_a_parked_laws_seeds_wait_for_nothing(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    assert H.seed_state(repo.conn, "deep") == "waiting"
    repo.conn.execute("UPDATE campaign_candidates SET state='PARKED' WHERE campaign_id=?", (campaign,))
    assert H.seed_state(repo.conn, "deep") == "gone"


def test_a_seed_parked_behind_a_lane_it_gave_up_holds_no_room(fleet):
    from graph_scale_dynamics.db.lane_yield import PARKED_UNTIL
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    repo.conn.execute("UPDATE jobs SET next_attempt_utc=? WHERE job_id='deep'", (PARKED_UNTIL,))
    assert H.seed_state(repo.conn, "deep") == "gone" and H.held_bytes(repo.conn, job_id="small") == 0


def test_the_held_room_comes_out_of_every_other_simulations_budget_and_no_analysis(fleet, monkeypatch):
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    budgets = []
    monkeypatch.setattr(M, "admission_quantiles", lambda conn: {})
    monkeypatch.setattr(M, "admission_headroom", lambda conn, snapshot=None, quantiles=None: {
        "small_pool_limit_bytes": GIB, "small_pool_budget_bytes": 30 * GIB, "budget_bytes": 30 * GIB,
        "lent_bytes": 0})
    monkeypatch.setattr(M, "admit_recorded_claim", lambda conn, **kw: budgets.append(kw["budget_bytes"]) or {})
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    M.locked_admission(repo, kind="simulation", reservation_bytes=2 * GIB, job_id="small", owner="w",
                       lease_generation=1)
    M.locked_admission(repo, kind="simulation", reservation_bytes=20 * GIB, job_id="deep", owner="w",
                       lease_generation=1)
    M.locked_admission(repo, kind="analysis", reservation_bytes=4 * GIB, campaign_id=campaign, artifact="a" * 64,
                       analysis_version="analysis-5.1.0", owner="w", claim_token="t")
    assert budgets == [10 * GIB, 30 * GIB, 30 * GIB], \
        "what is left beside the hold, the whole room for the held seed, and for an analysis (749; 748 gave it 10)"


def test_two_workers_at_once_start_one_hold_and_end_it_once(fleet, monkeypatch):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    stale = H._read_raw(repo.conn)
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)["new"]
    monkeypatch.setattr(H, "_read_raw", lambda conn: stale)
    assert H.start(repo.conn, job_id="small", campaign_id=campaign, n=DEEP, requested_bytes=9 * GIB) is None
    monkeypatch.undo()
    assert H.read(repo.conn)["job_id"] == "deep" and len(_events(repo, "memory_hold_started")) == 1
    seen = H._read_raw(repo.conn)
    repo.conn.execute("UPDATE jobs SET status='cancelled' WHERE job_id='deep'")
    assert H.active(repo.conn) is None
    monkeypatch.setattr(H, "_read_raw", lambda conn: seen)
    assert H.active(repo.conn) is None
    H.end(repo.conn, "deep", "admitted")
    monkeypatch.undo()
    assert [e["why"] for e in _events(repo, "memory_hold_ended")] == ["not waiting"], "one end, one event"


def test_a_worker_that_read_a_hold_before_it_ended_and_was_taken_up_again_cannot_end_it(fleet, monkeypatch):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    seen = H._read_raw(repo.conn)
    H.end(repo.conn, "deep", "admitted")
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)["state"] == "holding"
    monkeypatch.setattr(H, "_read_raw", lambda conn: seen)
    H.end(repo.conn, "deep", "not waiting")
    monkeypatch.undo()
    assert H.read(repo.conn)["state"] == "holding" and len(_events(repo, "memory_hold_ended")) == 1


def test_a_paused_campaign_holds_no_room(fleet):
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, campaign = fleet
    H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=20 * GIB)
    repo.conn.execute("UPDATE campaigns SET workers_target=0 WHERE campaign_id=?", (campaign,))
    assert H.held_bytes(repo.conn, job_id="small") == 0
    assert H.active(repo.conn) is None and H.read(repo.conn)["ended"] == "not waiting"
