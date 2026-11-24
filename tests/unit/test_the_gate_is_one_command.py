from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import gate, test_suite as suite  # noqa: E402


def _tree(root: Path) -> Path:
    (root / "graph_scale_dynamics" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "BUILD_NUMBER").write_text("41\n")
    (root / "graph_scale_dynamics" / "kept.py").write_text("x = 1\n")
    (root / "graph_scale_dynamics" / "edited.py").write_text("y = 1\n")
    (root / "graph_scale_dynamics" / "gone.py").write_text("z = 1\n")
    (root / "graph_scale_dynamics" / "__pycache__" / "kept.cpython-312.pyc").write_bytes(b"\0")
    return root


def test_the_fast_lane_reads_a_change_against_the_build_s_files(tmp_path):
    root = _tree(tmp_path)
    assert suite.recorded_build(root) is None
    record = suite.write_build_files(41, root)
    assert suite.recorded_build(root) == 41 and record.is_file()
    assert "tests/fixtures/build_files.json" not in suite.release_files(root), "the record leaves itself out"
    assert not any("__pycache__" in path for path in suite.release_files(root)), "only what a release carries"
    assert suite.changed_since_the_build(root) == []
    (root / "graph_scale_dynamics" / "edited.py").write_text("y = 2\n")
    (root / "graph_scale_dynamics" / "gone.py").unlink()
    (root / "graph_scale_dynamics" / "new.py").write_text("w = 1\n")
    assert suite.changed_since_the_build(root) == ["graph_scale_dynamics/edited.py", "graph_scale_dynamics/gone.py",
                                                   "graph_scale_dynamics/new.py"], "changed, gone and new"


def test_the_two_commands_are_the_release_s_lanes():
    full = gate.command("full")
    assert full[-5:] == ["--lane", "all", "--require-postgres", "--shards", "auto"], "the release's full lane"
    assert gate.command("fast")[-3:] == ["--lane", "fast", "--require-postgres"], "against the build's record"
    assert gate.command("fast", since="abc")[-2:] == ["--changed-since", "abc"]
    assert gate.command("full", allow_skips=True)[-1] == "--allow-skips", "a host without a browser"


def test_the_lanes_refuse_a_folder_whose_fleet_runs(monkeypatch, capsys):
    from graph_scale_dynamics.operations import folder_guard
    monkeypatch.setattr(folder_guard, "live_in_folder", lambda root: "this folder's fleet is running (pid 7)")
    ran = []
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: ran.append(a))
    assert gate.main(["full"]) == 2 and not ran
    assert "fresh folder" in capsys.readouterr().out


def test_the_tree_s_record_is_this_build_s_or_the_last():
    from tests.unit.test_build_identity import declared_predecessor
    build = int((ROOT / "BUILD_NUMBER").read_text().strip())
    assert suite.recorded_build() in (None, build, declared_predecessor(build) or build - 1)
