from __future__ import annotations

import threading
import time

import pytest

from graph_scale_dynamics.services.api import campaign_manager as cm


class _Repo:
    def __init__(self, target="postgresql://fake/one", status="active"):
        self.db_target = target
        self.status = status
        self.closed = 0

    def all_campaigns(self):
        return [{"campaign_id": "c1", "status": self.status}]

    def close(self):
        self.closed += 1


@pytest.fixture
def scans(monkeypatch):
    monkeypatch.setattr(cm, "_AGGREGATES", {})
    gate = threading.Event()
    gate.set()
    calls = []

    def slow_scan(repo):
        calls.append(threading.current_thread().name)
        assert gate.wait(10.0)
        return {"generation": len(calls)}

    monkeypatch.setattr(cm, "_slow_scan", slow_scan)
    monkeypatch.setattr(cm, "overview", lambda repo, cache_root=None, *, slow, campaigns: {"slow": slow})
    import graph_scale_dynamics.db.repo as repo_module
    monkeypatch.setattr(repo_module, "Repo", lambda target: _Repo(target))
    import graph_scale_dynamics.operations.subprocesses as subprocesses
    monkeypatch.setattr(subprocesses, "yield_this_thread", lambda *a, **k: True)
    return calls, gate


def _wait_idle(target="postgresql://fake/one", seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not cm._AGGREGATES.get(target, {}).get("refreshing"):
            return
        time.sleep(0.01)
    raise AssertionError("the background rebuild did not finish")


def test_a_due_rebuild_runs_once_in_the_background_while_polls_get_the_last_copy(scans):
    calls, gate = scans
    repo = _Repo()
    first = cm.cached_overview(repo)
    assert first["slow"] == {"generation": 1} and calls == [threading.current_thread().name], (
        "a cold cache is read in the request, once")

    gate.clear()
    cm._mark_stale()
    answers = []
    for _ in range(5):
        started = time.monotonic()
        answers.append(cm.cached_overview(repo))
        assert time.monotonic() - started < 0.5, "a poll waited for the rebuild"
    assert all(answer["slow"] == {"generation": 1} for answer in answers)
    assert all(answer["aggregates"]["refreshing"] for answer in answers)
    assert len(calls) == 2 and calls[1] == "gsd-campaigns-overview", (
        f"one rebuild however many polls arrive, off the request thread: {calls}")

    gate.set()
    _wait_idle()
    fresh = cm.cached_overview(repo)
    assert fresh["slow"] == {"generation": 2}
    assert fresh["aggregates"]["refreshing"] is False and fresh["aggregates"]["error"] is None


def test_a_failed_rebuild_keeps_the_last_copy_and_says_why(scans, monkeypatch):
    calls, _gate = scans
    repo = _Repo()
    cm.cached_overview(repo)
    import graph_scale_dynamics.db.repo as repo_module

    def refuse(target):
        raise RuntimeError("database busy")

    monkeypatch.setattr(repo_module, "Repo", refuse)
    cm._mark_stale()
    cm.cached_overview(repo)
    _wait_idle()
    after = cm.cached_overview(repo)
    assert after["slow"] == {"generation": 1}
    assert "database busy" in (after["aggregates"]["error"] or "")


def test_each_database_has_its_own_copy(scans):
    calls, _gate = scans
    one = cm.cached_overview(_Repo("postgresql://fake/one"))
    two = cm.cached_overview(_Repo("postgresql://fake/two"))
    assert one["slow"] == {"generation": 1} and two["slow"] == {"generation": 2}


def test_a_settled_folder_keeps_its_aggregates(scans, monkeypatch):
    calls, _gate = scans
    repo = _Repo(status="completed")
    cm.cached_overview(repo)
    clock = time.monotonic() + cm._ACTIVE_TTL + 1.0
    monkeypatch.setattr(cm.time, "monotonic", lambda: clock)
    cm.cached_overview(repo)
    assert len(calls) == 1, "nothing active, nothing can move: no rebuild after four ticks"


def test_the_api_start_builds_the_counts_so_the_first_view_does_not(scans):
    calls, _gate = scans
    assert cm.warm_aggregates("postgresql://fake/one") is True
    assert cm.warm_aggregates("postgresql://fake/one") is False, "one build, however often it is asked"
    _wait_idle()
    first = cm.cached_overview(_Repo())
    assert calls[0] == "gsd-campaigns-overview", calls
    assert first["slow"] == {"generation": 1}, "the first view is served the warm copy"
    _wait_idle()
