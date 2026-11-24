from __future__ import annotations

import os

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.services import db_watchdog
from graph_scale_dynamics.services.worker import main as worker
from tests.support.doubles import NullLog

JOB = {"job_id": "job-away", "attempt_number": 1, "lease_generation": 7, "candidate_id": "candidate",
       "campaign_id": "campaign", "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
       "n": 8, "seed": 11}


def _away(*_args, **_kwargs):
    raise DatabaseOperationalError("PostgreSQL operation failed [57P01]: terminating connection", transient=True,
                                   sqlstate="57P01")


class _Session:
    execute = staticmethod(_away)


class _AwayRepo:
    def __init__(self, away: int):
        self.away, self.renewals, self.released, self.closed = away, 0, [], []
        self.conn = _Session()

    def record_attempt(self, *args):
        pass

    def renew_lease(self, *args, **kwargs):
        self.renewals += 1
        if self.renewals <= self.away:
            _away()
        return True

    def get_flag(self, *args, **kwargs):
        if self.renewals <= self.away:
            _away()
        return "0"

    def preempt_reason(self, job):
        return None

    def heartbeat(self, *args):
        pass

    def settle_memory_reservation(self, *args):
        return False

    def release_job(self, job_id, owner, generation, defer_seconds=None):
        self.released.append(job_id)
        return True

    def close_attempt(self, *args, error_class=None):
        self.closed.append(error_class)


class _Child:
    def __init__(self):
        self.pid, self.returncode, self.stopped = os.getpid(), None, False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def harness(monkeypatch, tmp_path):
    child, calls = _Child(), []

    def stop(staging, grace=None):
        calls.append("saved")
        child.returncode = 75

    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(worker, "stop_current_child", stop)
    monkeypatch.setattr(worker, "terminate_current_child", lambda: calls.append("killed"))
    monkeypatch.setattr(worker, "lane_yield_reason", lambda repo, job: None)
    monkeypatch.setattr(worker, "memory_shed_reason", lambda *a, **k: None)
    monkeypatch.setattr(worker, "evidence_floor_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(worker, "SIM_LEASE_RENEW_SECONDS", 0.05)
    monkeypatch.setattr(worker, "DATABASE_RETRY_SECONDS", 0.02)
    return child, calls, BlobStore(tmp_path / "blobs")


def test_a_database_away_until_the_lease_would_lapse_saves_the_child_and_never_kills_it(harness, monkeypatch):
    child, calls, blobs = harness
    monkeypatch.setattr(worker, "SIM_LEASE_SECONDS", 1.0)
    monkeypatch.setattr(worker, "LEASE_SAVE_MARGIN_SECONDS", 0.5)
    repo = _AwayRepo(away=10_000)
    with pytest.raises(DatabaseOperationalError, match="the child saved its state"):
        worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert calls == ["saved"], "the child saves when the lease would lapse, and is never killed unsaved"
    assert repo.renewals >= 2, "the renewal is asked again while the database is away"


def test_a_database_back_before_the_lease_lapses_costs_the_chain_nothing(harness, monkeypatch):
    child, calls, blobs = harness
    monkeypatch.setattr(worker, "SIM_LEASE_SECONDS", 60.0)
    import time
    repo = _AwayRepo(away=3)
    asked_at = time.monotonic() + 1.5
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB),
                   stop_requested=lambda: time.monotonic() >= asked_at)
    assert repo.renewals > 3, "renewed once the database was back"
    assert calls == ["saved"], "the chain ran on through the outage and stopped only when asked, saving"
    assert repo.released == ["job-away"] and repo.closed == [worker.ATTEMPT_CLASS_FLEET_SHUTDOWN]


def test_the_watchdog_s_recovery_never_stops_the_fleet(monkeypatch, tmp_path):
    said = []
    monkeypatch.setattr(db_watchdog, "probe", lambda *a: {"connect_ok": True})
    dog = db_watchdog.Watchdog(socket_dir=tmp_path, postgres_dir=tmp_path, connect=None,
                               helper=None, owns_instance=True, log=said.append, emit=_away)
    dog.failing_since = 0.0
    assert dog.tick(100.0) == "recovered"
    assert any("recovery not recorded" in line for line in said)
    assert dog.failing_since is None


def test_the_supervisor_s_loop_waits_for_the_database_rather_than_stopping(monkeypatch, capsys):

    import main

    slept: list[float] = []
    monkeypatch.setattr(main.time, "sleep", slept.append)
    waits: dict[str, float] = {}
    for _ in range(3):
        main._wait_for_the_database(DatabaseOperationalError("server closed the connection", transient=True), waits)
    assert slept == [2.0, 2.0, 2.0]
    assert capsys.readouterr().out.count("the fleet waits for it") == 1, "said once in 30 seconds, not every turn"


class _LostUnderAWrite:
    in_transaction = False

    def __init__(self):
        self.calls = 0

    def execute(self, sql, args=()):
        self.calls += 1
        raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)

    def rollback_if_open(self):
        return False


def test_a_claim_or_write_that_may_have_committed_is_not_made_again(monkeypatch):
    from graph_scale_dynamics.db import repo as R
    monkeypatch.setattr(R.time, "sleep", lambda _s: None)
    repo = R.Repo.__new__(R.Repo)
    repo.conn = _LostUnderAWrite()
    with pytest.raises(DatabaseOperationalError) as raised:
        repo.claim_job("w1", ("simulate",))
    assert raised.value.outcome_unknown and repo.conn.calls == 1, "the claim was run again"
    repo.conn = _LostUnderAWrite()
    with pytest.raises(DatabaseOperationalError):
        repo.set_flag("written", "1")
    assert repo.conn.calls == 1, "the write was run again"


from graph_scale_dynamics.services.analyzer import main as analyzer  # noqa: E402

ANALYSIS = {"result_artifact": "art-away", "analysis_claim_token": "claim-away", "campaign_id": "campaign",
            "candidate_id": "candidate", "n": 4096, "seed": 3, "job_id": "job-away", "spec": {},
            "memory_reservation_bytes": 1, "analysis_attempt_number": 1}


class _Outage:
    def __init__(self, away_from: float, back_at: float):
        import time
        self.start, self.away_from, self.back_at = time.monotonic(), away_from, back_at

    def away(self) -> bool:
        import time
        elapsed = time.monotonic() - self.start
        return self.away_from <= elapsed < self.back_at

    def check(self, *, outcome_unknown: bool = False):
        if self.away():
            raise DatabaseOperationalError("PostgreSQL operation failed [57P01]: terminating connection",
                                           transient=True, sqlstate="57P01", outcome_unknown=outcome_unknown)


class _AnalysisRepo:
    def __init__(self, outage: _Outage):
        self.outage, self.renewals, self.commits, self.closed, self.released = outage, [], [], [], []
        outer = self

        class _Conn:
            def execute(self, *args, **kwargs):
                outer.outage.check()
                raise AssertionError("no query reaches the database in this test")

        self.conn = _Conn()

    def record_analysis_attempt(self, *args, **kwargs):
        pass

    def get_flag(self, *args, **kwargs):
        self.outage.check()
        return "0"

    def renew_analysis_claim(self, *args, **kwargs):
        self.renewals.append(self.outage.away())
        self.outage.check(outcome_unknown=True)
        return True

    def settle_analysis_memory_reservation(self, *args, **kwargs):
        self.outage.check(outcome_unknown=True)
        return False

    def heartbeat(self, *args, **kwargs):
        return False

    def publish_runtime_imports(self, *args, **kwargs):
        return False

    def commit_analysis_result(self, **kwargs):
        self.commits.append(self.outage.away())
        self.outage.check()
        return True

    def close_analysis_attempt(self, attempt_id, **kwargs):
        self.outage.check()
        self.closed.append(kwargs)

    def release_analysis_claim(self, *args, **kwargs):
        self.released.append(args)
        return True

    def artifact_retention(self, *args):
        return None


class _AnalysisChild:
    def __init__(self, args, seconds: float):
        import time
        self.pid, self.returncode, self.args = os.getpid(), None, args
        self.done_at = time.monotonic() + seconds

    def poll(self):
        import json
        import time
        from pathlib import Path
        if self.returncode is None and time.monotonic() >= self.done_at:
            Path(self.args[-2]).write_text(json.dumps({"metrics": {"d_s": {"d_s": 2.0}}, "curves": {}}))
            Path(self.args[-1]).write_text(json.dumps({"status": "success"}))
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def analysis_harness(monkeypatch, tmp_path):
    killed: list[str] = []
    made: list[_AnalysisChild] = []

    def popen(args, seconds, **_kw):
        made.append(_AnalysisChild(args, seconds))
        return made[-1]

    monkeypatch.setattr(analyzer, "terminate_current_child", lambda: killed.append("killed"))
    monkeypatch.setattr(analyzer, "analysis_stop_bytes", lambda *a: (1 << 50, "ceiling"))
    monkeypatch.setattr(analyzer, "analysis_stop_reason", lambda repo, campaign_id: None)
    monkeypatch.setattr(analyzer, "_child_memory_bytes", lambda pid: {"rss_bytes": 1, "uss_bytes": 1,
                                                                      "pss_bytes": 1, "vms_bytes": 1})
    monkeypatch.setattr(analyzer, "evict_analyzed_raw_body", lambda *a: {})
    monkeypatch.setattr(analyzer, "ANALYSIS_LEASE_RENEW_SECONDS", 0.05)
    monkeypatch.setattr(analyzer, "DATABASE_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(analyzer, "TICK_SECONDS", 0.05)
    return popen, killed, BlobStore(tmp_path / "blobs")


def test_the_analyzer_keeps_its_child_through_a_database_outage(analysis_harness, monkeypatch):
    popen, killed, blobs = analysis_harness
    monkeypatch.setattr(analyzer.subprocess, "Popen", lambda args, **kw: popen(args, 1.6))
    repo = _AnalysisRepo(_Outage(0.2, 1.2))
    assert analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", dict(ANALYSIS)) is True
    assert killed == [], "the child ran on through the outage"
    assert sum(repo.renewals) >= 2, "the claim's renewal was asked again while the database was away"
    assert repo.renewals[-1] is False, "and renewed once it was back"
    assert repo.commits == [False] and repo.closed[-1].get("error") is None, "the measurement committed once"


def test_a_result_finished_while_the_database_is_away_is_committed_when_it_is_back(analysis_harness, monkeypatch):
    popen, killed, blobs = analysis_harness
    monkeypatch.setattr(analyzer.subprocess, "Popen", lambda args, **kw: popen(args, 0.3))
    repo = _AnalysisRepo(_Outage(0.25, 1.4))
    assert analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", dict(ANALYSIS)) is True
    assert killed == [] and repo.commits[0] is True and repo.commits[-1] is False, (
        "the commit was asked again until the database was back, not lost with the staging")
    assert len(repo.closed) == 1 and repo.closed[0].get("error") is None


def test_an_analysis_commit_whose_reply_was_lost_is_read_again_not_made_again(analysis_harness, monkeypatch):
    popen, killed, blobs = analysis_harness
    monkeypatch.setattr(analyzer.subprocess, "Popen", lambda args, **kw: popen(args, 0.1))
    repo = _AnalysisRepo(_Outage(10.0, 20.0))
    landed = {"status": "done", "held": False, "measured": True}

    def commit(**kwargs):
        repo.commits.append("landed, reply lost")
        raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)

    repo.commit_analysis_result = commit
    monkeypatch.setattr(analyzer, "analysis_claim_state", lambda *a: dict(landed))
    assert analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", dict(ANALYSIS)) is True
    assert repo.commits == ["landed, reply lost"], "the commit was made again"
    assert repo.closed[-1].get("error_class") is None, "closed as the success it was"
    repo.commits.clear()
    landed.update(status="leased", held=True, measured=False)
    calls = iter([DatabaseOperationalError("lost", transient=True, outcome_unknown=True), True])

    def commit_once_lost(**kwargs):
        repo.commits.append("asked")
        answer = next(calls)
        if isinstance(answer, Exception):
            raise answer
        return answer

    repo.commit_analysis_result = commit_once_lost
    assert analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", dict(ANALYSIS)) is True
    assert repo.commits == ["asked", "asked"], "a commit the row says did not land is made again"


class _CommitRepo:
    backend = "postgresql"

    def __init__(self, landed):
        self.commits, self.renewals, self.landed = 0, 0, landed

    def commit_job_result(self, **kwargs):
        self.commits += 1
        raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)

    def renew_lease(self, *args, **kwargs):
        self.renewals += 1
        return False


def test_a_simulation_commit_whose_reply_was_lost_is_read_again_not_made_again(monkeypatch):
    monkeypatch.setattr(worker.time, "sleep", lambda _s: None)
    monkeypatch.setattr(worker, "job_commit_landed", lambda repo, *a: repo.landed)
    repo = _CommitRepo(landed=True)
    committed, _ = worker.commit_completed_result(repo, NullLog(), job=dict(JOB), owner="executor-1", generation=7,
                                                  digest="d" * 64, size=1, meta={})
    assert committed is True and repo.commits == 1, "the commit was made again"
    assert repo.renewals == 0, "a lease the commit may have ended is not renewed and read as lost"
    lost = _CommitRepo(landed=False)
    assert worker.commit_completed_result(lost, NullLog(), job=dict(JOB), owner="executor-1", generation=7,
                                          digest="d" * 64, size=1, meta={})[0] is False
    assert lost.commits == 1


def test_an_executor_gives_back_a_claim_whose_reply_was_lost(monkeypatch, tmp_path):
    from graph_scale_dynamics.services.executor import main as executor
    asked, given = [], []

    class _Repo:
        def __init__(self, *args):
            self.turns = 0

        def scheduler_snapshot(self):
            self.turns += 1
            if self.turns == 1:
                raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)
            asked.append("snapshot")
            return None

        def wait_for_work(self, *args):
            executor._STOP_REQUESTED.set()

        def close(self):
            pass

    monkeypatch.setattr(executor, "Repo", _Repo)
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)
    monkeypatch.setattr(executor.signal, "signal", lambda *a: None)
    monkeypatch.setattr(executor, "give_back_unseen_claims",
                        lambda repo, owner: given.append(owner) or {"jobs": 1, "analyses": 0})
    executor.main(["--db", "x", "--blobs", str(tmp_path / "blobs"), "--campaign", "c", "--var", str(tmp_path),
                   "--slot", "0", "--total-slots", "1", "--max-analyzers", "1"])
    assert len(given) == 1 and given[0].startswith("executor-0-") and asked == ["snapshot"], (
        "read again and given back on the next turn, once")


def test_a_heartbeat_the_database_cannot_take_ends_no_analysis(analysis_harness, monkeypatch):
    popen, killed, blobs = analysis_harness
    monkeypatch.setattr(analyzer.subprocess, "Popen", lambda args, **kw: popen(args, 0.6))
    repo = _AnalysisRepo(_Outage(10.0, 20.0))
    beats = []

    def heartbeat(*args, **kwargs):
        beats.append(args)
        raise DatabaseOperationalError("server closed the connection", transient=True, outcome_unknown=True)

    repo.heartbeat = heartbeat
    assert analyzer.run_analysis_job(repo, blobs, NullLog(), "executor-1", dict(ANALYSIS)) is True
    assert beats and killed == [] and repo.commits == [False]
