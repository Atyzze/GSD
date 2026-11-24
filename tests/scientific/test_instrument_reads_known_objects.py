from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration.instrument_check import (
    GATING_CHANNELS, TOP_RUNG_STANDARD, instrument_check,
)
from tests.support.calibration_table import require_table

pytestmark = pytest.mark.scientific

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = ("periodic_ring", "periodic_square_lattice", "periodic_cubic_lattice",
            "periodic_hypercubic_lattice_4d", "sierpinski_gasket",
            "uniform_random_tree", "random_4_regular")


@pytest.fixture(scope="module")
def table():
    return require_table()


@pytest.fixture(scope="module")
def checked(table):
    return instrument_check(table)


def test_the_required_families_are_all_present(table, checked):
    present = set(checked["top_rung"]) | set(table.get("families") or {})
    assert not [name for name in REQUIRED if name not in present]


def test_the_ladder_gate_passes_on_the_host_table(checked):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    assert checked["ladder_verdict"] == "PASS", checked["failing_families"]
    assert checked["failing_families"] == []


def test_the_tables_theory_matches_the_frozen_declaration(checked):
    from graph_scale_dynamics.calibration.owed import recalibration_owed
    predates = "declared family is absent from the table"
    drift = [found for found in checked["theory_drift"]
             if not (recalibration_owed() is not None and found.get("problem") == predates)]
    assert drift == [], "a table that is owed whole may predate a family; nothing else may differ"


def test_d_s_reads_every_analytic_family_within_the_standard(checked):
    misses = [m for m in checked["misses"] if m["channel"] == "d_s"]
    assert misses == [], (
        f"the spectral probe left the {TOP_RUNG_STANDARD:.0%} standard on a known object: "
        + "; ".join(f"{m['family']} reads {m['measured']:.4f} against {m['theory']:.4f} "
                    f"at N={m['n']} ({m['relative_deviation']:.1%})" for m in misses))
    read = {name: ch["d_s"] for name, ch in checked["top_rung"].items() if "d_s" in ch}
    assert len(read) >= 6, f"only {len(read)} families carry a judged d_s reading"


def test_the_expander_still_refuses(checked):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    assert checked["false_confidence"] == [], checked["false_confidence"]
    assert checked["refusals_held"] is True


def test_the_other_probes_are_charted_and_never_gate(checked):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    assert checked["ok"] is True
    charted = [m for m in checked["misses"] if not m["gates"]]
    assert all(m["channel"] in ("d_V", "d_B", "d_w") for m in charted)
    assert all(m["channel"] in GATING_CHANNELS for m in checked["gating_misses"])


def _top(family: str) -> int:
    from graph_scale_dynamics.calibration import owed
    declared = owed.recalibration_owed()
    return int(declared["owed"]["above_nodes"]) if declared else 1048576


def test_a_drifted_spectral_reading_fails_the_check(table):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    broken = copy.deepcopy(table)
    moved = 0
    for cell in broken["cells"].values():
        if cell.get("family") == "periodic_ring" and cell.get("n") == _top("periodic_ring"):
            channel = (cell.get("channels") or {}).get("d_s") or {}
            if channel.get("valid"):
                channel["value"] = 1.4
                moved += 1
    assert moved, "no top-rung ring cells to move; the fixture assumption changed"
    result = instrument_check(broken)
    assert result["ok"] is False
    assert any(m["family"] == "periodic_ring" and m["channel"] == "d_s" and m["gates"]
               for m in result["misses"])


def test_a_confident_expander_fails_the_check(table):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    broken = copy.deepcopy(table)
    answered = 0
    for cell in broken["cells"].values():
        if cell.get("family") == "random_4_regular" and cell.get("n") == min(262144, _top("random_4_regular")):
            channel = (cell.get("channels") or {}).get("d_s")
            if channel is not None:
                channel.update({"valid": True, "value": 2.5, "se": 0.01, "reason": None})
                answered += 1
    assert answered, "no gated expander cells to answer on; the fixture assumption changed"
    result = instrument_check(broken)
    assert result["ok"] is False
    assert result["refusals_held"] is False
    assert any(e["family"] == "random_4_regular" for e in result["false_confidence"])


def test_an_edited_theory_value_fails_the_check(table):
    broken = copy.deepcopy(table)
    broken.setdefault("families", {}).setdefault("periodic_ring", {})["theory"] = {"d_s": 1.4}
    result = instrument_check(broken)
    assert result["ok"] is False
    assert any(d.get("family") == "periodic_ring" for d in result["theory_drift"])


def test_the_baseline_tool_gates_on_this_check():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    done = subprocess.run(
        [sys.executable, "tools/baseline.py", "--skip", "estimators", "--skip", "cost"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "calibration  pass" in done.stdout, done.stdout
