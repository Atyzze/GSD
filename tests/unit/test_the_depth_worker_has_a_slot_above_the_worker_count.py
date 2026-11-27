from __future__ import annotations

import signal

from graph_scale_dynamics.scheduling import work_groups, worker_count
from graph_scale_dynamics.services.executor.main import _role
from graph_scale_dynamics.services.worker import main as W


class _Repo:
    def __init__(self, flags=None):
        self.flags = dict(flags or {})
        self.events = []

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = str(value)

    def _write(self, sql, params=()):
        return 1

    def emit(self, topic, payload):
        self.events.append((topic, payload))


class _Proc:
    def __init__(self, pid):
        self.pid, self.code = pid, None

    def poll(self):
        return self.code


def _record(slot):
    return {"module": "graph_scale_dynamics.services.executor.main", "extra": ("--slot", str(slot)),
            "group": "compute", "proc": _Proc(100 + slot), "suspended": False, "disabled": False}


def test_the_depth_slot_starts_once_there_is_depth_work_and_no_worker_count_stops_it(monkeypatch):
    sent = []
    monkeypatch.setattr(worker_count.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    services = [_record(slot) for slot in range(4)]
    spawned, said = [], []

    def spawn(slot, *, start=True):
        services.append(_record(slot))
        spawned.append((slot, start))

    state = {"spawned": 4}
    repo = _Repo()
    tick = lambda now, paused=False: worker_count.tick(repo, services=services, state=state, most=16, paused=paused,
                                                       launch=lambda r: None, spawn=spawn, now=now, grace=10.0,
                                                       say=said.append)
    tick(0.0)
    assert spawned == [], "no depth work, no depth slot"
    repo.flags[worker_count.DEPTH_ORDER_FLAG] = '{"campaign": "13", "laws": ["a"]}'
    tick(1.0)
    assert spawned == [(16, True)] and "slot 16 started above the worker count" in said[-1]
    assert repo.events[-1] == ("depth_slot", {"contract": worker_count.CONTRACT, "slot": 16, "most": 16})
    repo.flags[worker_count.FLAG] = "2"
    tick(2.0)
    assert sorted(pid for pid, sig in sent if sig == signal.SIGTERM) == [102, 103], (
        "a lower worker count stops the fleet's slots above it, never the depth slot")
    assert spawned == [(16, True)], "it starts once"


def test_the_depth_slot_has_its_own_role_and_the_others_keep_theirs():
    snapshot = {"analysis_slots": 1, "simulation_slots": 2, "paused": False}
    assert [_role(snapshot, slot, 16) for slot in (0, 1, 2, 3, 16)] == [
        "analysis", "simulation", "simulation", None, worker_count.DEPTH_ROLE]
    assert _role(dict(snapshot, paused=True), 16, 16) is None


def test_the_fleet_s_slots_leave_the_depth_campaign_and_hold_the_dex_to_its_level_while_it_is_checked():
    rows = [{"campaign_id": "11", "design_kind": "focus", "focus_part": "N", "leased": 3, "queued": 4, "behind": 0,
             "workers_target": None},
            {"campaign_id": "13", "design_kind": "focus", "focus_part": "D", "leased": 0, "queued": 2, "behind": 0,
             "workers_target": 1},
            {"campaign_id": "15", "design_kind": "seed", "leased": 9, "queued": 250, "behind": 0,
             "workers_target": None}]
    found = work_groups.ordered(rows)
    assert [tier for tier, _rows in found] == [work_groups.ZONE_TIER, work_groups.DEX_TIER]
    assert all(row["campaign_id"] != "13" for _tier, tier_rows in found for row in tier_rows)
    checked = W.offers(rows, {}, None)
    assert [o[2] for o in checked] == [{}, {"order": work_groups.BY_LAW, "max_n": 4096}, {"order": work_groups.BY_LAW},
                                       {}]
    assert checked[-1][0] == ("11", "15")
    held = W.offers(rows, {}, 4096)
    assert [o[2] for o in held] == [{}, {"order": work_groups.BY_LAW, "max_n": 4096}, {}], (
        "while a dex is checked its laws run only to the level they are verified at")
    assert held[-1][0] == ("11",), "the last offer leaves out the depth campaign and the Dex campaign"
    assert work_groups.verifying(_Repo({work_groups.VERIFYING_FLAG: "4096"})) == 4096
    assert work_groups.verifying(_Repo({work_groups.VERIFYING_FLAG: ""})) is None


def test_the_forecast_says_how_many_seeds_fit_at_once_how_long_each_size_takes_and_where_the_push_ends():
    from graph_scale_dynamics.operations import push
    gib = 1024 ** 3
    found = [{"n": 16384, "peak_bytes": int(0.27 * gib), "seconds": 112.0},
             {"n": 65536, "peak_bytes": int(1.08 * gib), "seconds": 765.0}]
    f = push.forecast(found, [16384, 65536, 262144, 1048576, 4194304], {"reach_bytes": 125 * gib, "host": True},
                      seeds=3, now=0.0)
    first, second, third = f["ahead"]
    assert first["n"] == 262144 and first["at_once"] == 3 and first["fits"]
    assert abs(first["seconds"] - 765.0 * 4 ** first["time_growth"]) < 2 and first["time_growth"] > 1.3, (
        "a run's time grows as the law's own two deepest sizes say")
    assert first["hours"] == round(first["seconds"] / 3600, 2), "three seeds at once: one run's time for the size"
    assert second["n"] == 1048576 and second["at_once"] == 3 and second["hours"] == round(second["seconds"] / 3600, 2)
    assert third["n"] == 4194304 and third["at_once"] == 1 and third["hours"] == round(3 * third["seconds"] / 3600, 2), (
        "only one seed fits: the three run one after another")
    assert f["final"]["n"] == 4194304 and f["final"]["one_at_a_time_from"] == 4194304 and f["host"]
    assert f["final"]["hours"] == round(first["hours"] + second["hours"] + third["hours"], 1)
    assert "its last size N=4,194,304, one seed at a time from N=4,194,304, about" in f["words"]
    half = push.forecast(found, [16384, 65536, 262144, 1048576, 4194304], {"reach_bytes": 46 * gib}, seeds=3, now=0.0)
    assert half["limit"]["n"] == 4194304 and half["final"]["n"] == 1048576 and not half["host"]
    assert [r["at_once"] for r in half["ahead"] if r["fits"]] == [3, 2], "half the host: two seeds at once at 1,048,576"
