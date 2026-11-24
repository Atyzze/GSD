from __future__ import annotations

import signal

import pytest

from graph_scale_dynamics.scheduling import worker_count
from graph_scale_dynamics.services.api import campaign_manager


class _Repo:
    def __init__(self, flags=None):
        self.flags = dict(flags or {})
        self.writes, self.events = [], []

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = str(value)

    def _write(self, sql, params=()):
        self.writes.append((sql, tuple(params)))
        return 1

    def emit(self, topic, payload):
        self.events.append((topic, payload))


class _Proc:
    def __init__(self, pid):
        self.pid, self.code = pid, None

    def poll(self):
        return self.code


def _record(slot, pid):
    return {"module": "graph_scale_dynamics.services.executor.main",
            "extra": ("--total-slots", "16", "--max-analyzers", "2", "--slot", str(slot)),
            "group": "compute", "proc": _Proc(pid), "suspended": False, "disabled": False}


@pytest.fixture
def fleet(monkeypatch):
    sent = []
    monkeypatch.setattr(worker_count.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    services = [_record(slot, 100 + slot) for slot in range(5)]
    launched, spawned = [], []

    def launch(record):
        record["proc"], record["suspended"] = _Proc(200 + worker_count.executor_slot(record)), False
        launched.append(worker_count.executor_slot(record))

    def spawn_executor(slot, *, start=True):
        record = _record(slot, 300 + slot)
        record["suspended"] = not start
        record["proc"] = record["proc"] if start else None
        services.append(record)
        spawned.append((slot, start))

    state = {"spawned": 5}

    said: list[str] = []

    def tick(repo, now, paused=False):
        before = len(said)
        target = worker_count.tick(repo, services=services, state=state, most=16, paused=paused, launch=launch,
                                   spawn=spawn_executor, now=now, grace=10.0, say=said.append)
        return target, (said[-1] if len(said) > before else None)

    return {"services": services, "sent": sent, "launched": launched, "spawned": spawned,
            "state": state, "tick": tick}


def _slot(fleet, slot):
    return next(r for r in fleet["services"] if worker_count.executor_slot(r) == slot)


def test_without_a_count_the_tick_changes_nothing(fleet):
    repo = _Repo()
    assert fleet["tick"](repo, 0.0) == (None, None)
    assert fleet["sent"] == [] and repo.events == [] and "compute_active_slots" not in repo.flags


def test_a_lower_count_stops_the_slots_above_it_at_once_and_holds_them(fleet):
    repo = _Repo({worker_count.FLAG: "3", "compute_active_slots": "5"})
    target, line = fleet["tick"](repo, 0.0)
    assert target == 3 and "stopped [3, 4]" in line
    assert fleet["sent"] == [(103, signal.SIGTERM), (104, signal.SIGTERM)]
    assert all(_slot(fleet, s)["held"] and _slot(fleet, s)["suspended"] for s in (3, 4))
    assert not any(_slot(fleet, s).get("held") for s in (0, 1, 2))
    assert repo.flags["compute_active_slots"] == "3" and repo.flags["compute_total_slots"] == "3"
    assert repo.events[-1][0] == "worker_count" and repo.events[-1][1]["stopped"] == [3, 4]
    assert fleet["tick"](repo, 1.0) == (3, None)
    assert len(fleet["sent"]) == 2


def test_a_stopped_slot_is_reaped_and_one_that_will_not_save_is_killed_after_the_grace(fleet):
    repo = _Repo({worker_count.FLAG: "3"})
    fleet["tick"](repo, 0.0)
    _slot(fleet, 4)["proc"].code = 0
    fleet["tick"](repo, 1.0)
    assert _slot(fleet, 4)["proc"] is None
    assert ("DELETE FROM service_heartbeats WHERE service=?", ("executor-4-104",)) in repo.writes
    assert (103, signal.SIGKILL) not in fleet["sent"]
    fleet["tick"](repo, 11.0)
    assert (103, signal.SIGKILL) in fleet["sent"]


def test_a_higher_count_restarts_held_slots_once_they_have_exited_and_starts_new_ones(fleet):
    repo = _Repo({worker_count.FLAG: "3"})
    fleet["tick"](repo, 0.0)
    _slot(fleet, 4)["proc"].code = 0
    repo.flags[worker_count.FLAG] = "7"
    target, line = fleet["tick"](repo, 1.0)
    assert target == 7
    assert fleet["launched"] == [4]
    assert fleet["spawned"] == [(5, True), (6, True)] and fleet["state"]["spawned"] == 7
    assert _slot(fleet, 3)["held"], "a slot still saving is not started twice"
    _slot(fleet, 3)["proc"].code = 0
    fleet["tick"](repo, 2.0)
    assert fleet["launched"] == [4, 3] and not _slot(fleet, 3)["held"]
    assert repo.flags["compute_active_slots"] == "7"


def test_handing_back_to_the_ramp_restarts_every_held_slot(fleet):
    repo = _Repo({worker_count.FLAG: "2"})
    fleet["tick"](repo, 0.0)
    for slot in (2, 3, 4):
        _slot(fleet, slot)["proc"].code = 0
    repo.flags[worker_count.FLAG] = ""
    fleet["tick"](repo, 1.0)
    target, line = fleet["tick"](repo, 2.0)
    assert target is None
    assert sorted(fleet["launched"]) == [2, 3, 4]
    assert not any(r.get("held") for r in fleet["services"])


def test_while_paused_a_count_marks_slots_and_starts_nothing(fleet):
    repo = _Repo({worker_count.FLAG: "2", "compute_active_slots": "0"})
    for record in fleet["services"]:
        record["proc"], record["suspended"] = None, True
    fleet["tick"](repo, 0.0, paused=True)
    assert fleet["sent"] == [] and repo.flags["compute_active_slots"] == "0"
    assert all(_slot(fleet, s)["held"] for s in (2, 3, 4))
    repo.flags[worker_count.FLAG] = "6"
    fleet["tick"](repo, 1.0, paused=True)
    assert fleet["launched"] == []
    assert fleet["spawned"] == [(5, False)]
    assert not any(r.get("held") for r in fleet["services"])
    assert all(r["suspended"] for r in fleet["services"])


def test_a_count_is_kept_within_one_and_the_most_the_machine_holds():
    assert worker_count.wanted("40", 16) == 16 and worker_count.wanted("0", 16) == 1
    assert worker_count.wanted("", 16) is None and worker_count.wanted("x", 16) is None
    for value in (0, 17, "x", True, 2.5, -1):
        assert worker_count.asked(value, 16)[1] is not None, value
    assert worker_count.asked(4, 16) == (4, None) and worker_count.asked("4", 16) == (4, None)
    assert worker_count.asked(None, 16) == (None, None) and worker_count.asked("auto", 16) == (None, None)


def test_the_plan_stops_from_the_top_and_waits_for_a_slot_still_saving():
    steps = worker_count.plan(5, live={0, 1, 2, 3, 4, 5, 6, 7}, held=set(), exiting=set(), spawned=8)
    assert steps == {"stop": [5, 6, 7], "restart": [], "spawn": [], "waiting": []}
    steps = worker_count.plan(10, live={0, 1, 2, 3, 4}, held={5, 6, 7}, exiting={7}, spawned=8)
    assert steps == {"stop": [], "restart": [5, 6], "spawn": [8, 9], "waiting": [7]}
    steps = worker_count.plan(None, live={0}, held={1, 2}, exiting={2}, spawned=3)
    assert steps == {"stop": [], "restart": [1], "spawn": [], "waiting": [2]}


def test_the_manage_route_sets_and_clears_the_count_and_refuses_what_the_machine_cannot_hold(monkeypatch):
    monkeypatch.setattr(campaign_manager, "_mark_stale", lambda: None)
    repo = _Repo({worker_count.MOST_FLAG: "12", "compute_active_slots": "8", "compute_total_slots": "8"})
    payload, code = campaign_manager.handle(repo, {"action": "fleet_workers", "workers": 5})
    assert code == 200 and payload["target"] == 5 and payload["most"] == 12
    assert repo.flags[worker_count.FLAG] == "5"
    payload, code = campaign_manager.handle(repo, {"action": "fleet_workers", "workers": 13})
    assert code == 400 and "between 1 and 12" in payload["error"] and repo.flags[worker_count.FLAG] == "5"
    payload, code = campaign_manager.handle(repo, {"action": "fleet_workers", "workers": None})
    assert code == 200 and payload["target"] is None and repo.flags[worker_count.FLAG] == ""
    assert "the ramp chooses" in payload["reading"]


def test_the_most_a_folder_offers_is_one_a_hardware_thread_within_its_database_and_never_below_its_ceiling():
    assert worker_count.most_slots(16, 32, {}) == 32
    assert worker_count.most_slots(16, 32, {"GSD_MAX_WORKERS": "24"}) == 24
    assert worker_count.most_slots(40, 32, {"GSD_MAX_WORKERS": "40"}) == 40
    assert worker_count.resumed(_Repo({worker_count.FLAG: "6"}), 16, 12) == 6
    assert worker_count.resumed(_Repo(), 16, 12) == 12

