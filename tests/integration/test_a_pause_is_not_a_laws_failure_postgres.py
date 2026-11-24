from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
LAW = "pause".ljust(64, "0")
JOB = "pause-job".ljust(64, "j")


@pytest.fixture
def folder(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "EXTENDING")
        repo.insert_job(job_id=JOB, campaign_id=campaign_id, candidate_id=LAW, kind="simulate", stage="rung_n4096",
                        n=4096, seed=0, replicate=0, spec={}, priority=4096, requested_by="test", sealed=False)
    return isolated_postgres_schema.dsn, campaign_id


def _lease(repo, number: int) -> str:
    attempt = f"attempt-{number}".ljust(64, "a")
    repo.conn.execute("UPDATE jobs SET status='leased',lease_owner='w1' WHERE job_id=?", (JOB,))
    repo.record_attempt(attempt, JOB, number, "w1")
    return attempt


def _class(repo, attempt: str) -> str | None:
    return repo.conn.execute("SELECT error_class FROM attempts WHERE attempt_id=?", (attempt,)).fetchone()["error_class"]


def test_three_pauses_and_one_real_failure_do_not_stop_a_job(folder):
    from graph_scale_dynamics.db.repo import FENCE_PAUSED_CLASS, Repo
    from graph_scale_dynamics.observability.child_diagnostics import same_reason_exhausted
    dsn, _campaign = folder
    with Repo(dsn) as repo:
        for number in (1, 2, 3):
            attempt = _lease(repo, number)
            repo.operator_pause_cancel_active_work(reason="user cancelled by PAUSE")
            assert _class(repo, attempt) == FENCE_PAUSED_CLASS
            repo.close_attempt(attempt, -15, 0, 1.0, "child terminated by SIGTERM", error_class="signal:SIGTERM")
            assert _class(repo, attempt) == FENCE_PAUSED_CLASS
        attempt = _lease(repo, 4)
        repo.close_attempt(attempt, -9, 0, 1.0, "out of memory", error_class="oom_killed")
        classes = repo.job_failure_classes(JOB)
        assert classes == [FENCE_PAUSED_CLASS] * 3 + ["oom_killed"]
        assert same_reason_exhausted(classes) is None, "a law is never stopped for the fleet's pauses"


def test_a_failure_of_the_child_s_own_before_the_fence_keeps_its_class(folder):
    from graph_scale_dynamics.db.repo import FENCE_PAUSED_CLASS, Repo
    dsn, _campaign = folder
    with Repo(dsn) as repo:
        for number, (code, cls) in enumerate([(1, "exception:ValueError"), (-9, "oom_killed"),
                                              (-11, "signal:SIGSEGV"), (None, None)], start=1):
            attempt = _lease(repo, number)
            repo.operator_pause_cancel_active_work(reason="user cancelled by PAUSE")
            repo.close_attempt(attempt, code if code is not None else -1, 0, 1.0,
                               None if cls is None else "the child's own failure", error_class=cls)
            assert _class(repo, attempt) == (cls or FENCE_PAUSED_CLASS), (number, cls)


def test_a_campaign_pause_names_its_own_interruption(folder):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_CAMPAIGN_PAUSED, INTERRUPTED_ATTEMPT_CLASSES
    from graph_scale_dynamics.operations.campaign_control import fence_campaign_leases
    dsn, campaign_id = folder
    with Repo(dsn) as repo:
        attempt = _lease(repo, 1)
        assert fence_campaign_leases(repo, campaign_id, reason="the campaign paused") == 1
        assert _class(repo, attempt) == ATTEMPT_CLASS_CAMPAIGN_PAUSED in INTERRUPTED_ATTEMPT_CLASSES


def test_the_pauses_closed_before_are_named_at_a_start_and_nothing_else_is(folder):
    from graph_scale_dynamics.db.repo import FENCE_PAUSED_CLASS, Repo
    from graph_scale_dynamics.operations import failure_repair
    dsn, _campaign = folder
    with Repo(dsn) as repo:
        fenced, own, done = _lease(repo, 1), _lease(repo, 2), _lease(repo, 3)
        repo.conn.execute("UPDATE attempts SET finished_utc='2026-10-20T00:00:00Z',exit_code=-15,"
                          "error='user cancelled by PAUSE' WHERE attempt_id=?", (fenced,))
        repo.close_attempt(own, 1, 0, 1.0, "a failure of its own", error_class="exception:ValueError")
        repo.close_attempt(done, 0, 0, 1.0, None)
        assert failure_repair.reclassify_pause_fences(repo) == 1
        assert _class(repo, fenced) == FENCE_PAUSED_CLASS
        assert _class(repo, own) == "exception:ValueError" and _class(repo, done) is None
        assert failure_repair.reclassify_pause_fences(repo) == 0
        assert failure_repair.render({"pauses_named": 1})[0].startswith("repair: 1 attempt(s) a pause closed")
