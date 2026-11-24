from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")
LAW = "law-extension-by-tier".ljust(64, "0")
STEP = 10_000_000


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "by-tier"}, search_seed=7)["campaign_id"])
    repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    for job, n, order, created in (("tier3-oldest", 65536, 40, "2026-11-06T20:00:00Z"),
                                   ("tier2-older", 16384, 30, "2026-11-06T21:00:00Z"),
                                   ("tier1-newest-65536", 65536, 20, "2026-11-06T23:00:00Z"),
                                   ("tier1-newer-16384", 16384, 20, "2026-11-06T22:30:00Z"),
                                   ("released-hold", 16384, 90, "2026-11-06T19:00:00Z")):
        repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage=f"rung_n{n}",
                        n=n, seed=1, replicate=0, spec={}, priority=order * STEP + n, requested_by="741-test",
                        sealed=False)
        repo.conn.execute("UPDATE jobs SET created_utc=? WHERE job_id=?", (created, job))
    yield repo
    repo.close()


def test_extension_below_the_lanes_serves_tier_one_first_then_the_longest_queued(repo):
    taken = []
    for _ in range(5):
        job = repo.claim_job("executor-1-1", ("simulate",), min_n=16384, max_n=1048575, order="oldest")
        assert job is not None
        taken.append(job["job_id"])
    assert taken == ["tier1-newer-16384", "tier1-newest-65536", "tier2-older", "tier3-oldest", "released-hold"]
