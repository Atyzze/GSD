from __future__ import annotations

from graph_scale_dynamics.scheduling import memory as M
from graph_scale_dynamics.scheduling.memory import MemorySnapshot

GIB = 1 << 30
HOST = 92 * GIB


def lease(ident, reserved, current, n=4194304, started="2026-09-24T20:00:00Z"):
    return {"kind": "simulation", "id": ident, "n": n, "reserved_bytes": int(reserved * GIB),
            "observed_bytes": int(current * GIB), "current_bytes": int(current * GIB), "started_utc": started}


def _five20(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    big = [lease("deep-1", 17.0, 4.6), lease("deep-2", 17.0, 4.6)]
    return M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=34 * GIB), observations=big)


def test_the_large_pool_keeps_the_growth_and_the_small_pool_borrows_it(monkeypatch):
    got = _five20(monkeypatch)
    assert got["headroom_bytes"] < GIB, "as on 520: the large children's growth fills the headroom"
    assert abs(got["lent_bytes"] - 24.8 * GIB) < 0.01 * GIB
    assert got["small_pool_headroom_bytes"] == 24 * GIB, "available less the floor: the floor is never lent"
    assert got["small_pool_limit_bytes"] == int(0.92 * GIB)


def test_small_childrens_own_growth_is_still_counted_against_the_small_pool(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    rows = [lease("deep-1", 17.0, 4.6), lease("small-1", 0.5, 0.1, n=65536)]
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=34 * GIB), observations=rows)
    small_growth = int(0.5 * GIB) - int(0.1 * GIB)
    assert got["small_pool_headroom_bytes"] == 24 * GIB - small_growth


def test_nothing_is_lent_under_the_floor(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    rows = [lease("deep-1", 17.0, 4.6)]
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=9 * GIB), observations=rows)
    assert got["small_pool_headroom_bytes"] == 0 and got["headroom_bytes"] == 0


def test_when_a_large_child_takes_back_what_was_lent_the_shed_rule_returns_it(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    rows = [lease("deep-1", 17.0, 16.0, started="2026-09-24T20:00:00Z")] + [
        lease(f"small-{i}", 0.9, 0.9, n=65536, started=f"2026-09-24T20:5{6 + i}:00Z") for i in range(4)]
    snapshot = MemorySnapshot(total=HOST, available=int(7.5 * GIB))
    now = M._utc_seconds("2026-09-24T21:00:00Z")
    shed = {r["id"]: M.memory_shed_reason(None, {"job_id": r["id"]}, snapshot=snapshot, observations=rows, now=now)
            for r in rows}
    assert shed["deep-1"] is None
    assert sum(v is not None for v in shed.values()) == 3, shed
    assert shed["small-0"] is None, "the oldest small child has lost the most per byte: kept last"
