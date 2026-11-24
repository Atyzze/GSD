from __future__ import annotations

import math

import psutil

RESOURCE_TELEMETRY_CONTRACT = "resource-telemetry-2"

_GSD_MODULE_MARKERS = (
    "graph_scale_dynamics.services.executor.main", "graph_scale_dynamics.services.worker.child", "graph_scale_dynamics.services.analyzer.main",
    "graph_scale_dynamics.services.analyzer.child", "graph_scale_dynamics.services.controller.main",
    "graph_scale_dynamics.services.maintenance.main", "graph_scale_dynamics.services.proposer.main",
    "graph_scale_dynamics.services.api.main", "graph_scale_dynamics.services.telemetry.main",
)


def process_cpu_seconds() -> float:
    total = 0.0
    for proc in psutil.process_iter(("cmdline", "cpu_times")):
        try:
            info = proc.info
            cmd = " ".join(str(x) for x in (info.get("cmdline") or ()))
            if not any(marker in cmd for marker in _GSD_MODULE_MARKERS):
                continue
            cpu = info.get("cpu_times")
            if cpu is not None:
                total += float(cpu.user) + float(cpu.system)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return total


def gsd_cpu_percent(previous_cpu_seconds: float | None, current_cpu_seconds: float,
                   elapsed_seconds: float | None) -> float | None:
    if previous_cpu_seconds is None or not elapsed_seconds or elapsed_seconds <= 0:
        return None
    delta = max(0.0, float(current_cpu_seconds) - float(previous_cpu_seconds))
    cpus = max(1, int(psutil.cpu_count(logical=True) or 1))
    return max(0.0, min(100.0, 100.0 * delta / (float(elapsed_seconds) * cpus)))


def sample_quality(*, watts: float | None, phase: str,
                   external_cpu_percent_estimate: float | None) -> str:
    if watts is None or not math.isfinite(float(watts)):
        return "power_unavailable"
    if phase == "baseline":
        return "baseline_observation"
    if external_cpu_percent_estimate is None:
        return "unknown_interference"
    if external_cpu_percent_estimate <= 5.0:
        return "clean"
    if external_cpu_percent_estimate <= 20.0:
        return "noisy"
    return "contaminated"


def interval_energy_j(previous_watts: float | None, watts: float | None,
                      elapsed_seconds: float | None) -> float | None:
    if previous_watts is None or watts is None or not elapsed_seconds or elapsed_seconds <= 0:
        return None
    a, b = float(previous_watts), float(watts)
    if not (math.isfinite(a) and math.isfinite(b) and a >= 0 and b >= 0):
        return None
    return 0.5 * (a + b) * float(elapsed_seconds)


def cpu_frequency_mhz() -> float | None:
    try:
        freq = psutil.cpu_freq()
        value = None if freq is None else float(freq.current)
        return value if value is not None and math.isfinite(value) and value > 0 else None
    except (psutil.Error, OSError, TypeError, ValueError):
        return None
