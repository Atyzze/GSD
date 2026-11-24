from __future__ import annotations

import json
import math
import os

TELEMETRY_AGGREGATION_CONTRACT = "gsd-telemetry-aggregation-2"

_SUM_FIELDS = ("interval_seconds", "interval_energy_j")
_MEAN_FIELDS = (
    "cpu_percent", "gsd_cpu_percent", "external_cpu_percent_estimate",
    "cpu_package_watts", "cpu_power_limit_watts", "cpu_temperature_celsius",
    "cpu_frequency_mhz", "memory_total_bytes", "memory_used_bytes",
    "memory_free_bytes",
)
_LAST_FIELDS = (
    "campaign_id", "telemetry_contract", "build_number", "runtime_fingerprint",
    "environment_fingerprint", "sampled_utc", "phase", "quality", "source",
    "memory_bandwidth", "active_work", "active_simulations", "active_analyses",
    "active_slot_limit", "governor_phase", "calibration_id",
)


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _work_identity(work) -> str:
    if not isinstance(work, list):
        return "[]"
    items = []
    for entry in work:
        if not isinstance(entry, dict):
            items.append(repr(entry))
            continue
        items.append(json.dumps(
            {k: entry.get(k) for k in (
                "type", "work_id", "campaign_id", "candidate_id", "n", "seed",
                "owner", "stage", "requested_by", "lease_generation",
                "producer_job", "status",
            )},
            sort_keys=True, separators=(",", ":"), default=str,
        ))
    return json.dumps(sorted(items), separators=(",", ":"))


def _minute_identity(sampled_utc) -> str:
    text = str(sampled_utc or "")
    return text[:16] if len(text) >= 16 else text


def attribution_key(sample: dict) -> tuple:
    availability = tuple(sample.get(field) is not None for field in _MEAN_FIELDS)
    return (
        str(sample.get("campaign_id")),
        str(sample.get("phase")),
        str(sample.get("quality")),
        str(sample.get("governor_phase")),
        sample.get("active_slot_limit"),
        sample.get("calibration_id"),
        str(sample.get("telemetry_contract")),
        int(sample.get("build_number") or 0),
        str(sample.get("runtime_fingerprint")),
        str(sample.get("environment_fingerprint")),
        int(sample.get("active_simulations") or 0),
        int(sample.get("active_analyses") or 0),
        _work_identity(sample.get("active_work")),
        availability,
        _minute_identity(sample.get("sampled_utc")),
    )


class TelemetryAggregator:
    def __init__(self, *, max_window_seconds: float | None = None,
                 max_samples: int | None = None):
        if max_window_seconds is None:
            max_window_seconds = float(os.environ.get(
                "GSD_TELEMETRY_MAX_WINDOW_SECONDS", "300"))
        if max_samples is None:
            max_samples = int(os.environ.get("GSD_TELEMETRY_MAX_SAMPLES", "150"))
        self.max_window_seconds = max(0.0, float(max_window_seconds))
        self.max_samples = max(1, int(max_samples))
        self._reset()

    def _reset(self) -> None:
        self._key: tuple | None = None
        self._count = 0
        self._window = 0.0
        self._sums: dict[str, float] = {}
        self._mean_sums: dict[str, float] = {}
        self._mean_counts: dict[str, int] = {}
        self._last: dict = {}
        self._started_utc: str | None = None
        self._power_samples: list[list[float | None]] = []
        self._temperature_max: float | None = None

    def _accumulate(self, sample: dict) -> None:
        if self._started_utc is None:
            self._started_utc = str(sample.get("sampled_utc") or "") or None
        for field in _SUM_FIELDS:
            value = _finite_number(sample.get(field))
            if value is not None:
                self._sums[field] = self._sums.get(field, 0.0) + value
        for field in _MEAN_FIELDS:
            value = _finite_number(sample.get(field))
            if value is not None:
                self._mean_sums[field] = self._mean_sums.get(field, 0.0) + value
                self._mean_counts[field] = self._mean_counts.get(field, 0) + 1
        interval = _finite_number(sample.get("interval_seconds"))
        if interval is not None:
            self._window += interval
        watts = _finite_number(sample.get("cpu_package_watts"))
        limit = _finite_number(sample.get("cpu_power_limit_watts"))
        self._power_samples.append([watts, limit])
        temp = _finite_number(sample.get("cpu_temperature_celsius"))
        if temp is not None:
            self._temperature_max = temp if self._temperature_max is None else max(self._temperature_max, temp)
        self._last = dict(sample)
        self._count += 1

    def _emit(self) -> dict | None:
        if not self._count:
            return None
        row = {field: self._last.get(field) for field in _LAST_FIELDS}
        for field in _SUM_FIELDS:
            row[field] = self._sums.get(field)
        for field in _MEAN_FIELDS:
            count = self._mean_counts.get(field, 0)
            row[field] = (self._mean_sums[field] / count) if count else None
        for field in ("memory_total_bytes", "memory_used_bytes", "memory_free_bytes"):
            if isinstance(row.get(field), float):
                row[field] = int(round(row[field]))
        row.update({
            "aggregated_samples": self._count,
            "window_seconds": self._window or None,
            "window_started_utc": self._started_utc,
            "aggregation_contract": TELEMETRY_AGGREGATION_CONTRACT,
            "power_samples": list(self._power_samples),
            "cpu_temperature_max_celsius": self._temperature_max,
        })
        self._reset()
        return row

    def _bounded(self) -> bool:
        if self._count >= self.max_samples:
            return True
        return bool(self.max_window_seconds) and self._window >= self.max_window_seconds

    def add(self, sample: dict) -> dict | None:
        key = attribution_key(sample)
        emitted = None
        if self._key is not None and key != self._key:
            emitted = self._emit()
        self._key = key
        self._accumulate(sample)
        if emitted is None and self._bounded():
            emitted = self._emit()
        return emitted

    def drain(self) -> dict | None:
        return self._emit()


def expand_aggregate_row(row: dict) -> list[dict]:
    item = dict(row)
    count = max(1, int(item.get("aggregated_samples") or 1))
    if count <= 1:
        return [item]
    power_samples = item.get("power_samples") or []
    if not isinstance(power_samples, list) or len(power_samples) != count:
        power_samples = [[item.get("cpu_package_watts"), item.get("cpu_power_limit_watts")]] * count
    interval = item.get("interval_seconds")
    energy = item.get("interval_energy_j")
    per_interval = (float(interval) / count) if isinstance(interval, (int, float)) and not isinstance(interval, bool) else None
    per_energy = (float(energy) / count) if isinstance(energy, (int, float)) and not isinstance(energy, bool) else None
    started = item.get("window_started_utc") or item.get("sampled_utc")
    ended = item.get("sampled_utc")
    out: list[dict] = []
    for index in range(count):
        expanded = dict(item)
        expanded["aggregate_source_samples"] = count
        expanded["aggregated_samples"] = 1
        expanded["window_seconds"] = per_interval
        expanded["interval_seconds"] = per_interval
        expanded["interval_energy_j"] = per_energy
        expanded["sampled_utc"] = ended if index == count - 1 else started
        pair = power_samples[index] if isinstance(power_samples[index], list) else []
        expanded["cpu_package_watts"] = pair[0] if len(pair) > 0 else item.get("cpu_package_watts")
        expanded["cpu_power_limit_watts"] = pair[1] if len(pair) > 1 else item.get("cpu_power_limit_watts")
        expanded["power_samples"] = [pair]
        out.append(expanded)
    return out
