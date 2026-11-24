from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_the_status_carries_the_new_fields():
    from graph_scale_dynamics.services.api.host import _btop_telemetry_status

    status = _btop_telemetry_status()
    for field in ("frames_without_watts", "cpu_line_without_watts", "config_seeded_from",
                  "config_inherited_keys", "argv", "last_error"):
        assert field in status
