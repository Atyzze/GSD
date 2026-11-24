from __future__ import annotations

import pytest
from graph_scale_dynamics.services.api import fleet_snapshots as api_fleet_snapshots

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


def _campaign_with_runs(repo, name: str, seed: int, laws: int, attempts_each: int) -> str:
    campaign_id = str(repo.create_campaign({"name": name}, search_seed=seed)["campaign_id"])
    for law in range(laws):
        cid = f"{name[0]}{law:04d}".ljust(64, "0")
        job_id = f"j-{cid}"
        repo.insert_candidate(cid, campaign_id, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=cid, kind="simulate", stage="base",
                        n=64, seed=0, replicate=0, spec={}, priority=100, requested_by="test")
        for number in range(1, attempts_each + 1):
            repo.record_attempt(f"a-{cid}-{number}", job_id, number, "test-worker")
    return campaign_id


def test_each_campaign_reads_its_own_runs_and_its_own_page(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.services.api import main as api

    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        first = _campaign_with_runs(repo, "first", 1, laws=3, attempts_each=2)
        second = _campaign_with_runs(repo, "second", 2, laws=1, attempts_each=1)
        api_fleet_snapshots._EXECUTION_COUNT_CACHE.update(at=0.0, value={})
        try:
            pages = {campaign_id: api.build_fast_overview(repo, campaign_id) for campaign_id in (first, second)}
        finally:
            api_fleet_snapshots._EXECUTION_COUNT_CACHE.update(at=0.0, value={})

    for campaign_id, page in pages.items():
        assert page["campaign_id"] == campaign_id, "the page reads the campaign it was asked for"
    assert pages[first]["runtime_counts"]["simulation_executions"] == 6
    assert pages[second]["runtime_counts"]["simulation_executions"] == 1
    assert {str(row["candidate_id"])[0] for row in pages[first].get("active") or []} <= {"f"}, (
        "the first campaign's page lists only its own laws")
