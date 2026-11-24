from __future__ import annotations

import os
from pathlib import Path

from graph_scale_dynamics.measurements.benchmarks import (
    BENCHMARK_WORKERS_ENV, LATTICES_OF_THE_TABLE, benchmark_workers, held_as_the_table_holds, _battery_unit,
    _measure_all,
)

ROOT = Path(__file__).resolve().parents[2]


def test_the_benchmark_key_does_not_move_when_the_build_number_does():
    from graph_scale_dynamics.db.repo import analyzer_identity
    identity = analyzer_identity()
    assert identity.startswith("science:"), "keyed on the frozen sources, not the tree"


def test_the_key_is_the_declared_set_of_files_that_can_change_a_number():
    from graph_scale_dynamics.domain.science_identity import frozen_paths
    frozen = set(frozen_paths())
    for essential in ("graph_scale_dynamics/measurements/estimators.py",
                      "graph_scale_dynamics/measurements/analysis.py",
                      "graph_scale_dynamics/measurements/certificate.py",
                      "graph_scale_dynamics/measurements/benchmarks.py",
                      "graph_scale_dynamics/measurements/box_covering.py",
                      "graph_scale_dynamics/measurements/walk_dimension.py",
                      "graph_scale_dynamics/scaleflow/flow.py"):
        assert essential in frozen, f"{essential} must invalidate the battery"
    assert not any(path.endswith((".css", ".js")) for path in frozen), \
        "a stylesheet change must not re-run the numerical controls"


def test_worker_count_defaults_to_every_core():
    assert benchmark_workers() == max(1, os.cpu_count() or 1)
    assert benchmark_workers(4) == 4
    assert benchmark_workers(0) == 1


def test_worker_count_is_overridable_for_a_serial_run(monkeypatch):
    monkeypatch.setenv(BENCHMARK_WORKERS_ENV, "1")
    assert benchmark_workers() == 1
    monkeypatch.setenv(BENCHMARK_WORKERS_ENV, "not a number")
    assert benchmark_workers() == max(1, os.cpu_count() or 1), "a bad value falls back"


def test_the_graph_is_rebuilt_from_its_key_not_shipped_to_the_worker():
    task = ("periodic_ring", 128, 1)
    _task, n, metrics = _battery_unit(task)
    assert _task == task and n == 128 and metrics["d_V"]["valid"]
    again = _battery_unit(task)
    assert again[2]["d_V"]["d_V_window"] == metrics["d_V"]["d_V_window"], (
        "deterministic, so the worker cannot drift from the parent")


def test_results_are_indexed_by_task_so_completion_order_cannot_reach_a_check():
    tasks = [("periodic_ring", 64, 1), ("periodic_ring", 128, 1)]
    serial = _measure_all(tasks, workers=1)
    assert set(serial) == set(tasks)
    for task in tasks:
        assert serial[task][0] == task[1], "keyed by its own task, not by position"


def test_the_battery_reads_cells_of_the_table_and_holds_them_to_its_rule_alone():
    from graph_scale_dynamics.calibration.cells import family_ladder, suite_families
    from graph_scale_dynamics.measurements.calibration import ladder_tolerance
    for family, parameter in LATTICES_OF_THE_TABLE:
        spec = suite_families([family])[0]
        rung = next(r for r in family_ladder(spec) if r["parameter"] == parameter)
        theory = spec["theory"]
        held = {probe: ladder_tolerance(family, probe, rung["n"]) for probe in theory}
        assert held["d_s"] is not None and held["d_V"] is not None, f"the rule holds {family} at {rung['n']:,} nodes"
        at = (family, parameter, rung["n"])
        inside = {probe: [theory[probe] + 0.99 * band] * 3 for probe, band in held.items() if band is not None}
        assert all(row["passed"] for row in held_as_the_table_holds(*at, inside))
        assert sorted(row["probe"] for row in held_as_the_table_holds(*at, inside)) == sorted(inside)
        outside = dict(inside, d_s=[theory["d_s"] + 1.01 * held["d_s"]] * 3)
        judged = {row["probe"]: row for row in held_as_the_table_holds(*at, outside)}
        assert (judged["d_s"]["passed"], judged["d_s"]["status"], judged["d_V"]["passed"]) == (
            False, "OUT_OF_TOLERANCE", True)
        refused = dict(inside, d_V=[theory["d_V"], None, None])
        judged = {row["probe"]: row for row in held_as_the_table_holds(*at, refused)}
        assert (judged["d_V"]["passed"], judged["d_V"]["status"]) == (False, "REFUSED_MAJORITY"), (
            "read on fewer than half its seeds, as the table's gate counts")
        none = dict(inside, d_V=[None, None, None])
        assert {row["probe"]: row["status"] for row in held_as_the_table_holds(*at, none)}["d_V"] == "REFUSED"
        not_held = {probe: [9.9] * 3 for probe, band in held.items() if band is None}
        assert held_as_the_table_holds(*at, not_held) == [], "a probe the rule does not hold is not judged"


def test_the_key_falls_back_rather_than_trusting_an_unreadable_freeze(monkeypatch):
    from graph_scale_dynamics.db.repo import analyzer_identity
    from graph_scale_dynamics.domain import science_identity, version
    monkeypatch.setattr(science_identity, "science_fingerprint", lambda: "unavailable")
    monkeypatch.setattr(version, "runtime_fingerprint", lambda: "runtime:abc")
    assert analyzer_identity() == "runtime:abc"


def test_a_pool_that_cannot_start_falls_back_to_serial(monkeypatch):
    import concurrent.futures

    from graph_scale_dynamics.measurements import benchmarks

    def refused(*args, **kwargs):
        raise OSError("no processes here")

    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", refused)
    monkeypatch.setattr(benchmarks, "_battery_unit", lambda task: (task, 64, {"task": task}))
    assert benchmarks._measure_all(["a", "b"], 2) == {"a": (64, {"task": "a"}), "b": (64, {"task": "b"})}
