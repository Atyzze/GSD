from __future__ import annotations

from graph_scale_dynamics.scheduling import memory as M
from graph_scale_dynamics.scheduling.memory import MemorySnapshot

GIB = 1 << 30
HOST = 92 * GIB


def lease(kind, ident, reserved, peak, current=None, started=None, n=1048576):
    gib = lambda v: None if v is None else int(v * GIB)
    return {"kind": kind, "id": ident, "n": n, "reserved_bytes": int(reserved * GIB), "observed_bytes": gib(peak),
            "current_bytes": gib(current), "started_utc": started}


def test_the_floor_is_ten_gib_on_a_workstation_and_a_tenth_of_a_small_host(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    assert M.host_available_floor_bytes(HOST) == 10 * GIB
    assert M.host_available_floor_bytes(3 * GIB) == int(0.3 * GIB)
    monkeypatch.setenv("GSD_HOST_MEMORY_FLOOR_BYTES", str(4 * GIB))
    assert M.host_available_floor_bytes(HOST) == 4 * GIB


def test_headroom_is_available_less_the_floor_less_what_children_have_yet_to_take(monkeypatch):
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    rows = [lease("simulation", f"deep-{i}", 6.6, 2.5, 2.5) for i in range(5)] + [
        lease("analysis", "probe-0", 2.9, 1.65, 1.65), lease("analysis", "probe-1", 2.9, 1.65, 1.65)]
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=38 * GIB), observations=rows)
    assert got["floor_bytes"] == 10 * GIB
    still = lambda kind: sum(r["reserved_bytes"] - r["current_bytes"] for r in rows if r["kind"] == kind)
    assert got["unrealised_by_lane"] == {"simulation": still("simulation"), "analysis": still("analysis")}
    assert abs(got["unrealised_by_lane"]["simulation"] - 5 * 4.1 * GIB) < 16
    expected = 38 * GIB - 10 * GIB - got["unrealised_bytes"]
    assert got["headroom_bytes"] == expected and got["headroom_bytes"] > 5 * GIB
    assert got["budget_bytes"] == got["reserved_bytes"] + expected
    assert got["shed_below_bytes"] == 8 * GIB


def test_what_a_child_has_yet_to_take_is_counted_from_what_it_holds_not_from_its_peak():
    between_spikes = lease("simulation", "deep", 4.5, 4.0, current=2.0)
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=20 * GIB),
                               observations=[between_spikes])
    assert got["unrealised_bytes"] == int(4.5 * GIB) - 2 * GIB, "458 read 0.5 GiB here"
    assert got["held_bytes"] == 2 * GIB


def test_a_child_not_yet_measured_counts_its_whole_reservation_and_one_past_it_counts_its_peak():
    rows = [lease("simulation", "young", 3.0, None), lease("simulation", "grown", 1.0, 1.4, current=1.4)]
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=20 * GIB), observations=rows)
    assert got["unrealised_bytes"] == 3 * GIB
    assert got["headroom_bytes"] == 7 * GIB


class _PeaksConn:
    def __init__(self, peaks):
        self.peaks = peaks

    def execute(self, sql, args=()):
        rows = [{"pss": int(p), "rss": int(p)} for p in self.peaks]

        class _Cursor:
            def fetchall(self_inner):
                return rows
        return _Cursor()


def test_a_rung_with_real_runs_expects_its_measured_peak_rather_than_the_reservation():
    M.reset_prediction_caches()
    conn = _PeaksConn([4.3 * GIB] * 10 + [4.5 * GIB] * 10)
    young = lease("simulation", "young-deep", 6.6, None, None)
    got = M.admission_headroom(conn, snapshot=MemorySnapshot(total=HOST, available=30 * GIB), observations=[young])
    assert got["unrealised_bytes"] == int(4.5 * GIB * M.EXPECTED_PEAK_SLACK) + 1, got["unrealised_bytes"]
    M.reset_prediction_caches()
    heavy = lease("simulation", "heavy", 6.6, 5.9, 3.0)
    got = M.admission_headroom(conn, snapshot=MemorySnapshot(total=HOST, available=30 * GIB), observations=[heavy])
    assert got["unrealised_bytes"] == int(5.9 * GIB) - 3 * GIB, "its own peak outranks a lighter rung"
    M.reset_prediction_caches()


def test_headroom_never_goes_negative_and_the_budget_then_equals_what_is_held():
    rows = [lease("simulation", "big", 30.0, 1.0, 1.0)]
    got = M.admission_headroom(None, snapshot=MemorySnapshot(total=HOST, available=15 * GIB), observations=rows)
    assert got["headroom_bytes"] == 0 and got["budget_bytes"] == got["reserved_bytes"]


def test_children_settle_at_their_rung_median_and_only_the_largest_spikes_are_counted():
    M.reset_prediction_caches()
    conn = _PeaksConn([4.4 * GIB] * 10 + [5.38 * GIB] * 10)
    rows = [lease("simulation", f"deep-{i}", 5.92, 2.2, 2.15) for i in range(7)]
    got = M.admission_headroom(conn, snapshot=MemorySnapshot(total=HOST, available=38 * GIB), observations=rows)
    typical = M._measured_quantile(conn, "simulation", 1048576, M.TYPICAL_PEAK_QUANTILE)
    peak = int(__import__("math").ceil(M._measured_quantile(conn, "simulation", 1048576, M.EXPECTED_PEAK_QUANTILE)
                                       * M.EXPECTED_PEAK_SLACK))
    held = int(2.15 * GIB)
    expected = 7 * (typical - held) + M.SPIKE_OVERLAP * (peak - typical)
    assert got["unrealised_bytes"] == expected and got["spike_room_bytes"] == M.SPIKE_OVERLAP * (peak - typical)
    every_spike = 7 * (peak - held)
    assert every_spike - got["unrealised_bytes"] > 4 * GIB, "463 counted every child's spike at once"
    M.reset_prediction_caches()


def test_nothing_is_shed_while_available_memory_is_above_the_shed_line():
    rows = [lease("simulation", "a", 4.0, 4.0, 4.0, "2026-09-16T00:00:00Z")]
    mem = MemorySnapshot(total=HOST, available=int(8.5 * GIB))
    assert M.memory_shed_reason(None, {"job_id": "a"}, snapshot=mem, observations=rows) is None


def test_children_are_shed_by_the_least_compute_lost_per_byte_until_the_floor_is_back():
    now = 1_800_000_000.0

    def ago(seconds):
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))

    rows = [
        lease("simulation", "old-deep", 4.4, 4.4, 4.4, ago(3 * 3600)),
        lease("simulation", "young-deep", 4.0, 3.5, 3.0, ago(600)),
        lease("simulation", "young-small", 0.2, 0.1, 0.1, ago(60)),
        lease("analysis", "probe", 3.0, 3.0, 3.0, ago(30)),
    ]
    mem = MemorySnapshot(total=HOST, available=6 * GIB)
    def shed(job, kind="simulation"):
        return M.memory_shed_reason(None, {"job_id": job}, snapshot=mem, observations=rows, now=now, kind=kind)

    assert shed("probe", "analysis") == M.PREEMPT_MEMORY_FLOOR
    assert {job: shed(job) for job in ("old-deep", "young-deep", "young-small")} == {
        "young-deep": M.PREEMPT_MEMORY_FLOOR, "young-small": None, "old-deep": None}
    assert shed("probe") is None
    mem = MemorySnapshot(total=HOST, available=int(7.9 * GIB))
    assert shed("probe", "analysis") == M.PREEMPT_MEMORY_FLOOR
    assert {job: shed(job) for job in ("old-deep", "young-deep", "young-small")} == {
        "young-deep": None, "young-small": None, "old-deep": None}


def test_a_child_that_saved_its_state_recently_loses_little_when_shed():
    now = 1_800_000_000.0

    def ago(seconds):
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))

    rows = [lease("simulation", "old-saved", 4.4, 4.4, 4.0, ago(3 * 3600)),
            lease("simulation", "young-unsaved", 4.4, 4.4, 4.0, ago(600))]
    mem = MemorySnapshot(total=HOST, available=7 * GIB)
    saved = {"old-saved": now - 60}.get
    shed = {job: M.memory_shed_reason(None, {"job_id": job}, snapshot=mem, observations=rows, now=now,
                                      saved_at=saved) for job in ("old-saved", "young-unsaved")}
    assert shed == {"old-saved": M.PREEMPT_MEMORY_FLOOR, "young-unsaved": None}, shed
    unsaved = {job: M.memory_shed_reason(None, {"job_id": job}, snapshot=mem, observations=rows, now=now)
               for job in ("old-saved", "young-unsaved")}
    assert unsaved == {"old-saved": None, "young-unsaved": M.PREEMPT_MEMORY_FLOOR}, unsaved


def test_a_shed_attempt_is_an_interruption_not_a_result():
    from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES, interrupted_sql
    assert M.PREEMPT_MEMORY_FLOOR in INTERRUPTED_ATTEMPT_CLASSES
    assert f"'{M.PREEMPT_MEMORY_FLOOR}'" in interrupted_sql("a")


def test_the_floor_is_the_operating_point_verdict_not_a_starved_queue():
    from graph_scale_dynamics.operations.compute_ecology import memory_floor_verdict
    admission = {"floor_bytes": 10 * GIB, "available_bytes": int(11.5 * GIB), "unrealised_bytes": int(1.2 * GIB),
                 "headroom_bytes": int(0.3 * GIB), "shed_below_bytes": 8 * GIB}
    state, severity, text = memory_floor_verdict(admission, waiting=0, deferred=40, idle=17)
    assert (state, severity) == ("MEMORY_FLOOR", "normal")
    for needle in ("10.0 GiB", "11.5 GiB available", "0.3 GiB headroom", "40 job(s) wait", "17 slot(s) idle",
                   "under 8.0 GiB"):
        assert needle in text, (needle, text)
    assert memory_floor_verdict(admission, waiting=5, deferred=0, idle=17, reservation_percent=60.0) is None
    assert memory_floor_verdict(admission, waiting=5, deferred=0, idle=0, reservation_percent=99.0) is None
    assert memory_floor_verdict(admission, waiting=80, deferred=8, idle=1, slots=32, reservation_percent=97.7) is None


def test_the_live_verdict_names_the_memory_floor_it_sits_at():
    from graph_scale_dynamics.services.api.fleet_snapshots import _capacity_diagnosis
    admission = {"floor_bytes": 10 * GIB, "available_bytes": 11 * GIB, "unrealised_bytes": GIB,
                 "headroom_bytes": 0, "shed_below_bytes": 8 * GIB}
    common = dict(paused=False, resources={"cpu_percent": 51.0, "memory_load_percent": 59.0}, active_slots=15,
                  scheduler_slots=32, blocked_simulations=0, deferred_analyses=0, memory_deferred_analyses=0,
                  stranded_nonterminal=0, nonterminal_observed=900, governor={}, admission=admission)
    state, _, _ = _capacity_diagnosis(runnable_simulations=0, runnable_analyses=2, deferred_simulations=40,
                                      memory_reservation_percent=99.3, **common)
    assert state == "MEMORY_FLOOR"
    state, severity, _ = _capacity_diagnosis(runnable_simulations=12, runnable_analyses=0, deferred_simulations=0,
                                             memory_reservation_percent=99.3, **common)
    assert (state, severity) == ("MEMORY_FLOOR", "normal")
    roomy = dict(common, admission=dict(admission, headroom_bytes=12 * GIB))
    state, _, _ = _capacity_diagnosis(runnable_simulations=12, runnable_analyses=0, deferred_simulations=0,
                                      memory_reservation_percent=40.0, **roomy)
    assert state == "SCHEDULER_UNDERFILL"
    full = dict(common, active_slots=31, resources={"cpu_percent": 99.9, "memory_load_percent": 61.0})
    state, _, _ = _capacity_diagnosis(runnable_simulations=71, runnable_analyses=1, deferred_simulations=8,
                                      memory_reservation_percent=97.7, **full)
    assert state == "CPU_LIMITED", state
