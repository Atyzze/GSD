from __future__ import annotations

import multiprocessing
import os
import re
import signal
import time
import types
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import admission as A
from graph_scale_dynamics.calibration import suite as S
from graph_scale_dynamics.calibration.cells import CELL_OOM_SCORE_ADJ
from tests.support import calibration_fakes as F

GIB = 1024 ** 3


def cell(key, *, price, held=0.0, started=0.0, growth=0.0, typical=None, paused_at=None, strict=False):
    price_b = int(price * GIB)
    typical_b = int((A.TYPICAL_SHARE * price if typical is None else typical) * GIB)
    return A.CellMemory(key=key, started=started, price=price_b, typical=typical_b, held=int(held * GIB),
                        growth=int(growth * GIB), paused=paused_at is not None, paused_at=paused_at, strict=strict)


def operators_1552():
    return [cell("erdos_renyi_sparse:4194304:0", price=5.5, held=1.7, started=1),
            cell("erdos_renyi_sparse:4194304:1", price=5.5, held=1.7, started=2),
            cell("erdos_renyi_sparse:4194304:2", price=5.5, held=1.6, started=3),
            cell("periodic_honeycomb_lattice:2048:2", price=4.7, held=3.5, started=4),
            cell("periodic_ring:4194304:1", price=14.4, held=3.0, started=5),
            cell("periodic_ring:4194304:2", price=14.4, held=3.2, started=6),
            cell("random_3_regular:4194304:0", price=6.1, held=1.8, started=7)]


def test_the_square_lattice_526_held_back_at_1552_now_starts():
    running = operators_1552()
    budget = int((50.7 - 10.0) * GIB)
    square = cell("periodic_square_lattice:2048:0", price=16.9, started=8)
    old = square.price + sum(A.remaining_bytes(c.price, c.held) for c in running)
    assert old > budget
    queue = [cell(f"periodic_square_lattice:2048:{s}", price=16.9, started=8 + s) for s in range(3)] + [
        cell(f"periodic_triangular_lattice:2048:{s}", price=16.9, started=11 + s) for s in range(3)]
    started = []
    for candidate in queue:
        if not A.fits_beside(candidate, [*running, *started], budget)[0]:
            break
        started.append(candidate)
    assert len(started) >= 3, [c.key for c in started]
    assert len(running) + len(started) >= 10


def test_admission_counts_the_growth_to_where_cells_settle_and_one_spike():
    a = cell("a", price=10, held=1, typical=4)
    b = cell("b", price=8, held=5, typical=4)
    c = cell("c", price=2, held=3, typical=1)
    counted = A.still_to_take([a, b, c])
    assert counted["typical_growth_bytes"] == 3 * GIB
    assert counted["spike_room_bytes"] == 6 * GIB == max(10 - 4, 8 - 5, 0) * GIB
    assert counted["bytes"] == 9 * GIB and counted["spikes_counted"] == A.SPIKE_OVERLAP == 1


def test_a_cell_ended_once_starts_again_only_when_everything_could_peak_beside_it():
    running = [cell("a", price=10, held=2), cell("b", price=10, held=2)]
    again = cell("c", price=10, strict=True)
    assert A.need_beside(again, running) == (10 + 8 + 8) * GIB
    assert A.need_beside(cell("c", price=10), running) < A.need_beside(again, running)


def test_under_the_shed_line_the_youngest_paused_cell_is_ended_first():
    running = [cell("old", price=10, held=9, started=1), cell("young", price=10, held=2, started=5)]
    paused = [cell("p1", price=10, held=3, started=2, paused_at=50), cell("p2", price=10, held=3, started=3,
                                                                          paused_at=60)]
    floor = 10 * GIB
    assert A.pressure(running, paused, int(7.9 * GIB), floor) == [("end", paused[1])]
    assert A.pressure(running, [], int(7.9 * GIB), floor) == [("end", running[1])]
    assert A.pressure(running, paused, int(8.1 * GIB), floor) == []


def test_a_climb_that_finds_no_room_pauses_its_cell_and_the_oldest_never_pauses():
    floor = 10 * GIB
    oldest = cell("oldest", price=16, held=4, growth=1, started=1)
    second = cell("second", price=16, held=4, growth=1, started=2)
    flat = cell("flat", price=16, held=4, growth=0, started=3)
    third = cell("third", price=6, held=2, growth=0.5, started=4)
    available = int((10 + 2 + 17) * GIB)
    actions = A.pressure([oldest, second, flat, third], [], available, floor)
    assert actions == [("pause", second)]
    actions = A.pressure([oldest, second, flat, third], [], int(12.5 * GIB), floor)
    assert actions == [("pause", second), ("pause", third)]
    assert A.pressure([second], [], int(12.5 * GIB), floor) == []


def test_the_oldest_paused_cell_continues_when_its_claim_fits():
    floor = 10 * GIB
    running = [cell("r", price=16, held=15, growth=0, started=1)]
    first = cell("first", price=16, held=4, started=2, paused_at=100.0)
    later = cell("later", price=6, held=1, started=3, paused_at=101.0)
    enough = int((10 + 2 + 12) * GIB)
    assert A.to_continue(running, [later, first], enough, floor, now=100.0 + A.MIN_PAUSE_SECONDS) is first
    assert A.to_continue(running, [later, first], enough, floor, now=110.0) is None
    assert A.to_continue(running, [later, first], enough - GIB, floor, now=1000.0) is None
    assert A.to_continue([], [later, first], 0, floor, now=100.0) is first


def test_a_family_measured_at_this_size_is_priced_with_a_tenth_more():
    cells = {"a": {"family": "periodic_ring", "n": 4194304, "status": "ok", "peak_rss_bytes": 11 * GIB},
             "b": {"family": "periodic_ring", "n": 4194304, "status": "ok", "peak_rss_bytes": int(11.5 * GIB)},
             "c": {"family": "periodic_ring", "n": 1048576, "status": "ok", "peak_rss_bytes": int(2.5 * GIB)}}
    price = A.cell_pricing(cells)
    assert price("periodic_ring", 4194304) == (int(1.10 * 11.5 * GIB), "measured at this size on this family")
    extrapolated, basis = price("periodic_ring", 8388608)
    assert basis == "measured on this family" and extrapolated == int(1.25 * 2 * 11.5 * GIB)


def test_a_cell_smaller_than_any_measured_one_is_capped_by_the_nearest_larger_one_not_priced_at_it():
    cells = {"r": {"family": "periodic_ring", "n": 4194304, "status": "ok", "peak_rss_bytes": int(11.5 * GIB)},
             "s": {"family": "periodic_square_lattice", "n": 4194304, "status": "ok",
                   "peak_rss_bytes": int(4.19 * GIB)},
             "a": {"family": "periodic_honeycomb_lattice", "n": 1048576, "status": "ok", "peak_rss_bytes": 3 * GIB},
             "b": {"family": "periodic_honeycomb_lattice", "n": 4194304, "status": "ok",
                   "peak_rss_bytes": int(3.75 * GIB)}}
    price = A.cell_pricing(cells)
    assert price("periodic_ring", 65536) == (A.predicted_cell_bytes(65536), "the 4 KiB per node model")
    assert price("periodic_square_lattice", 1048576) == (int(1.10 * 4.19 * GIB),
                                                          "a larger cell measured on this family")
    assert price("periodic_honeycomb_lattice", 2097152) == (int(1.10 * 3.75 * GIB),
                                                             "a larger cell measured on this family")
    assert price("periodic_honeycomb_lattice", 1100000)[1] == "measured on this family"


def test_where_a_family_settles_comes_from_its_recorded_memory():
    cells = {"a": {"family": "periodic_ring", "n": 4194304, "status": "ok", "peak_rss_bytes": 10 * GIB,
                   "mean_rss_bytes": 3 * GIB},
             "b": {"family": "periodic_ring", "n": 1048576, "status": "ok", "peak_rss_bytes": 3 * GIB,
                   "mean_rss_bytes": int(1.2 * GIB)},
             "c": {"family": "periodic_ring", "n": 4096, "status": "ok", "peak_rss_bytes": GIB,
                   "mean_rss_bytes": GIB}}
    share = A.typical_shares(cells)
    assert share("periodic_ring") == (pytest.approx(0.4), "its family's recorded memory")
    assert share("random_3_regular") == (A.TYPICAL_SHARE, "the default share")


def test_a_timeline_keeps_each_pieces_highest_sample():
    samples = [(t, 100 + t) for t in range(0, 100)] + [(50.5, 10_000)]
    line = A.timeline(samples, points=10)
    assert len(line) == 10 and [50, 10_000] in line
    assert A.mean_of([(0, 2), (5, 4)]) == 3 and A.mean_of([]) is None


class ReportedHost:
    def __init__(self, report: Path, room: float):
        self.report, self.room = report, room

    def held(self, pid) -> int:
        try:
            return int((self.report / str(int(pid))).read_text() or 0)
        except (OSError, ValueError):
            return 0

    def admission(self) -> A.Admission:
        def snapshot():
            live = sum(self.held(child.pid) for child in multiprocessing.active_children())
            return types.SimpleNamespace(available=int((10 + 2 + self.room) * GIB) - live, total=100 * GIB)
        guard = lambda mem: {"allowed": True, "reasons": [], "min_available_bytes": 10 * GIB}  # noqa: E731
        return A.Admission(snapshot=snapshot, guard=guard)


def _climbing(key: str, report: Path, *, steps=24, step=0.1) -> dict:
    family, n, seed = key.split(":")
    return {"key": key, "family": family, "parameter": int(n), "seed": int(seed), "n": int(n),
            "report": str(report), "plateau": 1 * GIB, "peak": 8 * GIB, "steps": steps, "step": step}


@pytest.fixture
def quick_rules(monkeypatch):
    monkeypatch.setattr(A, "GROWTH_BYTES", GIB // 2)
    monkeypatch.setattr(A, "GROWTH_WINDOW_SECONDS", 0.5)
    monkeypatch.setattr(S, "GROWTH_WINDOW_SECONDS", 0.5)
    monkeypatch.setattr(A, "MIN_PAUSE_SECONDS", 0.2)
    monkeypatch.setattr(S, "TRACE_SECONDS", 0.05)


def _run(monkeypatch, tasks, host, *, price=9, log=None):
    monkeypatch.setattr(S, "cell_pricing", lambda cells: (lambda family, n: (int(price * GIB), "a test price")))
    monkeypatch.setattr(S, "rss_bytes", host.held)
    log = [] if log is None else log
    finished, blocked = [], []
    S._run_in_workers(list(tasks), workers=8, admission=host.admission(), document={"cells": {}},
                      log=log.append, task_args=dict, finish=lambda c, running=1: finished.append(c),
                      blocked=blocked, root=None, science="test", cell_target=F.fake_climbing_cell,
                      watch=0.02, hold_first=0.0)
    return log, finished, blocked


def _most_running(log) -> int:
    return max(int(re.search(r"; (\d+) running", line).group(1)) for line in log if "calibration: started" in line)


def test_three_cells_climbing_at_once_the_youngest_waits_paused_and_nothing_is_shed(tmp_path, monkeypatch,
                                                                                  quick_rules):
    host = ReportedHost(tmp_path, room=22)
    tasks = [_climbing(f"periodic_square_lattice:4194304:{seed}", tmp_path) for seed in range(3)]
    log, finished, blocked = _run(monkeypatch, tasks, host)
    assert not blocked and not any("memory shed" in line for line in log), log
    assert sorted(c["seed"] for c in finished) == [0, 1, 2] and _most_running(log) == 3
    paused = [line for line in log if "calibration: paused" in line]
    assert paused and all("periodic_square_lattice:4194304:2" in line for line in paused), log
    assert any("calibration: continued periodic_square_lattice:4194304:2" in line for line in log), log
    waited = next(c for c in finished if c["seed"] == 2)
    assert waited["paused_seconds"] > 0.3
    ran = next(c for c in finished if c["seed"] == 0)
    assert waited["elapsed_seconds"] < ran["elapsed_seconds"] + 0.5, "paused time is not the cell's cost"
    assert waited["memory_timeline"] and waited["mean_rss_bytes"] > GIB


def test_526_would_have_run_two_and_kept_the_third_waiting(tmp_path, monkeypatch, quick_rules):
    host = ReportedHost(tmp_path, room=22)
    tasks = [_climbing(f"periodic_square_lattice:4194304:{seed}", tmp_path, steps=6) for seed in range(3)]
    monkeypatch.setattr(A, "TYPICAL_SHARE", 1.0)
    monkeypatch.setattr(A, "SPIKE_OVERLAP", 99)
    log, finished, _blocked = _run(monkeypatch, tasks, host)
    assert len(finished) == 3 and _most_running(log) == 2
    assert not any("calibration: paused" in line for line in log)


def test_a_cell_alone_past_the_host_is_ended_and_blocked_the_second_time(tmp_path, monkeypatch, quick_rules):
    host = ReportedHost(tmp_path, room=3)
    log, finished, blocked = _run(monkeypatch, [_climbing("periodic_ring:4194304:0", tmp_path, steps=10)], host,
                                  price=1)
    assert not finished and [b["key"] for b in blocked] == ["periodic_ring:4194304:0"]
    assert sum("memory shed" in line for line in log) == 2 and "ended 2 times" in blocked[0]["reason"]


def test_a_paused_cell_does_not_outlive_the_suite(tmp_path, monkeypatch, quick_rules):
    host = ReportedHost(tmp_path, room=22)
    tasks = [_climbing(f"periodic_square_lattice:4194304:{seed}", tmp_path, steps=60) for seed in range(3)]
    seen = []

    def log(line):
        seen.append(line)
        if "calibration: paused" in line:
            raise KeyboardInterrupt

    monkeypatch.setattr(S, "cell_pricing", lambda cells: (lambda family, n: (9 * GIB, "a test price")))
    monkeypatch.setattr(S, "rss_bytes", host.held)
    with pytest.raises(KeyboardInterrupt):
        S._run_in_workers(tasks, workers=8, admission=host.admission(), document={"cells": {}}, log=log,
                          task_args=dict, finish=lambda c, running=1: None, blocked=[], root=None,
                          science="test", cell_target=F.fake_climbing_cell, watch=0.02, hold_first=0.0)
    deadline = time.monotonic() + 10
    while multiprocessing.active_children() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not multiprocessing.active_children()


def test_a_cell_goes_first_to_the_kernels_killer_and_ends_with_its_suite(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    suite = context.Process(target=F.start_orphaned_cell, args=(str(tmp_path), ready))
    suite.start()
    pid_file = tmp_path / "orphan.pid"
    deadline = time.monotonic() + 30
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = int(pid_file.read_text())
    adj = Path(f"/proc/{pid}/oom_score_adj")
    while time.monotonic() < deadline and (not adj.exists() or adj.read_text().strip() != str(CELL_OOM_SCORE_ADJ)):
        time.sleep(0.05)
    assert adj.read_text().strip() == "500" == str(CELL_OOM_SCORE_ADJ)
    ready.set()
    suite.join(20)

    def ended() -> bool:
        try:
            state = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            return True
        return bool(re.search(r"^State:\s+[ZX]", state, re.M))

    while not ended() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not ended():
        os.kill(pid, signal.SIGKILL)
        pytest.fail("the cell outlived the process that started it")
