from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.research import compute_by_regime as C  # noqa: E402


def test_the_share_is_split_by_regime_rung_and_rule():
    by_rung = [
        {"work_kind": "simulation", "n": 64, "zero_temperature": True, "attempts": 30, "laws": 10, "core_seconds": 300.0},
        {"work_kind": "simulation", "n": 64, "zero_temperature": False, "attempts": 90, "laws": 30, "core_seconds": 600.0},
        {"work_kind": "analysis", "n": 64, "zero_temperature": False, "attempts": 90, "laws": 30, "core_seconds": 100.0},
        {"work_kind": "report", "n": None, "zero_temperature": None, "attempts": 2, "laws": 0, "core_seconds": 0.0},
    ]
    laws = ([{"zero_temperature": True, "rule": "failed", "top_n": 64}] * 10
            + [{"zero_temperature": False, "rule": "unsettled", "top_n": 4096}] * 30)
    summary = C.summarise(by_rung, laws)
    assert summary["laws"]["zero_temperature"] == 10 and summary["law_share"]["zero_temperature"] == 0.25
    assert summary["core_second_share"]["zero_temperature"] == 0.3
    assert summary["by_rung"]["zero_temperature"]["simulation:64"]["core_seconds"] == 300.0
    assert summary["by_rule"]["zero_temperature"] == {"failed": 10}
    assert summary["readings"][0].startswith("zero temperature: 10 of 40 laws (25.0%)")
    assert "N=64 (10 laws)" in summary["readings"][1]


def test_a_folder_with_no_zero_temperature_law_says_so_plainly():
    summary = C.summarise([], [{"zero_temperature": False, "rule": "unsettled", "top_n": 64}])
    assert summary["readings"] == ["zero temperature: 0 of 1 laws (0.0%) and 0.0 of 0.0 core hours (0.0%)"]
