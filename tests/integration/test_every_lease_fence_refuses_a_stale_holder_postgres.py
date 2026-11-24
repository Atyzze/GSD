from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

VERSION = "fence-test-v1"
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
OWNER, OTHER = "executor-holder", "executor-stale"


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = {"mode": "bounded", "ladder": [256], "analysis_version": VERSION}
        repo.insert_campaign("camp-fence", spec, content_hash(spec))
        repo.insert_candidate("law-fence", "camp-fence", LAW, "metropolis", 1, "DISCOVERY_ACTIVE")
        yield repo


def _job(repo, job_id: str = "job-fence", seed: int = 7) -> None:
    repo.insert_job(job_id=job_id, campaign_id="camp-fence", candidate_id="law-fence", kind="simulate",
                    stage="PILOT", n=256, seed=seed, replicate=0, spec={"candidate_spec": LAW}, priority=10,
                    sealed=False, requested_by="639-test")


def _row(repo, table: str, where: str, args: tuple) -> dict:
    return dict(repo.conn.execute(f"SELECT * FROM {table} WHERE {where}", args).fetchone())


def _jobs_row(repo, job_id: str = "job-fence") -> dict:
    return _row(repo, "jobs", "job_id=?", (job_id,))


def _commit(repo, claimed: dict, owner: str = OWNER, generation: int | None = None, digest: str = "a" * 64,
            retention: dict | None = None) -> bool:
    return repo.commit_job_result(
        job_id=claimed["job_id"], owner=owner,
        lease_generation=int(claimed["lease_generation"]) if generation is None else generation,
        digest=digest, size=64, media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
        analysis_version=VERSION, retention=retention)


def test_every_simulation_write_refuses_another_owner_and_another_generation(repo):
    _job(repo)
    claimed = repo.claim_job(OWNER, ("simulate",))
    generation = int(claimed["lease_generation"])
    before = _jobs_row(repo)
    for owner, gen in ((OTHER, generation), (OWNER, generation + 1)):
        assert repo.renew_lease("job-fence", owner, gen, lease_seconds=3600) is False
        assert repo.settle_memory_reservation("job-fence", owner, gen, 123_456) is False
        assert repo.finish_job("job-fence", owner, gen, "failed", error="stale") is False
        assert repo.release_job("job-fence", owner, gen) is False
        assert repo.stop_job_at_resource_boundary(
            job_id="job-fence", owner=owner, lease_generation=gen, attempt_id="none", peak_rss_bytes=1,
            wall_seconds=1.0, hard_limit_bytes=1, error="stale") is False
        assert _commit(repo, claimed, owner=owner, generation=gen) is False
    after = _jobs_row(repo)
    for key in ("status", "lease_owner", "lease_generation", "lease_expires_utc", "memory_reservation_bytes",
                "result_artifact", "attempts", "error"):
        assert after[key] == before[key], key
    assert not repo.conn.execute("SELECT 1 FROM artifacts WHERE artifact_hash=?", ("a" * 64,)).fetchone()
    assert not repo.conn.execute("SELECT 1 FROM analysis_queue").fetchone(), "no analysis enqueued by a stale commit"
    assert repo.settle_memory_reservation("job-fence", OWNER, generation, 123_456) is True
    assert _jobs_row(repo)["memory_reservation_bytes"] == 123_456
    assert repo.renew_lease("job-fence", OWNER, generation, lease_seconds=3600) is True
    assert _commit(repo, claimed) is True
    done = _jobs_row(repo)
    assert done["status"] == "done" and done["result_artifact"] == "a" * 64 and done["lease_owner"] is None
    assert _commit(repo, claimed) is False, "a lease is committed once"


def test_a_lease_taken_by_another_fences_every_write_of_the_old_holder(repo):
    _job(repo)
    first = repo.claim_job(OWNER, ("simulate",))
    old_generation = int(first["lease_generation"])
    repo.conn.execute("UPDATE jobs SET lease_expires_utc='1970-01-01T00:00:00Z' WHERE job_id='job-fence'")
    assert repo.reclaim_expired() >= 1
    assert _jobs_row(repo)["status"] == "queued"
    assert repo.claim_job(OTHER, ("simulate",)) is None, "786: a seed whose worker vanished waits before it runs again"
    repo.conn.execute("UPDATE jobs SET next_attempt_utc=NULL WHERE job_id='job-fence'")
    second = repo.claim_job(OTHER, ("simulate",))
    assert second and int(second["lease_generation"]) > old_generation
    assert repo.renew_lease("job-fence", OWNER, old_generation) is False
    assert repo.finish_job("job-fence", OWNER, old_generation, "failed", error="late") is False
    assert repo.release_job("job-fence", OWNER, old_generation) is False
    assert _commit(repo, first, owner=OWNER, generation=old_generation, digest="d" * 64) is False
    row = _jobs_row(repo)
    assert (row["status"], row["lease_owner"], int(row["lease_generation"])) == (
        "leased", OTHER, int(second["lease_generation"]))
    assert not repo.conn.execute("SELECT 1 FROM artifacts WHERE artifact_hash=?", ("d" * 64,)).fetchone()
    assert repo.renew_lease("job-fence", OTHER, int(second["lease_generation"]), lease_seconds=3600) is True
    assert repo.reclaim_expired() == 0 and _jobs_row(repo)["lease_owner"] == OTHER


def test_a_release_gives_the_claim_back_unspent_and_only_to_its_holder(repo):
    _job(repo)
    claimed = repo.claim_job(OWNER, ("simulate",))
    attempts = int(_jobs_row(repo)["attempts"])
    assert repo.release_job("job-fence", OTHER, int(claimed["lease_generation"])) is False
    assert repo.release_job("job-fence", OWNER, int(claimed["lease_generation"])) is True
    row = _jobs_row(repo)
    assert row["status"] == "queued" and row["lease_owner"] is None and int(row["attempts"]) == max(0, attempts - 1)


def _analysis(repo, digest: str = "a" * 64, retention: dict | None = None) -> dict:
    _job(repo)
    claimed = repo.claim_job(OWNER, ("simulate",))
    assert _commit(repo, claimed, digest=digest, retention=retention)
    analysis = repo.claim_analysis_job(OWNER, VERSION)
    assert analysis and analysis["analysis_claim_token"]
    return analysis


def _queue_row(repo, digest: str = "a" * 64) -> dict:
    return _row(repo, "analysis_queue", "campaign_id='camp-fence' AND input_artifact=? AND analysis_version=?",
                (digest, VERSION))


def _commit_analysis(repo, owner: str, token: str, digest: str = "a" * 64) -> bool:
    return repo.commit_analysis_result(
        campaign_id="camp-fence", input_artifact=digest, analysis_version=VERSION, owner=owner,
        claim_token=token, curves_digest="c" * 64, curves_size=32, producer_job="job-fence",
        analysis_id="analysis-fence", candidate_id="law-fence", n=256, seed=7, metrics={"d_V": {"value": 2.0}},
        provenance_status="verified", provenance_detail={"test": 639})


def test_every_analysis_write_refuses_another_owner_and_another_token(repo):
    analysis = _analysis(repo)
    token = analysis["analysis_claim_token"]
    before = _queue_row(repo)
    for owner, tok in ((OTHER, token), (OWNER, "not-the-token")):
        assert repo.renew_analysis_claim("camp-fence", "a" * 64, VERSION, owner, tok) is False
        assert repo.settle_analysis_memory_reservation("camp-fence", "a" * 64, VERSION, owner, tok, 999) is False
        assert repo.release_analysis_claim("camp-fence", "a" * 64, VERSION, owner, tok) is False
        assert repo.fail_analysis_claim("camp-fence", "a" * 64, VERSION, owner, tok, error="stale",
                                        error_class="child_crash", retryable=True) is None
        assert repo.fail_analysis_claim("camp-fence", "a" * 64, VERSION, owner, tok, error="full",
                                        error_class="no_space_left", retryable=True) is None
        assert repo.stop_analysis_at_resource_boundary(
            campaign_id="camp-fence", input_artifact="a" * 64, analysis_version=VERSION, owner=owner,
            claim_token=tok, peak_rss_bytes=1, wall_seconds=1.0, hard_limit_bytes=1, error="stale") is False
        assert _commit_analysis(repo, owner, tok) is False
        assert repo.replay_missing_transient_result(
            campaign_id="camp-fence", artifact_hash="a" * 64, analysis_version=VERSION, owner=owner,
            claim_token=tok) is False
    after = _queue_row(repo)
    for key in ("status", "lease_owner", "claim_token", "lease_expires_utc", "memory_reservation_bytes",
                "attempts", "error"):
        assert after[key] == before[key], key
    assert not repo.conn.execute("SELECT 1 FROM measurements").fetchone(), "no measurement from a stale claim"
    assert _jobs_row(repo)["status"] == "done", "the producer is not requeued by a stale replay"
    assert _commit_analysis(repo, OWNER, token) is True
    assert _queue_row(repo)["status"] == "done"
    assert repo.conn.execute("SELECT COUNT(*) c FROM measurements").fetchone()["c"] == 1
    assert _commit_analysis(repo, OWNER, token) is False, "a claim is committed once"


def test_an_expired_analysis_claim_nobody_reclaimed_commits(repo):
    analysis = _analysis(repo)
    repo.conn.execute("UPDATE analysis_queue SET lease_expires_utc='1970-01-01T00:00:00Z'")
    assert _commit_analysis(repo, OWNER, analysis["analysis_claim_token"]) is True
    assert repo.conn.execute("SELECT COUNT(*) c FROM measurements").fetchone()["c"] == 1


def test_a_reclaimed_analysis_claim_cannot_commit(repo):
    analysis = _analysis(repo)
    repo.conn.execute("UPDATE analysis_queue SET lease_expires_utc='1970-01-01T00:00:00Z'")
    repo.reclaim_expired()
    assert _queue_row(repo)["claim_token"] is None, "the reclaim takes the token"
    assert _commit_analysis(repo, OWNER, analysis["analysis_claim_token"]) is False
    assert not repo.conn.execute("SELECT 1 FROM measurements").fetchone()


def test_every_evidence_rebuild_write_refuses_a_stale_token(repo):
    analysis = _analysis(repo)
    assert _commit_analysis(repo, OWNER, analysis["analysis_claim_token"])
    rebuild = repo.claim_candidate_evidence_rebuild(OWNER, VERSION)
    assert rebuild and rebuild["candidate_id"] == "law-fence"
    token = rebuild["rebuild_claim_token"]
    revision = repo.conn.execute(
        "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') newest FROM measurements WHERE campaign_id='camp-fence'"
    ).fetchone()
    where = ("campaign_id='camp-fence' AND candidate_id='law-fence' AND analysis_version=?", (VERSION,))
    before = _row(repo, "candidate_evidence_rebuilds", *where)

    def complete(owner, tok):
        return repo.complete_candidate_evidence_rebuild(
            campaign_id="camp-fence", candidate_id="law-fence", analysis_version=VERSION, owner=owner,
            claim_token=tok, measurement_count=int(revision["c"]), newest_measurement_utc=revision["newest"],
            summaries={256: {"seeds": 1}}, transitions=[])
    for owner, tok in ((OTHER, token), (OWNER, "not-the-token")):
        assert repo.release_candidate_evidence_rebuild("camp-fence", "law-fence", VERSION, owner, tok) is False
        assert repo.fail_candidate_evidence_rebuild("camp-fence", "law-fence", VERSION, owner, tok,
                                                    error="stale") is None
        assert complete(owner, tok) == "fenced"
    after = _row(repo, "candidate_evidence_rebuilds", *where)
    for key in ("status", "lease_owner", "claim_token", "attempts", "error"):
        assert after[key] == before[key], key
    assert not repo.conn.execute("SELECT 1 FROM rung_summaries").fetchone(), "no summary from a stale rebuild"
    stale = repo.complete_candidate_evidence_rebuild(
        campaign_id="camp-fence", candidate_id="law-fence", analysis_version=VERSION, owner=OWNER,
        claim_token=token, measurement_count=int(revision["c"]) + 1, newest_measurement_utc=revision["newest"],
        summaries={256: {"seeds": 1}}, transitions=[])
    assert stale == "stale" and not repo.conn.execute("SELECT 1 FROM rung_summaries").fetchone()
    assert complete(OWNER, token) == "done"
    assert _row(repo, "candidate_evidence_rebuilds", *where)["status"] == "done"
    assert repo.conn.execute("SELECT COUNT(*) c FROM rung_summaries").fetchone()["c"] == 1


TRANSIENT = {"body_state": "transient", "encoding": "gzip", "detail": {"why": "tmpfs only"}}


def test_a_lost_transient_body_requeues_its_exact_producer_and_the_replay_revives_the_analysis(repo):
    analysis = _analysis(repo, retention=TRANSIENT)
    attempts_before = int(_jobs_row(repo)["attempts"])
    assert repo.artifact_retention("a" * 64)["body_state"] == "transient"
    for owner, token in ((OTHER, analysis["analysis_claim_token"]), (OWNER, "not-the-token")):
        assert repo.replay_missing_transient_result(
            campaign_id="camp-fence", artifact_hash="a" * 64, analysis_version=VERSION, owner=owner,
            claim_token=token) is False
    assert _queue_row(repo)["status"] == "leased" and _jobs_row(repo)["status"] == "done"
    assert repo.artifact_retention("a" * 64)["body_state"] == "transient", "a stale replay evicts nothing"
    assert repo.replay_missing_transient_result(
        campaign_id="camp-fence", artifact_hash="a" * 64, analysis_version=VERSION, owner=OWNER,
        claim_token=analysis["analysis_claim_token"]) is True
    queue = _queue_row(repo)
    assert queue["status"] == "failed" and queue["lease_owner"] is None and queue["claim_token"] is None
    assert str(queue["error"]).startswith("TRANSIENT_RAW_LOST:")
    retention = repo.artifact_retention("a" * 64)
    assert retention["body_state"] == "evicted" and retention["evicted_utc"]
    assert retention["detail"]["replay_queued"] is True and retention["detail"]["why"] == "tmpfs only"
    job = _jobs_row(repo)
    assert job["status"] == "queued" and job["result_artifact"] is None and job["lease_owner"] is None
    assert int(job["attempts"]) == max(0, attempts_before - 1), "the replay spends no scientific retry"
    assert repo.replay_missing_transient_result(
        campaign_id="camp-fence", artifact_hash="a" * 64, analysis_version=VERSION, owner=OWNER,
        claim_token=analysis["analysis_claim_token"]) is False, "once"
    again = repo.claim_job(OWNER, ("simulate",))
    assert again and again["job_id"] == "job-fence"
    assert _commit(repo, again, retention=TRANSIENT) is True
    revived = _queue_row(repo)
    assert revived["status"] == "queued" and int(revived["attempts"]) == 0 and revived["error"] is None
    assert repo.artifact_retention("a" * 64)["body_state"] == "transient"
    assert repo.claim_analysis_job(OWNER, VERSION)["result_artifact"] == "a" * 64


def test_the_replay_refuses_a_durable_body_and_an_artifact_already_measured(repo):
    durable = _analysis(repo)
    assert repo.replay_missing_transient_result(
        campaign_id="camp-fence", artifact_hash="a" * 64, analysis_version=VERSION, owner=OWNER,
        claim_token=durable["analysis_claim_token"]) is False
    assert _queue_row(repo)["status"] == "leased" and _jobs_row(repo)["status"] == "done"
    _job(repo, "job-fence-2", seed=8)
    claimed = repo.claim_job(OWNER, ("simulate",))
    assert _commit(repo, claimed, digest="e" * 64, retention=TRANSIENT)
    second = repo.claim_analysis_job(OWNER, VERSION)
    assert second["result_artifact"] == "e" * 64
    assert repo.commit_analysis_result(
        campaign_id="camp-fence", input_artifact="e" * 64, analysis_version=VERSION, owner=OWNER,
        claim_token=second["analysis_claim_token"], curves_digest="f" * 64, curves_size=32,
        producer_job="job-fence-2", analysis_id="analysis-fence-2", candidate_id="law-fence", n=256, seed=8,
        metrics={"d_V": {"value": 2.0}}, provenance_status="verified", provenance_detail={"test": 639})
    repo.conn.execute(
        "UPDATE analysis_queue SET status='leased',lease_owner=?,claim_token='again',"
        "lease_expires_utc='2999-01-01T00:00:00Z' WHERE input_artifact=?", (OWNER, "e" * 64))
    assert repo.replay_missing_transient_result(
        campaign_id="camp-fence", artifact_hash="e" * 64, analysis_version=VERSION, owner=OWNER,
        claim_token="again") is False
    assert _jobs_row(repo, "job-fence-2")["status"] == "done"
    assert repo.artifact_retention("e" * 64)["body_state"] == "transient"
