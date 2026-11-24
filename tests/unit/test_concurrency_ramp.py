from __future__ import annotations

from collections import namedtuple

import pytest

from graph_scale_dynamics.scheduling.concurrency import (
    CONNECTIONS_PER_SLOT, CPU_BACKOFF_PERCENT, CPU_TARGET_PERCENT, FLOOR_SLOTS, GIB, HARD_MAX_SLOTS,
    CpuSlope, HostCpuMeter, STEP_HOLD_SECONDS, STEP_SLOTS, cold_start_slots, connection_headroom,
    RAMP_CONTRACT, prior_cpu_per_slot, ramp_ceiling, ramp_decision)


def decide(**overrides):
    base = dict(
        active=32, baseline=32, ceiling=64,
        host_cpu_percent=50.0,
        available_bytes=40 * GIB, floor_bytes=10 * GIB,
        connection_headroom=60, runnable=500,
        seconds_since_step=STEP_HOLD_SECONDS + 1.0,
    )
    return ramp_decision(**(base | overrides))


def test_an_idle_host_with_queued_work_grows():
    decision = decide()
    assert decision.action == "raise"
    assert decision.slots == 32 + STEP_SLOTS
    assert decision.limiter == "none"


def test_the_cpu_target_stops_it():
    decision = decide(host_cpu_percent=CPU_TARGET_PERCENT)
    assert (decision.action, decision.limiter, decision.slots) == ("hold", "cpu", 32)


def test_past_the_backoff_line_it_gives_a_slot_back():
    decision = decide(host_cpu_percent=99.0)
    assert decision.action == "lower"
    assert decision.slots == 32 - STEP_SLOTS or decision.slots == 32
    assert decision.limiter == "cpu"


def test_it_never_falls_below_its_floor():
    decision = decide(active=8, baseline=8, host_cpu_percent=100.0)
    assert decision.slots == 8
    decision = decide(active=24, baseline=8, host_cpu_percent=100.0)
    assert decision.slots == 24 - STEP_SLOTS


def test_an_automatic_fleet_starts_at_one_step_and_the_floor_is_one_slot():
    assert cold_start_slots(32) == STEP_SLOTS and cold_start_slots(1) == 1
    assert FLOOR_SLOTS == 1


def test_a_learned_step_goes_halfway_to_the_target():
    decision = decide(active=2, baseline=1, running=2, host_cpu_percent=8.0, cpu_per_slot=3.125)
    goal = 2 + int((CPU_TARGET_PERCENT - 8.0) / 3.125)
    assert (decision.action, decision.slots) == ("raise", 2 + -(-(goal - 2) // 2))


def test_it_holds_where_the_learned_cost_puts_the_target():
    slope = 3.0
    running = int((CPU_TARGET_PERCENT - 5.0) / slope)
    decision = decide(active=running + 1, baseline=1, running=running,
                      host_cpu_percent=CPU_TARGET_PERCENT - 4.0, cpu_per_slot=slope)
    assert (decision.action, decision.limiter) == ("hold", "cpu")


def test_over_the_line_it_gives_back_once_and_waits_for_the_jobs():
    first = decide(active=30, baseline=1, running=30, host_cpu_percent=95.0, cpu_per_slot=3.125)
    over = -(-(95.0 - CPU_TARGET_PERCENT) // 3.125)
    assert (first.action, first.slots) == ("lower", 30 - int(over))
    again = decide(active=first.slots, baseline=1, running=30, host_cpu_percent=95.0, cpu_per_slot=3.125)
    assert (again.action, again.slots) == ("hold", first.slots)


def test_slots_not_yet_filled_are_waited_for():
    decision = decide(active=20, baseline=1, running=10, host_cpu_percent=30.0, cpu_per_slot=3.0)
    assert (decision.action, decision.limiter) == ("hold", "filling")


def test_the_cost_of_a_child_is_learned_from_rises_only():
    slope = CpuSlope(3.125)
    slope.mark(2, 8.0)
    assert slope.observe(2, 9.0) is None, "no child has started yet: keep waiting"
    reading = slope.observe(13, 45.0)
    assert reading == pytest.approx(37.0 / 11) and slope.value == pytest.approx(37.0 / 11)
    slope.mark(13, 45.0)
    assert slope.observe(9, 30.0) is None and slope.value == pytest.approx(37.0 / 11), (
        "a lowering says when jobs ended, not what a child costs")
    slope.mark(13, 45.0)
    slope.observe(14, 99.0)
    assert slope.value <= 3.125 * 4, "one wild reading is bounded"


@pytest.mark.parametrize("true_cost,outside", [(3.125, 5.0), (1.6, 12.0), (6.0, 3.0)])
def test_it_finds_its_own_cap_on_a_host_it_has_never_seen(true_cost, outside):
    slope = CpuSlope(prior_cpu_per_slot(32))
    active, running, since = cold_start_slots(32), cold_start_slots(32), 0.0
    seen = []
    for _ in range(120):
        cpu = min(100.0, outside + running * true_cost)
        seen.append(cpu)
        since += 4.0
        if since >= STEP_HOLD_SECONDS:
            slope.observe(running, cpu)
        decision = decide(active=active, baseline=FLOOR_SLOTS, ceiling=64, running=running,
                          host_cpu_percent=cpu, cpu_per_slot=slope.value, seconds_since_step=since)
        if decision.slots != active:
            slope.mark(running, cpu)
            since = 0.0
        active = decision.slots
        running = active
    settled = seen[-30:]
    assert all(CPU_TARGET_PERCENT - 2 * true_cost <= c < CPU_BACKOFF_PERCENT for c in settled), settled
    assert max(seen) < 100.0


def test_the_band_leaves_room_below_the_host_cap():
    assert CPU_TARGET_PERCENT <= 75.0 < CPU_BACKOFF_PERCENT < 90.0


def test_the_memory_floor_stops_it_before_admission_has_to():
    decision = decide(available_bytes=10 * GIB + (GIB // 2), floor_bytes=10 * GIB)
    assert decision.action == "lower"
    assert decision.limiter == "memory"


def test_the_host_memory_rail_is_obeyed_without_waiting_for_the_hold():
    decision = decide(seconds_since_step=0.0, launch_allowed=False,
                      launch_reasons=("memory_psi_full",))
    assert decision.action == "lower"
    assert decision.limiter == "memory"
    assert "memory_psi_full" in decision.reason


def test_an_empty_queue_is_not_a_reason_to_run_more_workers():
    decision = decide(runnable=0)
    assert (decision.action, decision.limiter) == ("hold", "work_supply")


def test_the_connection_budget_is_a_rail_of_its_own():
    decision = decide(connection_headroom=CONNECTIONS_PER_SLOT * STEP_SLOTS - 1)
    assert (decision.action, decision.limiter) == ("hold", "database_connections")


def test_the_ceiling_holds():
    decision = decide(active=64, ceiling=64)
    assert (decision.action, decision.limiter, decision.slots) == ("hold", "ceiling", 64)


def test_a_step_is_measured_before_the_next_one():
    decision = decide(seconds_since_step=STEP_HOLD_SECONDS / 2)
    assert (decision.action, decision.limiter) == ("hold", "settling")


def test_it_does_not_grow_on_a_host_it_has_not_measured_yet():
    decision = decide(host_cpu_percent=None)
    assert (decision.action, decision.limiter) == ("hold", "measuring")


def test_a_paused_fleet_is_left_alone():
    decision = decide(active=0)
    assert (decision.action, decision.limiter) == ("hold", "operator")


def test_a_step_never_crosses_the_ceiling():
    decision = decide(active=63, ceiling=64)
    assert decision.slots == 64


def test_memory_room_bounds_the_step_as_well_as_permitting_it():
    decision = decide(available_bytes=10 * GIB + GIB + (GIB // 2), floor_bytes=10 * GIB)
    assert decision.action == "raise"
    assert decision.slots == 33


def test_every_decision_says_which_thing_decided_it():
    for decision in (decide(), decide(runnable=0), decide(host_cpu_percent=95.0),
                     decide(active=64, ceiling=64), decide(connection_headroom=0)):
        assert decision.reason.strip(), "a limiter without a reason is a shrug"
        assert decision.as_dict()["contract"] == RAMP_CONTRACT == "concurrency-ramp-2"


def test_the_ceiling_is_twice_the_threads_and_never_below_the_start():
    assert ramp_ceiling(baseline=32, logical=32) == 64
    assert ramp_ceiling(baseline=32, logical=1) == 32
    assert ramp_ceiling(baseline=32, logical=32, override=40) == 40
    assert ramp_ceiling(baseline=32, logical=32, override=8) == 32
    assert ramp_ceiling(baseline=1, logical=10 ** 6) == HARD_MAX_SLOTS


def test_the_connection_headroom_keeps_the_services_out_of_the_fleets_budget():
    assert connection_headroom(connections=69, limit=100, reserve=24) == 7
    assert connection_headroom(connections=99, limit=100, reserve=24) == 0


Times = namedtuple("Times", "user nice system idle iowait")


def test_the_cpu_meter_needs_two_samples_and_then_measures_the_window():
    meter = HostCpuMeter()
    assert meter.sample(Times(0, 0, 0, 0, 0)) is None, "one sample is not a window"
    assert meter.sample(Times(30, 0, 10, 60, 0)) == pytest.approx(40.0)
    assert meter.sample(Times(30, 0, 10, 160, 0)) == pytest.approx(0.0)


def test_iowait_is_idle_because_a_waiting_core_is_one_another_child_can_have():
    meter = HostCpuMeter()
    meter.sample(Times(0, 0, 0, 0, 0))
    assert meter.sample(Times(10, 0, 0, 0, 90)) == pytest.approx(10.0)


def test_a_clock_that_did_not_move_reports_nothing_rather_than_zero():
    meter = HostCpuMeter()
    meter.sample(Times(1, 0, 1, 1, 1))
    assert meter.sample(Times(1, 0, 1, 1, 1)) is None
