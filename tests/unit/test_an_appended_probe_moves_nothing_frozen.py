from __future__ import annotations

import json
import shutil
from pathlib import Path

from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.calibration import ledger_runs as R
from graph_scale_dynamics.calibration import probe_groups as G
from graph_scale_dynamics.domain.science_identity import frozen_paths

ROOT = Path(__file__).resolve().parents[2]


def test_no_appended_probe_is_a_frozen_source_or_in_the_estimator_s_closure():
    assert not [p for p in frozen_paths() if p.startswith(G.APPENDED_DIR)]
    assert not [p for p in FP.measurement_closure(ROOT) if p.startswith(G.APPENDED_DIR)]


def test_the_shipped_table_is_current_under_the_geometry_group_s_fingerprint():
    table = json.loads((ROOT / "calibration" / "seed_table.json").read_text(encoding="utf-8"))
    assert R.table_geometry_fingerprint(table) == G.geometry_fingerprint(ROOT)


def test_every_appended_group_declares_its_own_channels_and_a_version():
    groups = G.appended_groups()
    assert "quantum_walk" in groups
    names = [name for module in groups.values() for name in module.CHANNELS]
    assert len(names) == len(set(names))
    assert not set(names) & set(G.GEOMETRY_CHANNELS)
    assert set(G.current_fingerprints(ROOT)) == {G.GEOMETRY, *groups}


def test_a_group_s_fingerprint_moves_with_its_own_code_and_nothing_else(tmp_path):
    entry = G.group_entry("quantum_walk")
    (tmp_path / entry).parent.mkdir(parents=True)
    shutil.copy(ROOT / entry, tmp_path / entry)
    assert G.group_fingerprint("quantum_walk", tmp_path) == G.group_fingerprint("quantum_walk", ROOT)
    source = (tmp_path / entry).read_text(encoding="utf-8")
    (tmp_path / entry).write_text(source.replace("STARTS = 4", "STARTS = 5"), encoding="utf-8")
    assert G.group_fingerprint("quantum_walk", tmp_path) != G.group_fingerprint("quantum_walk", ROOT)


def test_reformatting_a_group_s_code_does_not_move_its_fingerprint(tmp_path):
    entry = G.group_entry("quantum_walk")
    (tmp_path / entry).parent.mkdir(parents=True)
    source = (ROOT / entry).read_text(encoding="utf-8")
    (tmp_path / entry).write_text(source.replace("\n\n\ndef ", "\n\n\n\ndef "), encoding="utf-8")
    assert G.group_fingerprint("quantum_walk", tmp_path) == G.group_fingerprint("quantum_walk", ROOT)


def test_the_geometry_group_is_measured_by_the_suite_not_by_the_ledger_tool(tmp_path):
    import pytest
    with pytest.raises(G.ProbeGroupError):
        R.measure_missing(tmp_path, G.GEOMETRY, [])
