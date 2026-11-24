from __future__ import annotations

import time

from graph_scale_dynamics.db.repo import Repo, heartbeat_interval_seconds
from graph_scale_dynamics.services.api import fleet_snapshots as api_fleet_snapshots
from graph_scale_dynamics.services.api import overview as api_overview

BUSY = dict(paused=False, resources={"cpu_percent": 47.4}, active_slots=16, scheduler_slots=16,
            runnable_simulations=2669, runnable_analyses=278, blocked_simulations=0, deferred_analyses=0,
            memory_deferred_analyses=0, stranded_nonterminal=0, nonterminal_observed=182, governor={})


def test_a_growth_study_s_one_worker_a_core_is_named_and_is_not_a_warning():
    state, severity, explanation = api_fleet_snapshots._capacity_diagnosis(**BUSY, one_worker_per_core={"physical": 16,
                                                                                       "logical": 32})
    assert (state, severity) == ("ONE_WORKER_PER_CORE", "normal")
    assert "16 slots on 16 physical cores" in explanation and "32 threads (47.4%)" in explanation
    assert api_fleet_snapshots._capacity_diagnosis(**BUSY)[0] == "EXECUTOR_CONCURRENCY_LIMITED", "slots short of the cores, as before"
    saturated = dict(BUSY, resources={"cpu_percent": 95.0})
    assert api_fleet_snapshots._capacity_diagnosis(**saturated, one_worker_per_core={"physical": 16, "logical": 32})[0] == (
        "CPU_LIMITED"), "a saturated host is named as such whatever the ceiling"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, rows=None):
        self.rows, self.sql = rows or [], []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return _Rows(self.rows)


class _Repo:
    def __init__(self, rows):
        self.conn = _Conn(rows)


def test_simulations_run_are_counted_for_each_campaign():
    api_fleet_snapshots._EXECUTION_COUNT_CACHE.update(at=0.0, value={})
    repo = _Repo([{"campaign_id": "1", "executions": 2730}, {"campaign_id": "2", "executions": 30}])
    counts = api_fleet_snapshots._execution_counts(repo)
    assert counts == {"1": {"simulation_executions": 2730}, "2": {"simulation_executions": 30}}
    assert "GROUP BY j.campaign_id" in repo.conn.sql[0]
    api_fleet_snapshots._EXECUTION_COUNT_CACHE.update(at=0.0, value={})


def _bare_repo(interval: float) -> Repo:
    repo = object.__new__(Repo)
    repo.conn = _Conn()
    repo._heartbeat_interval_seconds = interval
    repo._next_heartbeat_at = 0.0
    repo.publish_runtime_imports = lambda service, names=None: False
    return repo


def test_a_paced_heartbeat_is_written_on_its_own_interval():
    repo = _bare_repo(32.0)
    assert repo.heartbeat("api", {}) is True
    assert repo.heartbeat("api", {}) is False, "the rate limit holds for a loop that calls every tick"
    assert repo.heartbeat("api", {}, paced=True) is True, "the heartbeat thread keeps its own 15 s"
    assert len(repo.conn.sql) == 2


def test_the_heartbeat_thread_writes_paced(monkeypatch):
    from graph_scale_dynamics.observability import heartbeat
    calls = []

    class FakeRepo:
        def __init__(self, db_path):
            pass

        def heartbeat(self, service, payload, paced=False):
            calls.append((service, paced))

        def close(self):
            pass

    monkeypatch.setattr(heartbeat, "Repo", FakeRepo)
    heartbeat.start_heartbeat_thread("api", "unused", interval_seconds=0.01)
    deadline = time.monotonic() + 2.0
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls[:2] == [("api", True), ("api", True)]


def test_a_service_is_alive_within_two_of_its_heartbeat_s_intervals():
    assert api_overview.ALIVE_WITHIN_SECONDS >= 2 * heartbeat_interval_seconds()
    assert api_overview.ALIVE_WITHIN_SECONDS > 45.0, "the api's 45 s beat of 2026-10-01 is alive"
