from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

VERSION = "backlog-contract-v1"
CANDIDATE_SPEC = {
    "terms": [{"kind": "edge_count", "coefficient": 0.3}],
    "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2},
}


def _queued_analysis_row(repo: Repo, *, candidate: str, job_id: str, stage: str,
                         n: int, digest: str) -> None:
    repo.insert_job(job_id=job_id, campaign_id="camp-backlog", candidate_id=candidate,
                    kind="simulate", stage=stage, n=n, seed=0, replicate=0,
                    spec={"candidate_spec": CANDIDATE_SPEC}, priority=10,
                    sealed=False, requested_by="backlog-contract")
    claimed = repo.claim_job("executor-backlog", ("simulate",))
    assert claimed and claimed["job_id"] == job_id
    assert repo.commit_job_result(
        job_id=job_id, owner="executor-backlog",
        lease_generation=claimed["lease_generation"], digest=digest, size=123,
        media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
        analysis_version=VERSION,
    )


def _fixture(dsn: str, *, stage: str, state: str) -> Repo:
    init_db(dsn)
    repo = Repo(dsn)
    spec = {"mode": "continuous", "ladder": [16384, 65536], "analysis_version": VERSION}
    repo.insert_campaign("camp-backlog", spec, content_hash(spec))
    repo.insert_candidate("cand-backlog", "camp-backlog", CANDIDATE_SPEC,
                          "metropolis", 1, "DISCOVERY_ACTIVE")
    _queued_analysis_row(repo, candidate="cand-backlog", job_id="job-backlog",
                         stage=stage, n=65536, digest="a" * 64)
    repo.set_candidate_state("cand-backlog", state, "fixture", campaign_id="camp-backlog")
    return repo


@pytest.mark.parametrize("stage", ["rung_n65536", "base_block"])
@pytest.mark.parametrize("state", ["PARKED", "DISCOVERY_ACTIVE"])
def test_the_counter_and_the_claim_never_disagree(isolated_postgres_schema, stage, state):
    repo = _fixture(isolated_postgres_schema.dsn, stage=stage, state=state)
    try:
        counted = repo.analysis_backlog(VERSION) > 0
        claimable = repo.claim_analysis_job("executor-backlog", VERSION) is not None
        assert counted == claimable, (
            f"state={state} stage={stage}: backlog says {counted}, claim says "
            f"{claimable}. A slot allocator reading the first and an executor "
            "calling the second cannot both be right")
    finally:
        repo.close()
