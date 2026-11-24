from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from graph_scale_dynamics.services.api import host as api_host
from tests.support import split_sources

ROOT = Path(__file__).resolve().parents[2]


def _reset(module):
    module._HOST_SNAPSHOT.update(at=0.0, value=None)


def test_one_sample_per_interval_however_many_callers():
    from graph_scale_dynamics.services.api import main as api

    calls: list[float] = []
    real = api_host.system_resources

    def slow_sample():
        calls.append(time.monotonic())
        time.sleep(0.003)
        return real()

    api_host.system_resources = slow_sample
    try:
        _reset(api)
        threads = [threading.Thread(target=api.host_snapshot) for _ in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(calls) == 1, (
            f"{len(calls)} concurrent host samples in one interval; each one steals "
            "part of the disk and memory-bandwidth delta window from the others"
        )
    finally:
        api_host.system_resources = real
        _reset(api)


def test_the_interval_is_honoured_and_then_released():
    from graph_scale_dynamics.services.api import main as api

    _reset(api)
    try:
        first = api.host_snapshot(now=1000.0)
        assert api.host_snapshot(now=1000.5) is first, "resampled inside the interval"
        later = api.host_snapshot(now=1000.0 + api_host._HOST_SNAPSHOT_INTERVAL_SECONDS + 0.01)
        assert later is not first, "the interval expired and nothing resampled"
    finally:
        _reset(api)


def test_a_sensor_fault_keeps_the_last_reading_rather_than_failing_the_request():
    from graph_scale_dynamics.services.api import main as api

    real = api_host.system_resources
    try:
        _reset(api)
        good = api.host_snapshot(now=2000.0)
        assert good
        api_host.system_resources = lambda: (_ for _ in ()).throw(OSError("sensor gone"))
        assert api.host_snapshot(now=2100.0) is good
        _reset(api)
        assert api.host_snapshot(now=2200.0) == {}, "no prior reading is an empty tile, not a crash"
    finally:
        api_host.system_resources = real
        _reset(api)


def _enclosing_function(tree: ast.AST, target: ast.AST) -> str | None:
    found: list[str] = []

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            if child is target:
                found.append(inner)
            walk(child, inner)

    walk(tree, None)
    return found[0] if found else None


def test_every_caller_goes_through_the_sampler():
    offenders = []
    for module in split_sources.API_MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        offenders += [f"{module.name}:{lineno}" for lineno in _direct_calls(tree)]
    assert not offenders, (
        "system_resources() is called directly at line(s) "
        f"{offenders}; route it through host_snapshot()"
    )


def _direct_calls(tree) -> list[int]:
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "system_resources":
            continue
        if _enclosing_function(tree, node) != "host_snapshot":
            offenders.append(node.lineno)
    return offenders
