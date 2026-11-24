from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.scheduling.base_block import validate_stage_gate

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = json.loads((ROOT / "tests" / "fixtures" / "campaign_5rung_sparse_survey.json").read_text(encoding="utf-8"))


def _spec(**filters) -> dict:
    spec = json.loads(json.dumps(SHIPPED))
    spec["filters"] = dict(spec["filters"], **filters)
    return spec


@pytest.mark.parametrize("gate, fragment", [
    ({"withhold_from_n": 1024, "until_verdict_at_n": 4096}, "below withhold_from_n"),
    ({"withhold_from_n": 1024, "until_verdict_at_n": 1024}, "below withhold_from_n"),
    ({"withhold_from_n": 64, "until_verdict_at_n": 64}, "first rung"),
    ({"withhold_from_n": 3000, "until_verdict_at_n": 1024}, "not one of the base sizes"),
    ({"withhold_from_n": True, "until_verdict_at_n": 1024}, "positive integer"),
    ({"withhold_from_n": 4096, "until_verdict_at_n": 1024, "contract": "other"}, "contract must be"),
])
def test_a_gate_that_cannot_work_is_refused(gate, fragment):
    spec = json.loads(json.dumps(SHIPPED))
    spec["base_block"]["stage_gate"] = gate
    assert any(fragment in p for p in validate_stage_gate(spec)), validate_stage_gate(spec)
