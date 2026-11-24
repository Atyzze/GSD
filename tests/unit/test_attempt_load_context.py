from __future__ import annotations

import time

from graph_scale_dynamics.services.worker import main as worker


def test_a_chain_that_had_its_core_reads_near_one_and_the_host_is_measured():
    start = worker._host_cpu_counters()
    assert start is not None and start[1] >= start[0] >= 0
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        sum(i * i for i in range(2000))
    context = worker.load_context(start, wall_seconds=10.0, user_cpu_seconds=9.5, system_cpu_seconds=0.3)
    assert context["cpu_over_wall"] == 0.98
    assert 0.0 <= context["host_busy_percent"] <= 100.0
    assert context["cores"] and context["cores"] >= 1


def test_a_waiting_chain_reads_well_under_one_and_missing_counters_are_omitted_not_invented():
    context = worker.load_context(None, wall_seconds=100.0, user_cpu_seconds=40.0, system_cpu_seconds=0.0)
    assert context["cpu_over_wall"] == 0.4
    assert "host_busy_percent" not in context, "no reading is better than a made-up one"
    assert "cpu_over_wall" not in worker.load_context(None, 0.0, 1.0, 0.0)
