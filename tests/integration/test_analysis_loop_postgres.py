from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

VERSION = "loop-v1"


def _repo(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    return Repo(isolated_postgres_schema.dsn)


def _committed_artifact(repo, *, digest, campaign="camp-loop", candidate="cand-loop",
                        job="job-loop", seed=7, replicate=0):
    campaign_spec = {"mode": "bounded", "ladder": [256], "analysis_version": VERSION}
    candidate_spec = {
        "terms": [{"kind": "edge_count", "coefficient": 0.3}],
        "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2},
    }
    if not repo.conn.execute(
        "SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign,)
    ).fetchone():
        repo.insert_campaign(campaign, campaign_spec, content_hash(campaign_spec))
    if not repo.conn.execute(
        "SELECT 1 FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
        (campaign, candidate),
    ).fetchone():
        repo.insert_candidate(candidate, campaign, candidate_spec, "metropolis", 1,
                              "DISCOVERY_ACTIVE")
    repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=candidate,
                    kind="simulate", stage="PILOT", n=256, seed=seed,
                    replicate=replicate, spec={"candidate_spec": candidate_spec},
                    priority=10, sealed=False, requested_by="build227-test")
    claimed = repo.claim_job("executor-loop", ("simulate",))
    assert claimed and claimed["job_id"] == job
    assert repo.commit_job_result(
        job_id=job, owner="executor-loop",
        lease_generation=claimed["lease_generation"], digest=digest, size=64,
        media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
        analysis_version=VERSION,
    )
    return campaign, candidate, job


def _force_due(repo, campaign, digest):
    repo.conn.execute(
        "UPDATE analysis_queue SET next_attempt_utc='1970-01-01T00:00:00Z' "
        "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
        (campaign, digest, VERSION),
    )


def _row(repo, campaign, digest):
    return repo.conn.execute(
        "SELECT status,attempts,max_attempts,error,error_class FROM analysis_queue "
        "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
        (campaign, digest, VERSION),
    ).fetchone()


def _exhaust(repo, campaign, digest, *, error_class, final_retryable=True):
    cap = int(_row(repo, campaign, digest)["max_attempts"])
    for attempt in range(1, cap + 1):
        claim = repo.claim_analysis_job("executor-loop", VERSION)
        assert claim is not None, f"attempt {attempt} of {cap} should be claimable"
        assert claim["analysis_attempt_number"] == attempt
        disposition = repo.fail_analysis_claim(
            campaign, digest, VERSION, "executor-loop",
            claim["analysis_claim_token"],
            error=f"deterministic failure {attempt}", error_class=error_class,
            retryable=final_retryable, terminal_topic="analysis_failed",
            terminal_payload={"job_id": claim["job_id"],
                              "candidate_id": claim["candidate_id"]},
        )
        assert disposition is not None
        if attempt < cap:
            assert disposition["retry"] is True
            _force_due(repo, campaign, digest)
    assert _row(repo, campaign, digest)["status"] == "failed"


def test_claim_refuses_rows_past_their_attempt_budget(isolated_postgres_schema):
    repo = _repo(isolated_postgres_schema)
    try:
        digest = "a" * 64
        campaign, _, _ = _committed_artifact(repo, digest=digest)
        _exhaust(repo, campaign, digest, error_class="child_process:unclassified")
        assert repo.claim_analysis_job("executor-loop", VERSION) is None
        repo.conn.execute(
            "UPDATE analysis_queue SET status='queued',next_attempt_utc=NULL "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
            (campaign, digest, VERSION),
        )
        assert repo.claim_analysis_job("executor-loop", VERSION) is None
    finally:
        repo.close()


def test_transient_raw_lost_replay_restores_budget(isolated_postgres_schema):
    repo = _repo(isolated_postgres_schema)
    try:
        digest = "d" * 64
        campaign, candidate, _ = _committed_artifact(repo, digest=digest)
        _exhaust(repo, campaign, digest, error_class="child_process:unclassified")
        repo.conn.execute(
            "UPDATE analysis_queue SET error='TRANSIENT_RAW_LOST: producer replay queued' "
            "WHERE campaign_id=? AND input_artifact=? AND analysis_version=?",
            (campaign, digest, VERSION),
        )
        _committed_artifact(repo, digest=digest, campaign=campaign,
                            candidate=candidate, job="job-loop-replay", seed=7,
                            replicate=1)
        row = _row(repo, campaign, digest)
        assert row["status"] == "queued" and row["attempts"] == 0
        claim = repo.claim_analysis_job("executor-loop", VERSION)
        assert claim is not None and claim["analysis_attempt_number"] == 1
    finally:
        repo.close()
