from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

VERSION = "dropped-test-v1"
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = {"mode": "bounded", "ladder": [256], "analysis_version": VERSION}
        repo.insert_campaign("camp-d", spec, content_hash(spec))
        repo.insert_candidate("law-d", "camp-d", LAW, "metropolis", 1, "DISCOVERY_ACTIVE")
        yield repo


def _job(repo, job_id: str, seed: int) -> bool:
    return repo.insert_job(job_id=job_id, campaign_id="camp-d", candidate_id="law-d", kind="simulate", stage="PILOT",
                           n=256, seed=seed, replicate=0, spec={"candidate_spec": LAW}, priority=10, sealed=False,
                           requested_by="639-test")


def _jobs(repo) -> list[dict]:
    return [dict(r) for r in repo.conn.execute(
        "SELECT job_id,graph_ordinal,status,lease_owner FROM jobs WHERE campaign_id='camp-d' ORDER BY job_id")]


def test_a_duplicate_job_id_is_a_no_op_and_takes_no_ordinal(repo):
    assert _job(repo, "job-1", 1) is True and _job(repo, "job-2", 2) is True
    assert _job(repo, "job-1", 1) is False, "a re-enqueue of the same id"
    rows = _jobs(repo)
    assert [r["job_id"] for r in rows] == ["job-1", "job-2"]
    assert sorted(r["graph_ordinal"] for r in rows) == [1, 2], "distinct ordinals, none burned by the re-enqueue"


def test_an_ordinal_collision_raises_rather_than_dropping_the_job(repo):
    assert _job(repo, "job-1", 1) is True
    repo.conn.execute("UPDATE campaign_graph_counter SET next_ordinal=1 WHERE campaign_id='camp-d'")
    with pytest.raises(Exception) as raised:
        _job(repo, "job-2", 2)
    assert "ordinal" in str(raised.value).lower() or "unique" in str(raised.value).lower(), raised.value
    repo.conn.rollback_if_open()
    assert [r["job_id"] for r in _jobs(repo)] == ["job-1"], "nothing was written in silence"


def test_expired_leases_are_reclaimed_in_bounded_batches_a_null_owner_included(repo):
    for i in range(5):
        _job(repo, f"job-{i}", i)
    for i in range(5):
        assert repo.claim_job(f"executor-{i}", ("simulate",))
    repo.conn.execute("UPDATE jobs SET lease_expires_utc='1970-01-01T00:00:00Z' WHERE campaign_id='camp-d'")
    repo.conn.execute("UPDATE jobs SET lease_owner=NULL WHERE job_id='job-0'")
    assert repo.reclaim_expired(batch_size=2) == 2, "one batch a call"
    assert sum(r["status"] == "queued" for r in _jobs(repo)) == 2
    assert repo.reclaim_expired(batch_size=2) == 2 and repo.reclaim_expired(batch_size=2) == 1
    rows = _jobs(repo)
    assert all(r["status"] == "queued" and r["lease_owner"] is None for r in rows), rows
    assert repo.reclaim_expired(batch_size=2) == 0


def test_a_live_lease_is_never_reclaimed(repo):
    _job(repo, "job-live", 1)
    assert repo.claim_job("executor-live", ("simulate",), lease_seconds=3600)
    assert repo.reclaim_expired() == 0
    assert _jobs(repo)[0]["status"] == "leased" and _jobs(repo)[0]["lease_owner"] == "executor-live"


def test_the_ladder_s_standing_reads_terminal_jobs_of_the_visible_laws_only(repo):
    repo.insert_candidate("law-hidden", "camp-d", LAW, "metropolis", 1, "DISCOVERY_ACTIVE")
    for i, status in enumerate(("done", "failed", "cancelled", "lost", "queued")):
        _job(repo, f"job-{status}", i)
        repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, f"job-{status}"))
    repo.insert_job(job_id="job-hidden", campaign_id="camp-d", candidate_id="law-hidden", kind="simulate",
                    stage="PILOT", n=256, seed=99, replicate=0, spec={"candidate_spec": LAW}, priority=10,
                    sealed=False, requested_by="639-test")
    states = repo.dashboard_rung_job_states("camp-d", ["law-d"])
    assert set(states) == {"law-d"}, "bounded to the laws on display"
    assert sorted(row["status"] for row in states["law-d"]) == ["cancelled", "done", "failed", "lost", "queued"]
    assert repo.dashboard_rung_job_states("camp-d", []) == {}
