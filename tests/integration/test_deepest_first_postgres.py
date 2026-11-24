from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")
LAW = "law-deepest-first".ljust(64, "0")


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "deepest"}, search_seed=5)["campaign_id"])
    repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    for job, n in (("deep-262144", 262144), ("deep-1048576", 1048576)):
        repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage=f"rung_n{n}",
                        n=n, seed=1, replicate=0, spec={}, priority=20 * 10_000_000 + n, requested_by="test",
                        sealed=False)
    yield repo
    repo.close()


def test_deepest_first_takes_the_million_rung_job(repo):
    job = repo.claim_job("executor-1-1", ("simulate",), min_n=32768, order="deepest")
    assert job is not None and int(job["n"]) == 1048576


def test_the_ordinary_order_is_unchanged(repo):
    job = repo.claim_job("executor-1-1", ("simulate",), min_n=32768)
    assert job is not None and int(job["n"]) == 262144
