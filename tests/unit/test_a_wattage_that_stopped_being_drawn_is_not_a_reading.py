from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.operations import power_sidecar
from graph_scale_dynamics.services.api import host as api_host


def _publish(tmp_path: Path, **overrides) -> Path:
    now = time.time()
    payload = {
        "contract": power_sidecar.CONTRACT, "wrote_at": now, "pid": 1, "btop_pid": 2,
        "btop_path": "/usr/bin/btop", "running": True,
        "watts": 88.0, "watts_at": now,
        "temperature_celsius": 62.0, "temperature_at": now, "frame_at": now,
        "frames_without_watts": 0, "cpu_line_without_watts": None, "last_error": None,
        "started_by": "publisher", "exec_inside_scratch_namespace": False,
        "btop_capabilities": ["cap_dac_read_search", "cap_perfmon"],
        "rapl_energy_path": str(power_sidecar.RAPL_ENERGY),
        "rapl_readable_without_capability": False,
        "config_seeded_from": "/home/op/.config/btop/btop.conf", "config_inherited_keys": 40,
        "argv": ["/usr/bin/btop", "--tty_off"],
    }
    payload.update(overrides)
    path = power_sidecar.reading_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_fresh_wattage_is_a_reading(tmp_path):
    _publish(tmp_path)
    reading = power_sidecar.read_published(tmp_path)
    assert reading["published"] is True
    assert reading["watts"] == 88.0
    assert reading["temperature_celsius"] == 62.0
    assert reading["watts_age_seconds"] < 1.0
    assert power_sidecar.why_no_watts(reading) is None


def test_a_wattage_nothing_has_redrawn_is_withdrawn_while_the_temperature_stays(tmp_path):
    now = time.time()
    _publish(tmp_path, wrote_at=now, watts_at=now - 300.0, temperature_at=now, frame_at=now,
             frames_without_watts=600)
    reading = power_sidecar.read_published(tmp_path)

    assert reading["watts"] is None, (
        "a wattage 300 seconds old was returned as the current power. That is the whole "
        "defect: the tile showed 88 W through a fleet going from 99% to 13%.")
    assert reading["watts_withdrawn"] == pytest.approx(300.0, abs=2.0)
    assert reading["temperature_celsius"] == 62.0, (
        "the temperature was drawn in the latest frame and must survive; withdrawing both "
        "would trade a wrong number for a missing one")

    said = power_sidecar.why_no_watts(reading)
    assert said and "600 frame(s) without one" in said and "not the current power" in said


def test_a_publisher_that_stopped_writing_withdraws_everything(tmp_path):
    now = time.time()
    _publish(tmp_path, wrote_at=now - 600.0, watts_at=now - 600.0,
             temperature_at=now - 600.0, frame_at=now - 600.0)
    reading = power_sidecar.read_published(tmp_path)
    assert reading["stale"] is True
    assert reading["watts"] is None and reading["temperature_celsius"] is None


def test_a_missing_or_foreign_file_is_not_read_as_a_reading(tmp_path):
    assert power_sidecar.read_published(tmp_path)["published"] is False
    path = power_sidecar.reading_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"watts": 500.0}), encoding="utf-8")
    assert power_sidecar.read_published(tmp_path)["published"] is False
    path.write_text("{not json", encoding="utf-8")
    assert power_sidecar.read_published(tmp_path)["published"] is False


def test_the_reason_ordering_puts_the_stale_wattage_first(tmp_path):
    now = time.time()
    _publish(tmp_path, watts_at=now - 120.0, frames_without_watts=240)
    said = power_sidecar.why_no_watts(power_sidecar.read_published(tmp_path))
    assert said and said.startswith("btop last drew a wattage")


def test_the_api_serves_the_published_reading_and_its_ages(tmp_path, monkeypatch):
    now = time.time()
    _publish(tmp_path, watts_at=now - 300.0, frames_without_watts=600,
             cpu_line_without_watts="CPU  ####  13%   62 C")
    monkeypatch.setattr(api_host, "PROJECT_ROOT", tmp_path)
    status = api_host._btop_telemetry_status()
    assert status["source"] == "publisher"
    assert status["watts"] is None
    assert status["watts_withdrawn_age_seconds"] == pytest.approx(300.0, abs=2.0)
    assert status["temperature_celsius"] == 62.0
    assert status["frames_without_watts"] == 600
    assert status["no_watts_because"].startswith("btop last drew a wattage")

    watts, temp, detail = api_host._btop_telemetry_snapshot(start=False)
    assert watts is None and temp == 62.0
    assert "btop last drew a wattage" in detail
