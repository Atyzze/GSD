from __future__ import annotations

import multiprocessing
import re
import types

from graph_scale_dynamics.calibration import admission as A
from graph_scale_dynamics.calibration import suite as S
from tests.support import calibration_fakes as F

GIB = 1024 ** 3


class Host:
    def __init__(self, available, total_gib: int = 100):
        self.available = available
        self.total = total_gib * GIB

    def admission(self) -> A.Admission:
        snapshot = lambda: types.SimpleNamespace(available=int(self.available()), total=self.total)  # noqa: E731
        guard = lambda mem: {"allowed": True, "reasons": [], "min_available_bytes": 10 * GIB}  # noqa: E731
        return A.Admission(snapshot=snapshot, guard=guard)


def _task(family: str, n: int, seed: int = 0, sleep: float = 0.6) -> dict:
    return {"key": f"{family}:{n}:{seed}", "family": family, "parameter": n, "seed": seed, "n": n, "sleep": sleep}


def _run(monkeypatch, tasks, host, prices, *, held=0, patience=1200.0, workers=8):
    monkeypatch.setattr(S, "cell_pricing", lambda cells: (lambda family, n: (prices[family], "a test price")))
    monkeypatch.setattr(S, "rss_bytes", lambda pid: held)
    log, finished, blocked = [], [], []
    S._run_in_workers(list(tasks), workers=workers, admission=host.admission(), document={"cells": {}},
                      log=log.append, task_args=dict, finish=lambda cell, running=1: finished.append(cell),
                      blocked=blocked, root=None, science="test", cell_target=F.fake_cell_main,
                      patience=patience, watch=0.05)
    return log, finished, blocked


def _starts(log):
    return [re.search(r"started (\S+) ", line).group(1) for line in log if "calibration: started" in line]


def _peak(log):
    return max(int(re.search(r"; (\d+) running", line).group(1)) for line in log if "calibration: started" in line)


def test_a_running_cell_is_charged_its_price_less_what_it_holds(monkeypatch):
    host = Host(lambda: 40 * GIB)
    tasks = [_task("periodic_ring", 1_048_576, seed) for seed in range(6)]
    log, finished, blocked = _run(monkeypatch, tasks, host, {"periodic_ring": 8 * GIB}, held=2 * GIB)
    assert len(finished) == 6 and not blocked
    assert _peak(log) == 6, log
    assert A.remaining_bytes(8 * GIB, 2 * GIB) == 6 * GIB


def test_a_cheaper_cell_starts_while_the_first_in_line_waits(monkeypatch):
    host = Host(lambda: 40 * GIB)
    tasks = [_task("periodic_ring", 1_048_576, sleep=1.0), _task("periodic_cubic_lattice", 4_096_000),
             _task("balanced_binary_tree", 1_048_575)]
    prices = {"periodic_ring": 10 * GIB, "periodic_cubic_lattice": 25 * GIB, "balanced_binary_tree": 5 * GIB}
    log, finished, _blocked = _run(monkeypatch, tasks, host, prices)
    assert len(finished) == 3
    order = _starts(log)
    assert order.index("balanced_binary_tree:1048575:0") < order.index("periodic_cubic_lattice:4096000:0"), order


def test_after_its_patience_nothing_starts_ahead_of_the_first_in_line(monkeypatch):
    host = Host(lambda: 40 * GIB)
    tasks = [_task("periodic_ring", 1_048_576, sleep=1.0), _task("periodic_cubic_lattice", 4_096_000),
             _task("balanced_binary_tree", 1_048_575)]
    prices = {"periodic_ring": 10 * GIB, "periodic_cubic_lattice": 25 * GIB, "balanced_binary_tree": 5 * GIB}
    log, finished, _blocked = _run(monkeypatch, tasks, host, prices, patience=0.0)
    assert len(finished) == 3
    order = _starts(log)
    assert order.index("periodic_cubic_lattice:4096000:0") < order.index("balanced_binary_tree:1048575:0"), order


def test_under_the_shed_line_the_youngest_cell_is_ended_and_a_cell_shed_twice_is_blocked(monkeypatch):
    host = Host(lambda: 40 * GIB if len(multiprocessing.active_children()) <= 1 else 6 * GIB)
    tasks = [_task("periodic_ring", 1_048_576, sleep=3.0), _task("balanced_binary_tree", 1_048_575)]
    prices = {"periodic_ring": 8 * GIB, "balanced_binary_tree": 8 * GIB}
    log, finished, blocked = _run(monkeypatch, tasks, host, prices)
    assert [cell["family"] for cell in finished] == ["periodic_ring"]
    assert [b["key"] for b in blocked] == ["balanced_binary_tree:1048575:0"]
    assert "ended 2 times" in blocked[0]["reason"]
    assert sum("memory shed" in line for line in log) == 2


def test_a_family_is_priced_from_its_whole_measured_peak_in_proportion():
    cells = {"a": {"family": "balanced_binary_tree", "n": 1_048_575, "status": "ok", "peak_rss_bytes": int(1.09 * GIB)},
             "b": {"family": "balanced_binary_tree", "n": 262_143, "status": "ok", "peak_rss_bytes": int(0.5 * GIB)},
             "c": {"family": "periodic_ring", "n": 4096, "status": "ok", "peak_rss_bytes": 5 * GIB}}
    price = A.cell_pricing(cells)
    bytes_4m, basis = price("balanced_binary_tree", 4_194_303)
    assert basis == "measured on this family"
    expected = A.MEASURED_MARGIN * max(1.09 * GIB * 4_194_303 / 1_048_575, 0.5 * GIB * 4_194_303 / 262_143)
    assert abs(bytes_4m - expected) < 1024
    assert price("balanced_binary_tree", 65_535) == (int(A.SAME_SIZE_MARGIN * 0.5 * GIB),
                                                     "a larger cell measured on this family")
    assert price("periodic_ring", 4_194_304) == (A.predicted_cell_bytes(4_194_304), "the 4 KiB per node model")


def test_what_a_cell_may_still_take_never_goes_below_zero():
    assert A.remaining_bytes(8 * GIB, 2 * GIB) == 6 * GIB
    assert A.remaining_bytes(8 * GIB, 9 * GIB) == 0
    assert A.remaining_bytes(8 * GIB, None) == 8 * GIB
    assert A.shed_line(10 * GIB) == 8 * GIB


def test_the_hold_line_says_what_the_running_cells_hold_and_may_still_take():
    decision = {"available_bytes": 56.7 * GIB, "reserve_bytes": 10 * GIB, "budget_bytes": 46.7 * GIB}
    line = S._hold_line(4, 31, {"key": "periodic_hypercubic_lattice_4d:45:1", "n": 4_100_625}, int(16.5 * GIB),
                        "the 4 KiB per node model", int(32.4 * GIB), decision, held=int(16.0 * GIB),
                        priced=int(48.4 * GIB))
    for needle in ("4 of 31 worker(s) busy", "16.5 GiB", "46.7 GiB", "hold 16.0 GiB of the 48.4 GiB",
                   "may take 32.4 GiB more"):
        assert needle in line, needle
