from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.operations import compute_ecology as E
from graph_scale_dynamics.operations import scratch_relief as R
from graph_scale_dynamics.scheduling import memory as M
from graph_scale_dynamics.scheduling import memory_hold as H
from graph_scale_dynamics.scheduling.memory import MemorySnapshot

GB = 10 ** 9
GIB = 1 << 30
HOST = 98_746_621_952
SCRATCH = 49_373_310_976
DEEP = 1_048_576
HOLD_ASK = 23_915_715_524
NOW = 1_794_215_000.0

OPERATOR_LEASES = [
    ("simulation", "deep-a", DEEP, 6.6, 1.6, 3.25, 7.8),
    ("simulation", "deep-b", DEEP, 6.6, 1.6, 3.25, 7.8),
    ("simulation", "mid-c", 65536, 1.0, 0.5, 0.9, 1.3),
    ("simulation", "mid-d", 65536, 1.0, 0.5, 0.9, 1.3),
    ("analysis", "probe-e", 262144, 2.2, 0.9, 2.1, 2.5),
]


class _Cursor:
    def __init__(self, rows, rowcount=0):
        self.rows, self.rowcount = rows, rowcount

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Folder:
    def __init__(self, leases=(), *, deferred=0):
        self.leases, self.deferred = list(leases), deferred
        self.control: dict[str, str] = {}
        self.events: list[tuple[str, dict]] = []
        self.written: list[str] = []

    def hold(self, row: dict | None) -> None:
        self.control.pop(H.HOLD_KEY, None) if row is None else self.control.update({H.HOLD_KEY: json.dumps(row)})

    def _peaks(self, kind: str, n: int) -> list[dict]:
        for k, _id, rung, _reserved, _held, typical, peak in self.leases:
            if (k, rung) == (kind, n):
                p95 = int(peak * GB / M.EXPECTED_PEAK_SLACK)
                return [{"pss": int(typical * GB), "rss": 0}] * 10 + [{"pss": p95, "rss": 0}] * 10
        return []

    def _reserved(self, kind: str) -> int:
        return sum(int(r * GB) for k, _i, _n, r, _h, _t, _p in self.leases if k == kind)

    def execute(self, sql, args=()):
        if "ORDER BY a.finished_utc DESC" in sql:
            return _Cursor(self._peaks("analysis" if "analysis_attempts" in sql else "simulation", int(args[0])))
        if sql.startswith("SELECT 'simulation' AS kind"):
            return _Cursor([{"kind": k, "id": i, "n": n, "reserved": int(r * GB), "started_utc": None,
                             "detail_json": json.dumps({"pss": int(h * GB), "pss_now": int(h * GB)})}
                            for k, i, n, r, h, _t, _p in self.leases])
        if "sim_bytes" in sql:
            return _Cursor([{"sim_bytes": 0, "sim_count": 0, "ana_bytes": 0, "ana_count": 0}])
        if "SUM(memory_reservation_bytes)" in sql:
            return _Cursor([{"simulation": self._reserved("simulation"), "analysis": self._reserved("analysis")}])
        if sql.startswith("SELECT COUNT(*) c FROM jobs"):
            return _Cursor([{"c": self.deferred}])
        if sql.startswith("SELECT value FROM control WHERE key"):
            return _Cursor([{"value": self.control[args[0]]}] if args[0] in self.control else [])
        if sql.startswith("INSERT INTO control"):
            if args[0] in self.control:
                return _Cursor([], 0)
            self.control[args[0]] = args[1]
            return _Cursor([], 1)
        if sql.startswith("UPDATE control SET value=? WHERE key=? AND value=?"):
            if self.control.get(args[1]) != args[2]:
                return _Cursor([], 0)
            self.control[args[1]] = args[0]
            return _Cursor([], 1)
        if sql.startswith("INSERT INTO events"):
            self.events.append((args[0], json.loads(args[1])))
            return _Cursor([], 1)
        if sql.startswith("SELECT j.status,j.memory_reservation_bytes"):
            return _Cursor([{"status": "queued", "memory_reservation_bytes": None,
                             "next_attempt_utc": None, "campaign_status": "active", "workers_target": None,
                             "state": "EXTENDING"}])
        if sql.startswith("UPDATE"):
            self.written.append(sql.split(" SET ")[0])
            return _Cursor([], 1)
        raise AssertionError(f"a statement this double does not know: {sql[:90]}")


class _Repo:
    def __init__(self, conn):
        self.conn = conn

    def acquire_blocking_lock(self, name):
        assert name == M.MEMORY_CLAIM_LOCK

    def release_service_lock(self, name):
        assert name == M.MEMORY_CLAIM_LOCK


def _holding(job_id="seed-1m", ask=HOLD_ASK, since=NOW - 600):
    return {"contract": H.MEMORY_HOLD_CONTRACT, "state": "holding", "job_id": job_id, "campaign_id": "8", "n": DEEP,
            "requested_bytes": ask, "since_epoch": since, "since_utc": H._stamp(since),
            "until_epoch": since + H.HOLD_MAX_SECONDS, "run_outs": 0, "rev": 1}


@pytest.fixture
def operators_host(monkeypatch):
    monkeypatch.setattr(M, "system_memory", lambda: MemorySnapshot(total=HOST, available=int(43.1 * GIB)))
    monkeypatch.setattr(M, "memory_pressure_snapshot",
                        lambda: {"available": False, "some_avg10": None, "full_avg10": None})
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    M.reset_prediction_caches()
    yield _Folder(OPERATOR_LEASES)
    M.reset_prediction_caches()


def _claim(conn, kind, ask, **identity):
    lease = (dict(campaign_id="8", artifact="a" * 64, analysis_version="analysis-5.1.0", owner="executor-1-1",
                  claim_token="t") if kind == "analysis" else dict(owner="executor-2-1", lease_generation=1))
    return M.locked_admission(_Repo(conn), kind=kind, reservation_bytes=int(ask), **{**lease, **identity})


def test_an_analysis_is_admitted_beside_a_held_seed_on_the_operators_numbers(operators_host):
    conn = operators_host
    head = M.admission_headroom(conn, snapshot=M.system_memory(), quantiles=M.admission_quantiles(conn))
    assert {k: round(head[k] / GB, 1) for k in ("reserved_bytes", "held_bytes", "unrealised_bytes",
                                                 "spike_room_bytes", "headroom_bytes")} == {
        "reserved_bytes": 17.4, "held_bytes": 5.1, "unrealised_bytes": 14.4, "spike_room_bytes": 9.1,
        "headroom_bytes": 21.1}, "the host's status at 08:41Z"
    conn.hold(_holding(since=time.time() - 600))
    ask = M._deterministic_fallback_peak_bytes({}, DEEP, "analysis")
    assert round(ask / GB, 2) == 4.17
    analysis = _claim(conn, "analysis", ask)
    assert analysis["within_budget"] and analysis["held_bytes"] == 0, "748 refused it: budget 14.6 GB, proposed 21.6"
    assert round(analysis["budget"] / GB, 1) == 38.5 and conn.written[-1] == "UPDATE analysis_queue"
    too_big = _claim(conn, "analysis", head["headroom_bytes"] + 1)
    assert too_big["refusal"] == "transient_memory_floor", "an analysis's own reservation still counts"
    deep = _claim(conn, "simulation", 6.6 * GB, job_id="another-1m")
    assert deep["refusal"] == "transient_memory_floor" and round(deep["budget"] / GB, 1) == 14.6, \
        "a simulation still leaves the held room free"
    held = _claim(conn, "simulation", HOLD_ASK, job_id="seed-1m")
    assert held["held_bytes"] == 0 and round(held["budget"] / GB, 1) == 38.5, "the held seed counts its room once"
    small = _claim(conn, "simulation", 0.5 * GB, job_id="small")
    assert small["within_budget"] and small["pool"] == "small"


def _scratch(used):
    return {"total_bytes": SCRATCH, "used_bytes": used, "free_bytes": SCRATCH - used, "fraction": used / SCRATCH}


def test_the_relief_moves_toward_the_low_mark_while_admission_is_short(monkeypatch, tmp_path):
    now = {"used": int(0.524 * SCRATCH)}
    calls = []

    def usage(path):
        return _scratch(now["used"])

    def spill(repo, store, *, target_fraction, budget_bytes, progress=None):
        calls.append((target_fraction, budget_bytes))
        now["used"] = max(int(target_fraction * SCRATCH) - 1, now["used"] - budget_bytes)
        return {"moved_bytes": budget_bytes, "after": usage(None), "moved": {}, "refused": {}}

    monkeypatch.setattr(R, "usage", usage)
    monkeypatch.setattr(R, "spill", spill)
    monkeypatch.setattr(R, "prune_dead_logs", lambda path: {"removed": 0, "bytes": 0})
    monkeypatch.setattr(R, "disk_free", lambda store: 500 * GB)
    store = SimpleNamespace(volatile_root=tmp_path, root=tmp_path, staging_backend={"tmpfs": True})
    assert round(usage(None)["fraction"], 3) == 0.524 and round(now["used"] / GB, 1) == 25.9
    assert R.relieve(None, store)["spilled"] is None and not calls, "748: at 52% nothing moves, whatever the host"
    why = "a hold for a 1,048,576 seed asking 22.3 GiB"
    first = R.relieve(None, store, pressed=why)
    assert calls == [(R.LOW_WATER, R.TICK_BUDGET_BYTES)] and first["relieving"] and first["pressed"] == why, \
        "a tick's budget moves, toward the low mark"
    assert R.doing(first) == ("moved 4.0 GiB to disk this tick, toward 40%, because admission is short "
                              "(a hold for a 1,048,576 seed asking 22.3 GiB)")
    second = R.relieve(None, store, relieving=first["relieving"], pressed=why)
    assert len(calls) == 2 and not second["relieving"] and usage(None)["fraction"] < R.LOW_WATER
    assert R.relieve(None, store, pressed=why)["spilled"] is None, "under the low mark nothing more moves"
    now["used"] = int(0.524 * SCRATCH)
    assert R.relieve(None, SimpleNamespace(volatile_root=tmp_path, root=tmp_path, staging_backend={}),
                     pressed=why)["spilled"] is None, "a scratch on disk frees no RAM by moving"
    assert R.relieve(None, store, pressed=None)["spilled"] is None and len(calls) == 2, "no shortage, no move"


def test_the_shortage_is_a_hold_or_a_seed_refused_for_memory_in_the_last_five_minutes():
    conn = _Folder()
    assert R.shortage(conn, now=NOW) == {"why": None, "deferred_at": None}
    conn.hold(_holding(since=NOW - 60))
    assert R.shortage(conn, now=NOW)["why"] == "a hold for a 1,048,576 seed asking 22.3 GiB"
    conn.hold(_holding(since=NOW - H.HOLD_MAX_SECONDS - 1))
    conn.deferred = 25
    refused = R.shortage(conn, now=NOW)
    assert refused == {"why": "seeds refused for memory 0 s ago", "deferred_at": NOW}
    conn.deferred = 0
    assert R.shortage(conn, refused["deferred_at"], now=NOW + 120)["why"] == "seeds refused for memory 120 s ago"
    assert R.shortage(conn, refused["deferred_at"], now=NOW + R.SHORT_SECONDS + 1)["why"] is None


def _published(conn, store, seen, *, now=NOW):
    conn.control[H.SCRATCH_KEY] = json.dumps({"at_epoch": now, "movable_bytes": R.movable_bytes(
        SimpleNamespace(conn=None), store, seen), "used_bytes": seen["used_bytes"],
        "total_bytes": seen["total_bytes"], "fraction": round(seen["fraction"], 3), "doing": "moves nothing"})


def test_a_hold_starts_only_when_its_seed_can_fit_once_the_fleet_drains(monkeypatch, tmp_path):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    monkeypatch.setattr(R, "disk_free", lambda store: 500 * GB)
    monkeypatch.setattr(R, "spillable_bytes", lambda repo, store: 19_000_000_000)
    store = SimpleNamespace(volatile_root=tmp_path, root=tmp_path, staging_backend={"tmpfs": True})
    conn = _Folder()
    seen = {"total_bytes": SCRATCH, "used_bytes": 19_762_327_440, "fraction": 19_762_327_440 / SCRATCH}
    _published(conn, store, seen)
    bundle = H.reach(conn, snapshot=MemorySnapshot(total=HOST, available=30_231_543_808), observations=[], now=NOW)
    assert bundle["movable_bytes"] == 19_762_327_440 - int(R.LOW_WATER * SCRATCH) == 13_003_050
    assert bundle["reach_bytes"] == 30_231_543_808 + 0 + 13_003_050 - 10 * GIB == 19_507_128_618
    assert round(bundle["reach_bytes"] / GIB, 1) == 18.2 and round(HOLD_ASK / GIB, 1) == 22.3
    assert H.start(conn, job_id="seed-1m", campaign_id="8", n=DEEP, requested_bytes=HOLD_ASK,
                   reach=lambda: bundle, now=NOW) is None, "748 started this hold, ran it out and rested 8 hours"
    row = H.read(conn)
    assert row["state"] == "unheld" and not conn.events
    assert row["unfit"]["reach_bytes"] == 19_507_128_618 and row["unfit"]["requested_bytes"] == HOLD_ASK
    room = E.memory_room(conn, {"available_bytes": 30_231_543_808, "held_bytes": 0, "floor_bytes": 10 * GIB,
                                "headroom_bytes": 19_494_125_568}, now=NOW + 5)
    assert ("A 1,048,576 seed asks 22.3 GiB; with the RAM scratch spilled and nothing running, this host gives at "
            "most 18.2 GiB") in E.room_reading(room)
    assert "smaller seeds run meanwhile" in E.room_reading(room)
    smaller = H.start(conn, job_id="seed-15g", campaign_id="8", n=DEEP, requested_bytes=15_887_257_077,
                      reach=lambda: bundle, now=NOW + 10)
    assert smaller["new"] and "unfit" not in smaller, "a smaller seed that fits is held for"


def test_a_hold_that_can_no_longer_fit_ends_and_is_taken_up_again_when_it_can():
    conn = _Folder()
    conn.hold(_holding(since=NOW - 600))
    operator = {"reach_bytes": int(43.1 * GIB) + int(5.1 * GB) + int(6.1 * GB) - 10 * GIB}
    kept = H.start(conn, job_id="seed-1m", campaign_id="8", n=DEEP, requested_bytes=HOLD_ASK,
                   reach=lambda: operator, now=NOW)
    assert kept["state"] == "holding", "at 08:41Z the 23.9 GB seed could fit: its hold stands"
    shrunk = {"reach_bytes": 19_507_128_618, "available_bytes": 30_231_543_808, "children_bytes": 0,
              "movable_bytes": 13_003_050, "floor_bytes": 10 * GIB}
    assert H.start(conn, job_id="seed-1m", campaign_id="8", n=DEEP, requested_bytes=HOLD_ASK,
                   reach=lambda: shrunk, now=NOW + 5) is None
    row = H.read(conn)
    assert (row["state"], row["ended"], row["run_outs"]) == ("ended", "cannot fit", 0), "no rest: it did not run out"
    assert conn.events[-1][1]["why"] == "cannot fit" and conn.events[-1][1]["reach_bytes"] == 19_507_128_618
    assert H.held_bytes(conn, job_id="other", now=NOW + 6) == 0, "the fleet has its room back at once"
    back = H.start(conn, job_id="seed-1m", campaign_id="8", n=DEEP, requested_bytes=HOLD_ASK,
                   reach=lambda: operator, now=NOW + 60)
    assert back["state"] == "holding" and back["until_epoch"] == NOW - 600 + H.HOLD_MAX_SECONDS and "unfit" not in back
    assert [e[1].get("resumed") for e in conn.events if e[0] == "memory_hold_started"] == [True]


def test_the_status_names_the_hold_its_room_and_the_scratch(operators_host):
    conn = operators_host
    admission = M.admission_headroom(conn, snapshot=M.system_memory(), quantiles=M.admission_quantiles(conn))
    conn.hold(_holding(since=NOW - 600))
    used = int(0.524 * SCRATCH)
    conn.control[H.SCRATCH_KEY] = json.dumps({
        "at_epoch": NOW - 2, "used_bytes": used, "total_bytes": SCRATCH, "fraction": 0.524,
        "movable_bytes": used - int(R.LOW_WATER * SCRATCH),
        "doing": R.doing({"usage": _scratch(used), "tmpfs": True, "pressed": "a hold for a 1,048,576 seed asking "
                          "22.3 GiB", "spilled": {"moved_bytes": R.TICK_BUDGET_BYTES}})})
    room = E.memory_room(conn, admission, now=NOW)
    assert room["hold"]["left_to_simulations_bytes"] == 0 and room["hold"]["analyses_held_back"] is False
    assert room["hold"]["until_utc"] == H._stamp(NOW - 600 + H.HOLD_MAX_SECONDS)
    state, _, text = E.memory_floor_verdict(admission, waiting=1415 + 60, deferred=25, idle=7, slots=12, room=room)
    assert state == "SEEDS_LARGER_THAN_HEADROOM"
    assert "less any room held for a lane's seed" not in text, "what 748 said, without a number"
    for needle in ("the headroom less the 22.3 GiB held for a 1,048,576 seed",
                   f"held since {H._stamp(NOW - 600)} until {H._stamp(NOW - 600 + H.HOLD_MAX_SECONDS)}",
                   "0.0 GiB of the headroom is left to other simulations", "no analysis is held back",
                   "The RAM scratch holds 24.1 GiB of 46.0 GiB (52%)",
                   "the relief moved 4.0 GiB to disk this tick, toward 40%, because admission is short"):
        assert needle in text, (needle, text)
    from graph_scale_dynamics.services.api.fleet_snapshots import _capacity_diagnosis
    live = _capacity_diagnosis(paused=False, resources={"cpu_percent": 30.0, "memory_load_percent": 53.0},
                               active_slots=5, scheduler_slots=12, runnable_simulations=1415, runnable_analyses=60,
                               blocked_simulations=0, deferred_analyses=0, memory_deferred_analyses=0,
                               stranded_nonterminal=0, nonterminal_observed=900, governor={}, admission=admission,
                               deferred_simulations=25, memory_reservation_percent=45.0, room=room)
    assert live == (state, "normal", text)
