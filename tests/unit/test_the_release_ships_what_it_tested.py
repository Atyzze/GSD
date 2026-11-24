from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "package_release.py"

sys.path.insert(0, str(ROOT / "tools"))
import package_release as P  # noqa: E402


def test_a_tree_that_moved_while_its_lane_ran_is_refused_and_named():
    before = {"a.py": "1", "b.py": "2"}
    P.refuse_an_untested_tree(before, dict(before))
    with pytest.raises(RuntimeError, match=r"\['b.py', 'c.py'\]"):
        P.refuse_an_untested_tree(before, {"a.py": "1", "b.py": "3", "c.py": "4"})


def test_the_tested_tree_leaves_out_only_what_the_release_writes_itself():
    tree = P.tested_tree(P.current_build() + 1)
    assert "graph_scale_dynamics/research/dimension_rule.py" in tree and "tools/package_release.py" in tree
    assert not set(P.RELEASE_WRITES) & set(tree)


def test_a_moved_pin_must_be_named_in_the_notes(tmp_path, monkeypatch):
    record = tmp_path / "build_files.json"
    record.write_text(json.dumps({"files": {"tests/fixtures/committed_readings.json": "0" * 64}}))
    notes = tmp_path / "notes.md"
    monkeypatch.setattr(P, "_tracked_paths", lambda: {"build_files.json": record})
    monkeypatch.setattr(P, "notes_path", lambda number: notes)
    notes.write_text("# a build that says nothing of its pins\n")
    with pytest.raises(RuntimeError, match="committed_readings"):
        P.refuse_unnamed_moves(999)
    notes.write_text("# a build\n\n`tests/fixtures/committed_readings.json` moved: two designs added.\n")
    P.refuse_unnamed_moves(999)
    same = hashlib.sha256((ROOT / "tests/fixtures/committed_readings.json").read_bytes()).hexdigest()
    record.write_text(json.dumps({"files": {"tests/fixtures/committed_readings.json": same}}))
    notes.write_text("# a build that moved no pin\n")
    P.refuse_unnamed_moves(999)


def test_a_release_that_skips_its_checks_spends_no_number():
    before = (ROOT / "BUILD_NUMBER").read_text()
    for flag in ("--skip-tests", "--skip-compile", "--skip-wheel"):
        result = subprocess.run([sys.executable, str(TOOL), flag], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0 and "spends no build number" in (result.stdout + result.stderr), flag
    assert (ROOT / "BUILD_NUMBER").read_text() == before
    assert P.release_output_path(Path("/tmp"), 7, unverified=True).name == "GSD7_unverified.tar.zst"
    assert P.release_output_path(Path("/tmp"), 7).name == "GSD7.tar.zst"


def _small_tree(root: Path) -> Path:
    for rel, text in (("README.md", "a tree\n"), ("BUILD_NUMBER", "7\n"), ("pyproject.toml", 'version = "7"\n'),
                      ("docs/build_notes/BUILD7_NOTES.md", "# Build 7\n"), ("tools/run.sh", "#!/bin/sh\n"),
                      ("tools/a.py", "A = 1\n"), (".env.postgres", "POSTGRES_PASSWORD=the-folder-secret\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (root / "tools/run.sh").chmod(0o775)
    (root / "docs/env").symlink_to("../.env.postgres")
    return root


def _members(archive: Path, tmp: Path) -> tuple[bytes, list]:
    import tarfile
    tar = tmp / f"{archive.name}.tar"
    subprocess.run(["zstd", "-d", "-q", "-f", str(archive), "-o", str(tar)], check=True)
    with tarfile.open(tar) as tf:
        return tar.read_bytes(), tf.getmembers()


@pytest.fixture
def small_tree(tmp_path, monkeypatch):
    tree = _small_tree(tmp_path / "tree")
    monkeypatch.setattr(P, "ROOT", tree)
    monkeypatch.setattr(P, "REQUIRED_RELEASE_PATHS", set())
    monkeypatch.setattr(P, "notes_path", lambda number: tree / "docs" / "build_notes" / f"BUILD{number}_NOTES.md")
    return tree


def test_one_tree_packs_to_the_same_bytes_and_a_link_ships_as_a_link(small_tree, tmp_path):
    import os
    first = P.archive(7, tmp_path / "one" / "GSD7.tar.zst")
    for path in small_tree.rglob("*"):
        os.utime(path, (1_000_000, 1_000_000), follow_symlinks=False)
    second = P.archive(7, tmp_path / "two" / "GSD7.tar.zst")
    assert first.read_bytes() == second.read_bytes(), "two archives of one tree differ"
    raw, members = _members(first, tmp_path)
    assert b"the-folder-secret" not in raw, "a link's target shipped as its content"
    assert [m.name for m in members] == sorted(m.name for m in members)
    link = next(m for m in members if m.name.endswith("/docs/env"))
    assert link.issym() and link.linkname == "../.env.postgres"
    assert {(m.mtime, m.uid, m.gid, m.uname, m.gname) for m in members} == {(P.member_mtime(7), 0, 0, "", "")}
    assert next(m for m in members if m.name.endswith("tools/run.sh")).mode == 0o755
    assert next(m for m in members if m.name.endswith("tools/a.py")).mode == 0o644
    assert P.member_mtime(8) != P.member_mtime(7), "each build's files carry a time of their own"
    P.verify_archive(7, first, tested=P.tested_tree(7))


def test_a_link_out_of_the_tree_is_refused(small_tree, tmp_path):
    (tmp_path / "outside.txt").write_text("not the tree's\n")
    (small_tree / "docs/out").symlink_to("../../outside.txt")
    with pytest.raises(RuntimeError, match="outside the tree"):
        P.archive(7, tmp_path / "GSD7.tar.zst")
    (small_tree / "docs/out").unlink()
    (small_tree / "docs/out").symlink_to(small_tree / "README.md")
    with pytest.raises(RuntimeError, match="outside the tree"):
        P.archive(7, tmp_path / "GSD7.tar.zst")


def test_the_archive_is_checked_against_what_the_lane_tested_not_the_tree_now(small_tree, tmp_path):
    tested = P.tested_tree(7)
    (small_tree / "tools/a.py").write_text("A = 2\n")
    partial = P.archive(7, tmp_path / "GSD7.tar.zst")
    P.verify_archive(7, partial)
    with pytest.raises(RuntimeError, match=r"changed=\['graph_scale_dynamics_build_7/tools/a.py'\]"):
        P.verify_archive(7, partial, tested=tested)
