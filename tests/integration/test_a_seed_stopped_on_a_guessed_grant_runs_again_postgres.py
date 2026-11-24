from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

VERSION = "runaway-test-v1"
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
OWNER = "executor-holder"
GIB = 1024 ** 3


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import content_hash
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = {"mode": "bounded", "ladder": [65536], "analysis_version": VERSION}
        repo.insert_campaign("camp-run", spec, content_hash(spec))
        repo.insert_candidate("law-run", "camp-run", LAW, "metropolis", 1, "DISCOVERY_ACTIVE")
        yield repo


def _claimed(repo, job_id: str = "job-run", seed: int = 0) -> dict:
    repo.insert_job(job_id=job_id, campaign_id="camp-run", candidate_id="law-run", kind="simulate",
                    stage="PILOT", n=65536, seed=seed, replicate=0, spec={"candidate_spec": LAW}, priority=10,
                    sealed=False, requested_by="843-test")
    claimed = repo.claim_job(OWNER, ("simulate",))
    repo.record_attempt(f"attempt-{job_id}", job_id, 1, OWNER)
    return claimed


def _stop(repo, claimed: dict, *, requeue: bool, peak: int) -> bool:
    return repo.stop_job_at_resource_boundary(
        job_id=claimed["job_id"], owner=OWNER, lease_generation=int(claimed["lease_generation"]),
        attempt_id=f"attempt-{claimed['job_id']}", peak_rss_bytes=peak, wall_seconds=120.0,
        hard_limit_bytes=2 * GIB, error="supervised RSS boundary reached (runaway)", requeue=requeue)


def _job(repo, job_id: str = "job-run") -> dict:
    return dict(repo.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())


def _attempt(repo, job_id: str = "job-run") -> dict:
    return dict(repo.conn.execute("SELECT * FROM attempts WHERE job_id=?", (job_id,)).fetchone())


def test_a_seed_stopped_on_its_guessed_bound_goes_back_unspent_and_is_not_the_law_s_failure(repo):
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_MEMORY_RUNAWAY, INTERRUPTED_ATTEMPT_CLASSES
    claimed = _claimed(repo)
    attempts = int(_job(repo)["attempts"])
    assert _stop(repo, claimed, requeue=True, peak=int(2.13 * GIB)) is True
    job = _job(repo)
    assert job["status"] == "queued" and job["lease_owner"] is None and job["next_attempt_utc"] is not None
    assert int(job["attempts"]) == max(0, attempts - 1), "the law is not charged for the host's guess"
    attempt = _attempt(repo)
    assert attempt["error_class"] == ATTEMPT_CLASS_MEMORY_RUNAWAY in INTERRUPTED_ATTEMPT_CLASSES
    assert int(attempt["peak_rss_bytes"]) == int(2.13 * GIB)
    assert not repo.conn.execute("SELECT 1 FROM events WHERE topic='analysis_ready'").fetchone(), (
        "no failure is announced: the seed runs again")


def test_a_seed_stopped_at_the_host_ceiling_still_fails_as_before(repo):
    claimed = _claimed(repo)
    assert _stop(repo, claimed, requeue=False, peak=int(40 * GIB)) is True
    assert _job(repo)["status"] == "failed" and _attempt(repo)["error_class"] == "memory_hard_stop"
    assert repo.conn.execute("SELECT 1 FROM events WHERE topic='analysis_ready'").fetchone()


def test_the_next_grant_is_at_least_what_the_stopped_seed_was_seen_to_need(repo):
    from graph_scale_dynamics.scheduling import memory as M
    spec = {"candidate_spec": LAW}
    before = M.predicted_claim_peak_bytes(repo.conn, kind="simulation", campaign_id="camp-run",
                                          candidate_id="law-run", n=65536, spec=spec)
    assert M.runaway_seen_bytes(repo.conn, "simulation", "camp-run", "law-run", 65536) == 0
    _stop(repo, _claimed(repo), requeue=True, peak=int(2.13 * GIB))
    seen = M.runaway_seen_bytes(repo.conn, "simulation", "camp-run", "law-run", 65536)
    assert seen == int(2.13 * GIB)
    after = M.predicted_claim_peak_bytes(repo.conn, kind="simulation", campaign_id="camp-run",
                                         candidate_id="law-run", n=65536, spec=spec)
    assert after >= int(seen * M.RUNAWAY_SEEN_SLACK) and after >= before
    bound, kind = M.process_stop_bytes(spec, 65536, after)
    assert bound >= 4 * after or kind == "ceiling", "the second run is not stopped where the first was"
    assert M.runaway_seen_bytes(repo.conn, "simulation", "camp-run", "other-law", 65536) == 0
    assert M.runaway_seen_bytes(repo.conn, "simulation", "camp-run", "law-run", 16384) == 0, "its own size only"


def _analysis(repo) -> dict:
    claimed = _claimed(repo, "job-made")
    assert repo.commit_job_result(
        job_id="job-made", owner=OWNER, lease_generation=int(claimed["lease_generation"]), digest="a" * 64,
        size=64, media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
        analysis_version=VERSION)
    analysis = repo.claim_analysis_job(OWNER, VERSION)
    assert analysis and analysis["analysis_claim_token"]
    return analysis


def test_an_analysis_stopped_on_its_guessed_bound_runs_again_and_one_at_the_ceiling_fails(repo):
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_MEMORY_RUNAWAY
    analysis = _analysis(repo)

    def stop(requeue: bool, token: str) -> bool:
        return repo.stop_analysis_at_resource_boundary(
            campaign_id="camp-run", input_artifact="a" * 64, analysis_version=VERSION, owner=OWNER,
            claim_token=token, peak_rss_bytes=int(2.84 * GIB), wall_seconds=40.0, hard_limit_bytes=int(2.77 * GIB),
            error="supervised RSS boundary reached (runaway)", requeue=requeue)
    assert stop(True, analysis["analysis_claim_token"]) is True
    row = dict(repo.conn.execute("SELECT * FROM analysis_queue WHERE input_artifact=?", ("a" * 64,)).fetchone())
    assert row["status"] == "queued" and row["error_class"] == ATTEMPT_CLASS_MEMORY_RUNAWAY
    assert row["next_attempt_utc"] is not None and int(row["peak_rss_bytes"]) == int(2.84 * GIB)
    assert not repo.conn.execute("SELECT 1 FROM events WHERE topic='analysis_ready' "
                                 "AND payload_json LIKE '%resource_hard_stop%'").fetchone()
    repo.conn.execute("UPDATE analysis_queue SET next_attempt_utc=NULL")
    again = repo.claim_analysis_job(OWNER, VERSION)
    assert again and again["analysis_claim_token"], "it is claimed again"
    assert stop(False, again["analysis_claim_token"]) is True
    row = dict(repo.conn.execute("SELECT * FROM analysis_queue WHERE input_artifact=?", ("a" * 64,)).fetchone())
    assert row["status"] == "failed" and row["error_class"] == "memory_hard_cap"
