from __future__ import annotations

import threading
import time

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.services.controller.main import decision_relevant

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "rest-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def test_noise_does_not_end_the_rest_and_a_finished_job_does(isolated_postgres_schema):
    dsn = isolated_postgres_schema.dsn
    init_db(dsn)
    waiter, writer = Repo(dsn), Repo(dsn)
    try:
        writer.insert_campaign("camp", SPEC, content_hash(SPEC))
        writer.insert_candidate("law-1", "camp", LAW, "metropolis", 1, "BASE_BLOCK_RUNNING")
        waiter.wait_for_work(0.01)

        def noise():
            for i in range(10):
                writer.set_flag("compute_active_slots", str(i))
                writer.insert_job(job_id=f"noise-{i}", campaign_id="camp", candidate_id="law-1",
                                  kind="simulate", stage="base", n=64, seed=i, replicate=0,
                                  spec={"candidate_spec": LAW}, priority=10, sealed=False,
                                  requested_by="rest-contract")
                time.sleep(0.05)

        thread = threading.Thread(target=noise)
        started = time.monotonic()
        thread.start()
        woke = waiter.wait_for_work(1.5, decision_relevant)
        thread.join()
        assert woke is False and time.monotonic() - started >= 1.4, (
            "a control write or a queued job ended the controller's rest")

        def finish():
            time.sleep(0.2)
            writer.conn.execute("UPDATE jobs SET status='done' WHERE job_id='noise-0'")

        thread = threading.Thread(target=finish)
        started = time.monotonic()
        thread.start()
        woke = waiter.wait_for_work(5.0, decision_relevant)
        thread.join()
        assert woke is True and time.monotonic() - started < 3.0, "a finished job must wake it"
    finally:
        waiter.close()
        writer.close()


def test_a_backlog_is_one_wake_not_one_wake_per_notification(isolated_postgres_schema):
    dsn = isolated_postgres_schema.dsn
    init_db(dsn)
    waiter, writer = Repo(dsn), Repo(dsn)
    try:
        waiter.wait_for_work(0.01)
        for i in range(50):
            writer.conn.execute(f"SELECT pg_notify('gsd_work', '{{\"n\": {i}}}')")
        time.sleep(0.2)
        waiter.conn.execute("SELECT 1").fetchone()
        assert waiter.wait_for_work(0.5) is True
        started = time.monotonic()
        assert waiter.wait_for_work(0.5) is False, "a second wait replayed the backlog"
        assert time.monotonic() - started >= 0.45
    finally:
        waiter.close()
        writer.close()
