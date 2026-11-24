from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import package_release


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def test_scrub_leaves_the_repository_var_and_toolchain_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    kept = [
        tmp_path / ".git" / "HEAD",
        tmp_path / "var" / "release_journal.json",
        tmp_path / "var" / "wheels" / "engine.whl",
        tmp_path / "engine_rs" / "target" / "release" / "lib.so",
        tmp_path / ".venv" / "bin" / "python",
        tmp_path / "graph_scale_dynamics" / "a.py",
        tmp_path / "var" / "build" / "keep.txt",
    ]
    removed = [
        tmp_path / "build" / "lib" / "a.py",
        tmp_path / "dist" / "gsd.whl",
        tmp_path / "gsd.egg-info" / "PKG-INFO",
        tmp_path / "graph_scale_dynamics" / "__pycache__" / "a.pyc",
        tmp_path / "graph_scale_dynamics" / "b.pyc",
    ]
    for path in kept + removed:
        _touch(path)
    package_release.remove_generated_files()
    for path in kept:
        assert path.exists(), path
    for path in removed:
        assert not path.exists(), path


def test_output_accepts_a_directory_or_a_file(tmp_path):
    inside = tmp_path / "releases"
    inside.mkdir()
    assert package_release.release_output_path(inside, 339) == (inside / "GSD339.tar.zst").resolve()
    assert package_release.release_output_path(tmp_path / "new", 339) == (tmp_path / "new" / "GSD339.tar.zst").resolve()
    explicit = tmp_path / "custom.tar.zst"
    assert package_release.release_output_path(explicit, 339) == explicit.resolve()


def test_the_archive_exclusion_list_is_not_the_scrub_list():
    assert ".git" in package_release.EXCLUDED_PARTS
    assert "var" in package_release.EXCLUDED_PARTS
    assert ".git" not in package_release.GENERATED_PARTS
    assert "var" not in package_release.GENERATED_PARTS


def test_gate_result_is_stamped_into_the_notes_and_an_unstamped_note_is_refused(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    notes = tmp_path / package_release.REQUIRED_NOTES_DIR / "BUILD340_NOTES.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("The token `GATE_RESULT` is prose.\n## Verification\n\n    full lane   GATE_RESULT\n",
                     encoding="utf-8")
    with pytest.raises(RuntimeError):
        package_release.refuse_unstamped_notes(340)
    package_release.stamp_gate_result(340, "1046 passed, 2 skipped in 330s")
    assert notes.read_text().count("GATE_RESULT") == 1, "the backticked mention is prose and stays"
    assert "1046 passed" in notes.read_text()
    package_release.refuse_unstamped_notes(340)
    package_release.refuse_unstamped_notes(341)


def test_summary_capture_reads_the_pytest_line(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    script = tmp_path / "fake_lane.py"
    script.write_text("print('....')\nprint('=== 12 passed, 1 skipped in 0.1s ===')\n")
    summary = package_release.run_gate_and_capture_summary([sys.executable, str(script)])
    assert summary == "12 passed, 1 skipped in 0.1s"
