from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from graph_scale_dynamics.scheduling.memory import (
    DEFAULT_PROCESS_INTERCEPT_FLOOR_BYTES, host_memory_launch_guard, system_memory,
)

GIB = 1024 ** 3

BYTES_PER_NODE = 4 * 1024
PROCESS_INTERCEPT_BYTES = int(DEFAULT_PROCESS_INTERCEPT_FLOOR_BYTES)

DECLARED_BOUNDARY_IMPORTS = ("graph_scale_dynamics.scheduling.memory",)


def predicted_cell_bytes(n: int) -> int:
    return PROCESS_INTERCEPT_BYTES + BYTES_PER_NODE * max(1, int(n))


MEASURED_MARGIN = 1.25
SAME_SIZE_MARGIN = 1.10
MEASURED_MIN_N = 65536


def _measured_points(cells: dict | None) -> dict[str, list[tuple[int, int]]]:
    measured: dict[str, list[tuple[int, int]]] = {}
    for cell in (cells or {}).values():
        rss, n = cell.get("peak_rss_bytes"), cell.get("n")
        if not isinstance(rss, int) or not isinstance(n, int) or n < MEASURED_MIN_N or cell.get("status") != "ok":
            continue
        measured.setdefault(str(cell.get("family")), []).append((n, rss))
    return measured


def cell_pricing(cells: dict | None):
    measured = _measured_points(cells)

    def price(family: str, n: int) -> tuple[int, str]:
        points = measured.get(family)
        if not points:
            return predicted_cell_bytes(n), "the 4 KiB per node model"
        n = max(1, int(n))
        same = [peak for size, peak in points if size == n]
        if same:
            return int(SAME_SIZE_MARGIN * max(same)), "measured at this size on this family"
        smaller = [(size, peak) for size, peak in points if size < n]
        if smaller:
            cost = int(MEASURED_MARGIN * max(peak * n / size for size, peak in smaller))
            basis = "measured on this family"
        else:
            cost, basis = predicted_cell_bytes(n), "the 4 KiB per node model"
        larger = [size for size, _peak in points if size > n]
        if larger:
            nearest = min(larger)
            cap = int(SAME_SIZE_MARGIN * max(peak for size, peak in points if size == nearest))
            if cap < cost:
                return cap, "a larger cell measured on this family"
        return cost, basis

    return price


TYPICAL_SHARE = 0.4


def typical_shares(cells: dict | None):
    shares: dict[str, float] = {}
    for cell in (cells or {}).values():
        mean, peak = cell.get("mean_rss_bytes"), cell.get("peak_rss_bytes")
        if (not isinstance(mean, int) or not isinstance(peak, int) or peak <= 0
                or cell.get("status") != "ok" or int(cell.get("n") or 0) < MEASURED_MIN_N):
            continue
        family = str(cell.get("family"))
        shares[family] = max(shares.get(family, 0.0), min(1.0, mean / peak))

    def share(family: str) -> tuple[float, str]:
        if family in shares:
            return shares[family], "its family's recorded memory"
        return TYPICAL_SHARE, "the default share"

    return share


def rss_bytes(pid: int, proc: str = "/proc") -> int | None:
    try:
        text = Path(proc, str(int(pid)), "status").read_text()
    except (OSError, ValueError):
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def remaining_bytes(price: int, held: int | None) -> int:
    return max(0, int(price) - int(held or 0))


SHED_MARGIN_BYTES = 2 * 1024 ** 3


def shed_line(reserve_bytes: int) -> int:
    reserve = max(0, int(reserve_bytes))
    return max(0, reserve - min(SHED_MARGIN_BYTES, reserve // 4))


SPIKE_OVERLAP = 1
PAUSE_MARGIN_BYTES = 2 * GIB
GROWTH_BYTES = 256 * 1024 ** 2
GROWTH_WINDOW_SECONDS = 30.0
MIN_PAUSE_SECONDS = 30.0


@dataclass
class CellMemory:
    key: str
    started: float
    price: int
    typical: int
    held: int = 0
    growth: int = 0
    paused: bool = False
    paused_at: float | None = None
    strict: bool = False
    extra: dict = field(default_factory=dict)


def still_to_take(cells) -> dict:
    cells = list(cells)
    typical_growth = sum(max(0, c.typical - c.held) for c in cells)
    spikes = sorted((max(0, c.price - max(c.typical, c.held)) for c in cells), reverse=True)
    spike_room = sum(spikes[:SPIKE_OVERLAP])
    return {"bytes": typical_growth + spike_room, "typical_growth_bytes": typical_growth,
            "spike_room_bytes": spike_room, "spikes_counted": min(SPIKE_OVERLAP, len(spikes)),
            "cells": len(cells)}


def need_beside(candidate: CellMemory, running) -> int:
    running = list(running)
    if candidate.strict:
        return remaining_bytes(candidate.price, candidate.held) + sum(
            remaining_bytes(c.price, c.held) for c in running)
    return still_to_take([*running, candidate])["bytes"]


def fits_beside(candidate: CellMemory, running, budget: int) -> tuple[bool, int]:
    need = need_beside(candidate, running)
    return need + PAUSE_MARGIN_BYTES <= int(budget), need


def pressure(running, paused, available: int, floor: int) -> list[tuple[str, CellMemory]]:
    running, paused = list(running), list(paused)
    if int(available) < shed_line(floor):
        victims = paused or running
        return [("end", max(victims, key=lambda c: c.started))] if victims else []
    if len(running) < 2:
        return []
    headroom = int(available) - int(floor) - PAUSE_MARGIN_BYTES
    oldest = min(running, key=lambda c: c.started)
    claimed, actions = 0, []
    for cell in sorted((c for c in running if c.growth >= GROWTH_BYTES), key=lambda c: c.started):
        claim = remaining_bytes(cell.price, cell.held)
        if cell is oldest or claimed + claim <= headroom:
            claimed += claim
        else:
            actions.append(("pause", cell))
    return actions


def to_continue(running, paused, available: int, floor: int, now: float) -> CellMemory | None:
    paused = list(paused)
    if not paused:
        return None
    first = min(paused, key=lambda c: c.started)
    running = list(running)
    if not running:
        return first
    if first.paused_at is not None and now - first.paused_at < MIN_PAUSE_SECONDS:
        return None
    headroom = int(available) - int(floor) - PAUSE_MARGIN_BYTES
    claimed = sum(remaining_bytes(c.price, c.held) for c in running if c.growth >= GROWTH_BYTES)
    return first if claimed + remaining_bytes(first.price, first.held) <= headroom else None


def mean_of(samples) -> int | None:
    values = [int(v) for _t, v in samples]
    return int(sum(values) / len(values)) if values else None


def timeline(samples, points: int = 32) -> list[list[int]]:
    samples = [(float(t), int(v)) for t, v in samples]
    if not samples:
        return []
    end = max(t for t, _v in samples) or 1.0
    pieces: dict[int, tuple[float, int]] = {}
    for t, v in samples:
        index = min(points - 1, int(points * t / end)) if end > 0 else 0
        if index not in pieces or v > pieces[index][1]:
            pieces[index] = (t, v)
    return [[int(round(t)), v] for _index, (t, v) in sorted(pieces.items())]


class Admission:
    def __init__(self, *, snapshot=None, guard=None):
        self._snapshot = snapshot or system_memory
        self._guard = guard or (lambda s: host_memory_launch_guard(snapshot=s))

    def decide(self, predicted_bytes: int, inflight_bytes: int, *, need_bytes: int | None = None) -> dict:
        mem = self._snapshot()
        guard = self._guard(mem)
        reserve = int(guard.get("min_available_bytes") or 0)
        budget = max(0, int(mem.available) - reserve)
        counted = int(predicted_bytes) + int(inflight_bytes) if need_bytes is None else int(need_bytes)
        fits_now = counted <= budget
        fits_ever = predicted_bytes <= max(0, int(mem.total) - reserve)
        allowed = bool(guard.get("allowed")) and fits_now
        reason = None
        if not fits_ever:
            reason = (f"host total {mem.total / 1024 ** 3:.1f} GiB minus reserve "
                      f"{reserve / 1024 ** 3:.1f} GiB cannot hold a "
                      f"{predicted_bytes / 1024 ** 3:.1f} GiB cell")
        elif not guard.get("allowed"):
            reason = "host launch guard: " + ", ".join(guard.get("reasons") or ["refused"])
        elif not fits_now and need_bytes is not None:
            reason = (f"available {mem.available / 1024 ** 3:.1f} GiB minus reserve "
                      f"{reserve / 1024 ** 3:.1f} GiB is below the {counted / 1024 ** 3:.1f} GiB the running "
                      "cells and this one may still take, with the pause margin")
        elif not fits_now:
            reason = (f"available {mem.available / 1024 ** 3:.1f} GiB minus reserve "
                      f"{reserve / 1024 ** 3:.1f} GiB is below what the running cells may still take, "
                      f"{inflight_bytes / 1024 ** 3:.1f} GiB, plus {predicted_bytes / 1024 ** 3:.1f} GiB")
        return {"allowed": allowed, "fits_ever": fits_ever, "reason": reason,
                "budget_bytes": budget, "reserve_bytes": reserve, "counted_bytes": counted,
                "available_bytes": int(mem.available), "total_bytes": int(mem.total)}
