from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.scheduling import fleet_halves

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

VERSION = "halves-v1"
CAMPAIGN, LAW = "camp-halves", "law-halves"


def _queued(repo, *, n: int, priority: int, created: str) -> str:
    spec = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
            "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
    if not repo.conn.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (CAMPAIGN,)).fetchone():
        campaign_spec = {"mode": "bounded", "ladder": [4096, 16384, 65536], "analysis_version": VERSION}
        repo.insert_campaign(CAMPAIGN, campaign_spec, content_hash(campaign_spec))
        repo.insert_candidate(LAW, CAMPAIGN, spec, "metropolis", 1, "DISCOVERY_ACTIVE")
    job, digest = f"job-{n}", f"{n:064d}"
    repo.insert_job(job_id=job, campaign_id=CAMPAIGN, candidate_id=LAW, kind="simulate", stage=f"rung_n{n}", n=n,
                    seed=1, replicate=0, spec={"candidate_spec": spec}, priority=priority, sealed=False,
                    requested_by="607-test")
    claimed = repo.claim_job("executor-halves", ("simulate",), job_id=job)
    assert claimed and repo.commit_job_result(
        job_id=job, owner="executor-halves", lease_generation=claimed["lease_generation"], digest=digest, size=64,
        media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"}, analysis_version=VERSION)
    repo.conn.execute("UPDATE analysis_queue SET created_utc=? WHERE input_artifact=?", (created, digest))
    return digest


def test_extensions_half_reads_the_longest_queued_and_base_exploration_by_rank(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        deep = fleet_halves.EXTENSION_FROM_N
        _queued(repo, n=16384, priority=20 * 10_000_000 + 16384, created="2026-10-08T12:00:00Z")
        oldest = _queued(repo, n=65536, priority=30 * 10_000_000 + 65536, created="2026-10-08T09:00:00Z")
        _queued(repo, n=1024, priority=10 * 10_000_000 + 1024, created="2026-10-08T13:00:00Z")
        block = _queued(repo, n=256, priority=10 * 10_000_000 + 256, created="2026-10-08T14:00:00Z")
        assert repo.analysis_leased_count() == 0

        later = _queued(repo, n=262144, priority=30 * 10_000_000 + 262144, created="2026-10-08T10:00:00Z")
        first = repo.claim_analysis_job("executor-halves", VERSION, min_n=deep, order="oldest")
        assert first["n"] == 16384
        second = repo.claim_analysis_job("executor-halves", VERSION, min_n=deep, order="oldest")
        assert second["result_artifact"] == oldest, "then within a queue order the longest queued: 09:00 before 10:00"
        assert later != oldest
        assert (repo.analysis_leased_count(min_n=deep), repo.analysis_leased_count()) == (2, 2)

        base = repo.claim_analysis_job("executor-halves", VERSION, max_n=deep - 1)
        assert base["result_artifact"] == block, "base exploration by rank: 256 before 1,024"
        assert (repo.analysis_leased_count(min_n=deep), repo.analysis_leased_count(max_n=deep - 1)) == (2, 1)
        assert repo.analysis_leased_count() == 3

        by_rank = repo.claim_analysis_job("executor-halves", VERSION)
        assert by_rank["n"] == 1024, "with neither argument the claim is by rank, as before 607"
    finally:
        repo.close()
