from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


def _end_the_session_of(repo, other) -> None:
    pid = repo.conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
    other.conn.execute("SELECT pg_terminate_backend(?, 10000)", (pid,))


@pytest.fixture
def repos(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo, Repo(isolated_postgres_schema.dsn) as other:
        yield repo, other


def test_a_statement_outside_a_transaction_runs_on_a_new_session(repos):
    repo, other = repos
    repo.set_flag("paused", "0")
    _end_the_session_of(repo, other)
    assert repo.get_flag("paused", "1") == "0", "the supervisor's next read finds the database again"
    assert repo.conn.reconnects == 1


def test_inside_a_transaction_the_loss_is_transient_and_the_next_one_runs(repos):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    repo, other = repos
    repo.conn.execute("BEGIN")
    repo.conn.execute("SELECT 1")
    _end_the_session_of(repo, other)
    with pytest.raises(DatabaseOperationalError) as raised:
        repo.conn.execute("SELECT 2")
    assert raised.value.transient, "the caller's retry does the transaction again"
    assert not raised.value.outcome_unknown, "a transaction the session took with it committed nothing"
    assert not repo.conn.in_transaction and repo.conn.execute("SELECT 3 AS x").fetchone()["x"] == 3


def test_a_session_that_listened_listens_again(repos):
    from graph_scale_dynamics.db.connection import WORK_CHANNEL
    repo, other = repos
    repo.conn.listen_for_work()
    _end_the_session_of(repo, other)
    repo.get_flag("paused", "0")
    other.conn.execute(f"NOTIFY {WORK_CHANNEL}, 'work'")
    assert repo.conn.wait_for_work(timeout=5.0), "the work channel is heard on the new session"


def test_a_write_is_not_run_twice_on_the_new_session(repos):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError, safe_to_repeat
    repo, other = repos
    repo.set_flag("written", "0")
    _end_the_session_of(repo, other)
    with pytest.raises(DatabaseOperationalError) as raised:
        repo.conn.execute("UPDATE control SET value='1' WHERE key='written'")
    assert raised.value.transient, "its caller redoes it, or for a claim leaves it to the lease"
    assert raised.value.outcome_unknown, "it may have committed: no retry loop below the caller redoes it"
    assert repo.conn.reconnects == 1 and repo.get_flag("written", "?") == "0", "not run on the new session"
    assert safe_to_repeat("  select 1") and safe_to_repeat("SHOW lock_timeout") and safe_to_repeat("BEGIN")
    for write in ("WITH picked AS (SELECT 1) UPDATE jobs SET status='leased'", "INSERT INTO control VALUES ('a','b')",
                  "DELETE FROM control", "COMMIT", "ROLLBACK", "/* a comment */ SELECT 1"):
        assert not safe_to_repeat(write), write


def test_a_session_lock_is_taken_again_on_the_new_session(repos):
    repo, other = repos
    assert repo.acquire_service_lock("gsd-test:fleet")
    _end_the_session_of(repo, other)
    repo.get_flag("paused", "0")
    assert repo.conn.reconnects == 1
    assert not other.acquire_service_lock("gsd-test:fleet"), "a second fleet could take the lock and start"
    holder = other.service_lock_holder("gsd-test:fleet")
    assert holder and int(holder["pid"]) == int(repo.conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])
    repo.release_service_lock("gsd-test:fleet")
    _end_the_session_of(repo, other)
    repo.get_flag("paused", "0")
    assert other.acquire_service_lock("gsd-test:fleet"), "a lock let go is not taken again"
    other.release_service_lock("gsd-test:fleet")


def test_a_session_lock_another_process_took_stops_this_one(repos):
    from graph_scale_dynamics.db.connection import SessionLockLost
    repo, other = repos
    assert repo.acquire_service_lock("gsd-test:fleet")
    _end_the_session_of(repo, other)
    assert other.acquire_service_lock("gsd-test:fleet"), "the second fleet takes it while the first is away"
    with pytest.raises(SessionLockLost, match="another process holds that lock now") as raised:
        try:
            repo.get_flag("paused", "0")
        except Exception:
            pytest.fail("the lost lock was swallowed by an except Exception")
    assert not isinstance(raised.value, Exception)
    assert repo.get_flag("paused", "0") == "0", "the session stays for the process's own cleanup, said once"
    other.release_service_lock("gsd-test:fleet")


VERSION = "lost-reply-v1"


def _leased_job(repo, job="job-lost-reply", campaign="camp-lost-reply", candidate="cand-lost-reply"):
    from graph_scale_dynamics.domain.model import content_hash
    spec = {"mode": "bounded", "ladder": [256], "analysis_version": VERSION}
    law = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
           "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
    if not repo.conn.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign,)).fetchone():
        repo.insert_campaign(campaign, spec, content_hash(spec))
        repo.insert_candidate(candidate, campaign, law, "metropolis", 1, "DISCOVERY_ACTIVE")
    repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=candidate, kind="simulate", stage="PILOT", n=256,
                    seed=7, replicate=0, spec={"candidate_spec": law}, priority=10, sealed=False,
                    requested_by="631-test")
    claimed = repo.claim_job("executor-lost", ("simulate",))
    assert claimed and claimed["job_id"] == job
    return claimed


class _ReplyLost:
    def __init__(self, repo, name):
        self._repo, self._name, self.calls = repo, name, 0

    def __getattr__(self, attr):
        real = getattr(self._repo, attr)
        if attr != self._name:
            return real

        def landed_then_lost(*args, **kwargs):
            from graph_scale_dynamics.db.connection import DatabaseOperationalError
            self.calls += 1
            assert real(*args, **kwargs)
            raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)
        return landed_then_lost


def test_a_simulation_commit_whose_reply_was_lost_is_read_from_its_row(repos):
    from graph_scale_dynamics.db.write_outcome import job_commit_landed
    from graph_scale_dynamics.services.worker import main as worker
    from tests.support.doubles import NullLog
    repo, _other = repos
    job = _leased_job(repo)
    owner, generation, digest = "executor-lost", int(job["lease_generation"]), "a" * 64
    assert job_commit_landed(repo, job["job_id"], owner, generation, digest) is None, "leased: not landed yet"
    lost = _ReplyLost(repo, "commit_job_result")
    committed, _ = worker.commit_completed_result(lost, NullLog(), job=job, owner=owner, generation=generation,
                                                  digest=digest, size=64, meta={"schema": "raw-simulation-envelope-v1"})
    assert committed is True and lost.calls == 1, "a commit that landed is not made again and read as fenced"
    assert repo.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()["status"] == "done"
    assert job_commit_landed(repo, job["job_id"], owner, generation + 1, "b" * 64) is False


def test_the_analyzer_s_claim_and_commit_outlive_a_lost_session(repos):
    from graph_scale_dynamics.db.write_outcome import analysis_claim_state
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.services.analyzer import main as analyzer
    from tests.support.doubles import NullLog
    repo, other = repos
    job = _leased_job(repo)
    assert repo.commit_job_result(job_id=job["job_id"], owner="executor-lost",
                                  lease_generation=int(job["lease_generation"]), digest="c" * 64, size=64,
                                  media_type="application/json", meta={}, analysis_version=ANALYSIS_VERSION)
    claimed = repo.claim_analysis_job("analyzer-lost", ANALYSIS_VERSION)
    assert claimed and claimed["result_artifact"] == "c" * 64
    claim = analyzer.ClaimThroughAnOutage()
    _end_the_session_of(repo, other)
    assert claim.renew(repo, NullLog(), claimed, "analyzer-lost", 0.0) is None, "the renewal met the lost session"
    assert claim.renew(repo, NullLog(), claimed, "analyzer-lost", 5.0) is True, "and found the new one"
    state = analysis_claim_state(repo, claimed["campaign_id"], claimed["result_artifact"], ANALYSIS_VERSION,
                                 "analyzer-lost", claimed["analysis_claim_token"])
    assert state["held"] and not state["measured"]
    lost = _ReplyLost(repo, "commit_analysis_result")
    writes = analyzer.ClaimWrites(lost, NullLog(), claimed, "analyzer-lost", "attempt-lost")
    _end_the_session_of(repo, other)
    assert writes.commit(curves_digest="d" * 64, curves_size=2, producer_job=claimed["job_id"],
                         analysis_id="analysis-lost", candidate_id=claimed["candidate_id"], n=256, seed=7,
                         metrics={"d_s": {"d_s": 2.0}}) is True
    assert lost.calls == 1, "a commit that landed is not made again"
    state = analysis_claim_state(repo, claimed["campaign_id"], claimed["result_artifact"], ANALYSIS_VERSION,
                                 "analyzer-lost", claimed["analysis_claim_token"])
    assert state["status"] == "done" and state["measured"] and not state["held"]


def test_a_claim_whose_reply_was_lost_is_given_back_unspent(repos):
    from graph_scale_dynamics.db.write_outcome import give_back_unseen_claims
    repo, _other = repos
    job = _leased_job(repo, job="job-unseen")
    assert repo.conn.execute("SELECT attempts FROM jobs WHERE job_id='job-unseen'").fetchone()["attempts"] == 1
    assert give_back_unseen_claims(repo, "executor-lost") == {"jobs": 1, "analyses": 0}
    row = repo.conn.execute("SELECT status,attempts,lease_owner FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
    assert (row["status"], row["attempts"], row["lease_owner"]) == ("queued", 0, None)
    assert give_back_unseen_claims(repo, "executor-lost") == {"jobs": 0, "analyses": 0}
