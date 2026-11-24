from __future__ import annotations

import math
from dataclasses import dataclass

GIB = 1024 ** 3

RAMP_CONTRACT = "concurrency-ramp-2"

CPU_TARGET_PERCENT = 75.0
CPU_BACKOFF_PERCENT = 83.0
FLOOR_SLOTS = 1
SLOPE_WEIGHT = 0.5
SLOPE_BOUND = 4.0
STEP_SLOTS = 2
STEP_HOLD_SECONDS = 20.0
SLOT_RESERVE_BYTES = 1 * GIB
CONNECTIONS_PER_SLOT = 3
CONNECTION_RESERVE = 24
CEILING_MULTIPLIER = 2
HARD_MAX_SLOTS = 256


def ramp_ceiling(*, baseline: int, logical: int, override: int | None = None,
                 multiplier: int = CEILING_MULTIPLIER) -> int:
    baseline = max(1, int(baseline))
    logical = max(1, int(logical))
    if override is not None:
        return max(baseline, min(HARD_MAX_SLOTS, int(override)))
    return max(baseline, min(HARD_MAX_SLOTS, int(multiplier) * logical))


def cold_start_slots(slots_available: int) -> int:
    return max(1, min(int(slots_available), STEP_SLOTS))


def prior_cpu_per_slot(logical: int) -> float:
    return 100.0 / max(1, int(logical))


class CpuSlope:
    def __init__(self, prior: float, *, value: float | None = None, samples: int = 0):
        self.prior = float(prior)
        self.value = float(value) if value else self.prior
        self.samples = int(samples)
        self._mark: tuple[int, float] | None = None

    def mark(self, running: int, cpu: float | None) -> None:
        self._mark = None if cpu is None else (int(running), float(cpu))

    def observe(self, running: int, cpu: float | None) -> float | None:
        if self._mark is None or cpu is None:
            return None
        before_running, before_cpu = self._mark
        added = int(running) - before_running
        if added == 0:
            return None
        self._mark = None
        rise = float(cpu) - before_cpu
        if added < 0 or rise <= 0:
            return None
        reading = min(max(rise / added, self.prior / SLOPE_BOUND), self.prior * SLOPE_BOUND)
        self.value = reading if self.samples == 0 else (
            SLOPE_WEIGHT * reading + (1.0 - SLOPE_WEIGHT) * self.value)
        self.samples += 1
        return reading

    def as_dict(self) -> dict:
        return {"cpu_per_slot": round(self.value, 4), "samples": self.samples,
                "prior": round(self.prior, 4)}


@dataclass(frozen=True)
class RampDecision:
    slots: int
    action: str
    limiter: str
    reason: str

    def as_dict(self) -> dict:
        return {"slots": self.slots, "action": self.action,
                "limiter": self.limiter, "reason": self.reason,
                "contract": RAMP_CONTRACT}


def _gib(value: float | int | None) -> str:
    return f"{max(0, int(value or 0)) / GIB:.1f} GiB"


def ramp_decision(*, active: int, baseline: int, ceiling: int,
                  host_cpu_percent: float | None,
                  available_bytes: int, floor_bytes: int,
                  connection_headroom: int, runnable: int,
                  seconds_since_step: float,
                  launch_allowed: bool = True,
                  launch_reasons: tuple[str, ...] = (),
                  cpu_target: float = CPU_TARGET_PERCENT,
                  cpu_backoff: float = CPU_BACKOFF_PERCENT,
                  step: int = STEP_SLOTS,
                  slot_reserve_bytes: int = SLOT_RESERVE_BYTES,
                  step_hold_seconds: float = STEP_HOLD_SECONDS,
                  running: int | None = None,
                  cpu_per_slot: float | None = None) -> RampDecision:
    active = max(0, int(active))
    baseline = max(1, int(baseline))
    ceiling = max(baseline, int(ceiling))
    step = max(1, int(step))
    runnable = max(0, int(runnable))
    headroom_bytes = int(available_bytes) - int(floor_bytes)

    def at(slots: int, action: str, limiter: str, reason: str) -> RampDecision:
        return RampDecision(slots=max(baseline, min(ceiling, int(slots))),
                            action=action, limiter=limiter, reason=reason)

    if active <= 0:
        return at(active, "hold", "operator", "the fleet is paused")

    lowered = max(baseline, active - step)
    if not launch_allowed:
        return at(lowered, "lower", "memory",
                  "the host memory rail refuses new children: "
                  + (", ".join(launch_reasons) or "unspecified"))
    if headroom_bytes < int(slot_reserve_bytes):
        return at(lowered, "lower", "memory",
                  f"{_gib(available_bytes)} available is within {_gib(slot_reserve_bytes)} of the "
                  f"{_gib(floor_bytes)} floor")
    running_now = active if running is None else max(0, int(running))
    slope = float(cpu_per_slot) if cpu_per_slot and float(cpu_per_slot) > 0 else None
    if host_cpu_percent is not None and float(host_cpu_percent) >= float(cpu_backoff):
        cpu = float(host_cpu_percent)
        if slope is None:
            return at(lowered, "lower", "cpu",
                      f"host CPU {cpu:.1f}% is past the {cpu_backoff:.0f}% backoff line")
        goal = max(baseline, running_now - math.ceil((cpu - float(cpu_target)) / slope))
        if goal >= active:
            return at(active, "hold", "cpu",
                      f"host CPU {cpu:.1f}% is past the {cpu_backoff:.0f}% line with {running_now} "
                      f"child(ren) running; the {active} slot(s) left already fit the target once "
                      "the jobs over it end")
        return at(goal, "lower", "cpu",
                  f"host CPU {cpu:.1f}% is past the {cpu_backoff:.0f}% line; at {slope:.2f}% of the "
                  f"host a child, {goal} slot(s) bring it to the {cpu_target:.0f}% target")

    if runnable < 1:
        return at(active, "hold", "work_supply",
                  "no queued simulation or analysis work for another slot")
    if active >= ceiling:
        return at(active, "hold", "ceiling",
                  f"at the {ceiling}-slot ceiling; past it a child mostly takes wall-clock "
                  "from the children already running")
    if int(connection_headroom) < CONNECTIONS_PER_SLOT * step:
        return at(active, "hold", "database_connections",
                  f"{int(connection_headroom)} PostgreSQL connection(s) spare, and a slot can hold "
                  f"{CONNECTIONS_PER_SLOT}")
    if host_cpu_percent is None:
        return at(active, "hold", "measuring", "no host CPU sample yet")
    if float(host_cpu_percent) >= float(cpu_target):
        return at(active, "hold", "cpu",
                  f"host CPU {float(host_cpu_percent):.1f}% is at the {cpu_target:.0f}% target")
    if float(seconds_since_step) < float(step_hold_seconds):
        return at(active, "hold", "settling",
                  f"{float(seconds_since_step):.0f}s since the last step, of {step_hold_seconds:.0f}s")

    if running is not None and running_now < active - step:
        return at(active, "hold", "filling",
                  f"{running_now} of {active} slot(s) are running; the rest are still being filled")
    want = step
    if slope is not None:
        goal = running_now + int((float(cpu_target) - float(host_cpu_percent)) / slope)
        if goal <= active:
            return at(active, "hold", "cpu",
                      f"at {slope:.2f}% of the host a child, the {cpu_target:.0f}% target is "
                      f"{goal} slot(s); the fleet is at {active}")
        want = max(step, math.ceil((goal - active) / 2))
    room = min(want,
               ceiling - active,
               headroom_bytes // max(1, int(slot_reserve_bytes)),
               int(connection_headroom) // CONNECTIONS_PER_SLOT)
    if room < 1:
        return at(active, "hold", "memory",
                  f"{_gib(headroom_bytes)} above the floor is under one slot's "
                  f"{_gib(slot_reserve_bytes)}")
    return at(active + room, "raise", "none",
              f"host CPU {float(host_cpu_percent):.1f}% under the {cpu_target:.0f}% target, "
              f"{_gib(headroom_bytes)} above the memory floor, {runnable} item(s) queued")


class HostCpuMeter:
    def __init__(self) -> None:
        self._previous: tuple[float, float] | None = None

    @staticmethod
    def _totals(times) -> tuple[float, float]:
        idle = float(getattr(times, "idle", 0.0)) + float(getattr(times, "iowait", 0.0))
        return float(sum(float(value) for value in times)), idle

    def sample(self, times=None) -> float | None:
        if times is None:
            import psutil
            times = psutil.cpu_times()
        current = self._totals(times)
        previous, self._previous = self._previous, current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - (idle_delta / total_delta))))


def connection_headroom(*, connections: int, limit: int,
                        reserve: int = CONNECTION_RESERVE) -> int:
    return max(0, int(limit) - int(connections) - max(0, int(reserve)))
