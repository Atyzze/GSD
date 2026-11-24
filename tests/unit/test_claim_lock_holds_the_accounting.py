from __future__ import annotations

import pytest

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.scheduling import memory as M
from graph_scale_dynamics.scheduling.memory import MemorySnapshot

GIB = 1 << 30
HOST = 92 * GIB
HISTORY_SCAN = "ORDER BY a.finished_utc DESC"


def lease(kind, ident, n, reserved, held=None):
    return {"kind": kind, "id": ident, "n": n, "reserved_bytes": int(reserved * GIB),
            "observed_bytes": None if held is None else int(held * GIB),
            "current_bytes": None if held is None else int(held * GIB), "started_utc": None}


class _Cursor:
    def __init__(self, rows, rowcount=0):
        self.rows, self.rowcount = rows, rowcount

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Fleet:
    def __init__(self, leases, peaks):
        self.leases, self.peaks = leases, peaks
        self.locked = False
        self.log: list[tuple[str, bool]] = []

    def execute(self, sql, args=()):
        self.log.append((sql, self.locked))
        if HISTORY_SCAN in sql:
            return _Cursor([{"pss": int(p), "rss": int(p)} for p in self.peaks])
        if sql.startswith("SELECT 'simulation' AS kind"):
            return _Cursor([{"kind": r["kind"], "id": r["id"], "n": r["n"], "reserved": r["reserved_bytes"],
                             "detail_json": None, "started_utc": None} for r in self.leases])
        if "sim_bytes" in sql:
            return _Cursor([{"sim_bytes": 0, "sim_count": 0, "ana_bytes": 0, "ana_count": 0}])
        if "SUM(memory_reservation_bytes)" in sql:
            return _Cursor([{"simulation": sum(r["reserved_bytes"] for r in self.leases), "analysis": 0}])
        if sql.startswith("UPDATE jobs SET memory_reservation_bytes"):
            return _Cursor([], rowcount=1)
        if sql.startswith("SELECT value FROM control WHERE key"):
            return _Cursor([])
        raise AssertionError(f"admission issued a statement this double does not know: {sql[:80]}")


class _Repo:
    def __init__(self, conn):
        self.conn = conn

    def acquire_blocking_lock(self, name):
        assert name == M.MEMORY_CLAIM_LOCK
        self.conn.locked = True

    def release_service_lock(self, name):
        assert name == M.MEMORY_CLAIM_LOCK
        self.conn.locked = False


@pytest.fixture
def roomy_host(monkeypatch):
    monkeypatch.setattr(M, "system_memory", lambda: MemorySnapshot(total=HOST, available=60 * GIB))
    monkeypatch.setattr(M, "memory_pressure_snapshot",
                        lambda: {"available": False, "some_avg10": None, "full_avg10": None})
    M.reset_prediction_caches()
    yield
    M.reset_prediction_caches()


def test_the_claim_lock_is_held_for_the_accounting_alone(roomy_host):
    leases = [lease("simulation", "claimed", 64, 0.0), lease("simulation", "deep", 65536, 2.0, 1.0),
              lease("analysis", "probe", 256, 0.5)]
    conn = _Fleet(leases, [100 << 20] * 12)
    got = M.locked_admission(_Repo(conn), kind="simulation", reservation_bytes=150 << 20,
                             job_id="claimed", owner="executor-1-1", lease_generation=1)
    assert got["recorded"] is True, got
    under = [sql for sql, locked in conn.log if locked]
    before = [sql for sql, locked in conn.log if not locked]
    assert under, "the accounting ran under the lock"
    assert not [sql for sql in under if HISTORY_SCAN in sql], "a history scan ran under the claim lock"
    assert sum(HISTORY_SCAN in sql for sql in before) == 3, "one read per rung, before the lock"
    assert under[-1].startswith("UPDATE jobs SET memory_reservation_bytes"), "the write closes the section"


def test_admission_reads_the_same_budget_from_prefetched_quantiles(roomy_host):
    rows = [lease("simulation", "deep", 65536, 6.6, 3.0), lease("simulation", "young", 65536, 6.6)]
    conn = _Fleet(rows, [4.4 * GIB] * 10 + [5.4 * GIB] * 10)
    mem = MemorySnapshot(total=HOST, available=38 * GIB)
    reading_under_the_lock = M.admission_headroom(conn, snapshot=mem, observations=rows)
    M.reset_prediction_caches()
    quantiles = M.admission_quantiles(conn, observations=rows)
    conn.log.clear()
    prefetched = M.admission_headroom(conn, snapshot=mem, observations=rows, quantiles=quantiles)
    assert conn.log == [], "with its quantiles and its leases in hand, admission reads nothing"
    assert prefetched == reading_under_the_lock


def test_a_rung_the_prefetch_did_not_see_counts_its_reservation():
    row = lease("simulation", "new-rung", 262144, 3.0, 1.0)
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=38 * GIB),
                               observations=[row], quantiles={})
    assert got["unrealised_bytes"] == 3 * GIB - 1 * GIB


def test_one_read_serves_a_rungs_median_and_its_p95():
    M.reset_prediction_caches()
    conn = _Fleet([], [100 << 20] * 20)
    p95 = M._measured_quantile(conn, "simulation", 1024, M.EXPECTED_PEAK_QUANTILE)
    p50 = M._measured_quantile(conn, "simulation", 1024, M.TYPICAL_PEAK_QUANTILE)
    assert (p95, p50) == (100 << 20, 100 << 20)
    assert sum(HISTORY_SCAN in sql for sql, _ in conn.log) == 1
    assert M.MEASURED_PEAKS_CACHE_SECONDS % 4.0 == 0, "a refresh is a whole number of four-second ticks"
    M.reset_prediction_caches()


def test_a_claim_that_fails_before_its_child_is_returned_and_the_error_still_raised():
    returned, reported = [], []
    timeout = DatabaseOperationalError("PostgreSQL operation failed [55P03]: canceling statement due to "
                                       "lock timeout", transient=True, sqlstate="55P03")
    with pytest.raises(DatabaseOperationalError) as raised:
        with M.returned_on_failure(lambda: returned.append("job") or True,
                                   report=lambda error, released: reported.append((error, released))):
            raise timeout
    assert raised.value is timeout
    assert returned == ["job"] and reported == [(timeout, True)]


def test_a_return_that_fails_leaves_the_lease_to_expire_and_raises_the_original_error(capsys):
    def release():
        raise DatabaseOperationalError("connection lost", transient=True, sqlstate="08006")

    reported = []
    with pytest.raises(RuntimeError, match="the claim's own failure"):
        with M.returned_on_failure(release, report=lambda error, released: reported.append(released)):
            raise RuntimeError("the claim's own failure")
    assert reported == [False]
    assert "could not return a failed claim" in capsys.readouterr().err


def test_an_admitted_claim_is_not_returned():
    returned = []
    with M.returned_on_failure(lambda: returned.append("job")):
        pass
    assert returned == []
