from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "package_release.py"

DEAD_PID = 2 ** 22

sys.path.insert(0, str(ROOT / "tools"))
import package_release


@pytest.fixture
def tree(tmp_path, monkeypatch):
    (tmp_path / "BUILD_NUMBER").write_text("410\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "410"\n')
    freeze_dir = tmp_path / "tests" / "fixtures"
    freeze_dir.mkdir(parents=True)
    (freeze_dir / "science_freeze.json").write_text('{"baseline_build": 410}\n')
    (tmp_path / "uv.lock").write_text("original-lock\n")

    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    monkeypatch.setattr(package_release, "JOURNAL", tmp_path / "var" / "release_journal.json")
    return tmp_path


def _originals(tree: Path) -> dict:
    return {
        "BUILD_NUMBER": (tree / "BUILD_NUMBER").read_text(),
        "pyproject.toml": (tree / "pyproject.toml").read_text(),
        "science_freeze.json": (tree / "tests" / "fixtures" / "science_freeze.json").read_text(),
        "uv.lock": (tree / "uv.lock").read_text(),
    }


def _simulate_killed_release(tree: Path, number: int) -> None:
    package_release.write_release_journal(number, _originals(tree))
    journal = package_release.JOURNAL
    record = json.loads(journal.read_text())
    record["pid"] = DEAD_PID
    journal.write_text(json.dumps(record))
    (tree / "BUILD_NUMBER").write_text(f"{number}\n")
    (tree / "pyproject.toml").write_text(f'[project]\nversion = "{number}"\n')
    (tree / "tests" / "fixtures" / "science_freeze.json").write_text(
        json.dumps({"baseline_build": number}) + "\n")
    (tree / "uv.lock").write_text("regenerated-lock\n")


def test_an_interrupted_release_is_undone_at_the_next_startup(tree, capsys):
    _simulate_killed_release(tree, 411)
    assert package_release.current_build() == 411, "precondition: the number was spent"

    recovered = package_release.restore_from_journal()

    assert recovered == 411
    assert package_release.current_build() == 410, "the spent number was not returned"
    assert (tree / "pyproject.toml").read_text() == '[project]\nversion = "410"\n'
    assert json.loads((tree / "tests" / "fixtures" / "science_freeze.json").read_text()) == {
        "baseline_build": 410}
    assert (tree / "uv.lock").read_text() == "original-lock\n"
    assert not (tree / "var" / "release_journal.json").exists()
    assert "411" in capsys.readouterr().out


def test_recovery_runs_before_the_next_number_is_computed(tree):
    _simulate_killed_release(tree, 411)
    package_release.restore_from_journal()
    assert package_release.current_build() + 1 == 411, (
        "the next release does not reclaim the number the interrupted run spent")


def test_a_lock_that_did_not_exist_before_is_removed_again(tree):
    originals = _originals(tree) | {"uv.lock": None}
    (tree / "uv.lock").unlink()
    package_release.write_release_journal(412, originals)
    record = json.loads(package_release.JOURNAL.read_text())
    record["pid"] = DEAD_PID
    package_release.JOURNAL.write_text(json.dumps(record))
    (tree / "BUILD_NUMBER").write_text("412\n")
    (tree / "uv.lock").write_text("generated-by-the-failed-run\n")

    package_release.restore_from_journal()

    assert not (tree / "uv.lock").exists()
    assert package_release.current_build() == 410


def test_a_completed_release_leaves_no_journal_to_recover(tree):
    package_release.write_release_journal(411, _originals(tree))
    (tree / "var" / "release_journal.json").unlink()
    (tree / "BUILD_NUMBER").write_text("411\n")

    assert package_release.restore_from_journal() is None
    assert package_release.current_build() == 411, "a delivered build was rolled back"


@pytest.mark.parametrize("content", ["{not json", json.dumps({"contract": "something-else"})])
def test_an_unreadable_journal_does_not_block_a_release(tree, content, capsys):
    journal = tree / "var" / "release_journal.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(content)

    assert package_release.restore_from_journal() is None
    assert "warning" in capsys.readouterr().out.lower()
    assert package_release.current_build() == 410


def test_the_journal_is_written_before_the_bump_not_after():
    source = TOOL.read_text(encoding="utf-8")
    body = source[source.index("def main("):]
    journal_at = body.index("write_release_journal(number")
    bump_at = body.index('build_path.write_text(f"{number}')
    assert journal_at < bump_at, "the journal is written after the tree is mutated"
    recovery_at = body.index("restore_from_journal()")
    reads_build = body.index("original_build = build_path.read_text()")
    assert recovery_at < reads_build, "recovery runs after the current build is read"


def test_the_tool_still_refuses_a_number_at_or_below_the_current_build():
    result = subprocess.run(
        [sys.executable, str(TOOL), "--number", "1", "--skip-tests"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "is spent" in (result.stdout + result.stderr)


def test_a_leaked_fleet_lock_is_reported_as_an_environment_precondition():
    import subprocess as sp

    from tests.integration.slice_driver import FLEET_LOCK_HELD, require

    refused = sp.CompletedProcess(
        args=[], returncode=3,
        stdout=f"Graph Scale Dynamics - Build 308\n[supervisor] refusing to start: {FLEET_LOCK_HELD}\n",
        stderr="")
    with pytest.raises(AssertionError) as caught:
        require(refused, "fleet")
    message = str(caught.value)
    assert "environment precondition" in message
    assert "killed rather than stopped" in message
    assert "fleet failed (3)" not in message


def test_an_ordinary_fleet_failure_still_reports_normally():
    import subprocess as sp

    from tests.integration.slice_driver import require

    with pytest.raises(AssertionError) as caught:
        require(sp.CompletedProcess(args=[], returncode=1,
                                    stdout="worker crashed", stderr="traceback"),
                "fleet")
    message = str(caught.value)
    assert "fleet failed (1)" in message
    assert "environment precondition" not in message


def test_recovery_leaves_a_live_release_alone(tree, capsys):
    import os

    package_release.write_release_journal(411, _originals(tree))
    (tree / "BUILD_NUMBER").write_text("411\n")
    journal = json.loads((tree / "var" / "release_journal.json").read_text())
    assert journal["pid"] == os.getpid(), "the journal does not record its owner"

    assert package_release.restore_from_journal() is None
    assert package_release.current_build() == 411, "a running release was rolled back"
    assert (tree / "var" / "release_journal.json").exists(), (
        "a live release's journal was deleted, so its own rollback can no longer run")
    assert "already running" in capsys.readouterr().out


def test_recovery_proceeds_when_the_owner_is_gone(tree):
    package_release.write_release_journal(411, _originals(tree))
    journal = tree / "var" / "release_journal.json"
    record = json.loads(journal.read_text())
    record["pid"] = DEAD_PID
    journal.write_text(json.dumps(record))
    (tree / "BUILD_NUMBER").write_text("411\n")

    assert package_release.restore_from_journal() == 411
    assert package_release.current_build() == 410


def test_a_journal_without_a_pid_still_recovers(tree):
    package_release.write_release_journal(411, _originals(tree))
    journal = tree / "var" / "release_journal.json"
    record = json.loads(journal.read_text())
    del record["pid"]
    journal.write_text(json.dumps(record))
    (tree / "BUILD_NUMBER").write_text("411\n")

    assert package_release.restore_from_journal() == 411
    assert package_release.current_build() == 410


@pytest.mark.parametrize("pid,expected", [(0, False), (-1, False), (1, True)])
def test_liveness_probe(pid, expected):
    assert package_release._process_alive(pid) is expected


def test_verify_archive_refuses_a_tree_that_answers_to_another_number(tree, monkeypatch):
    (tree / "BUILD_NUMBER").write_text("307\n")
    (tree / "pyproject.toml").write_text('[project]\nversion = "307"\n')
    with pytest.raises(RuntimeError) as caught:
        package_release.verify_archive(308, tree / "gsd_build_308.tar.zst")
    message = str(caught.value)
    assert "named for build 308" in message and "307" in message
    assert "no archive was written that anyone should keep" in message


def test_verify_archive_refuses_a_mismatched_project_version(tree):
    (tree / "BUILD_NUMBER").write_text("308\n")
    (tree / "pyproject.toml").write_text('[project]\nversion = "307"\n')
    with pytest.raises(RuntimeError) as caught:
        package_release.verify_archive(308, tree / "gsd_build_308.tar.zst")
    assert "declares version 307" in str(caught.value)


def test_a_file_changed_after_the_kill_is_left_as_it_is(tree, capsys):
    package_release.write_release_journal(411, _originals(tree))
    (tree / "BUILD_NUMBER").write_text("411\n")
    package_release.journal_written("BUILD_NUMBER")
    (tree / "pyproject.toml").write_text('[project]\nversion = "411"\n')
    package_release.journal_written("pyproject.toml")
    record = json.loads(package_release.JOURNAL.read_text())
    record["pid"] = DEAD_PID
    package_release.JOURNAL.write_text(json.dumps(record))
    (tree / "pyproject.toml").write_text('[project]\nversion = "411"\ndependencies = ["x"]\n')
    (tree / "tests" / "fixtures" / "science_freeze.json").write_text('{"baseline_build": 410, "files": {"a": "b"}}\n')

    assert package_release.restore_from_journal() == 411
    assert package_release.current_build() == 410, "what the killed run wrote is undone"
    assert 'dependencies = ["x"]' in (tree / "pyproject.toml").read_text(), "an edit after the kill is kept"
    assert '"files"' in (tree / "tests" / "fixtures" / "science_freeze.json").read_text()
    out = capsys.readouterr().out
    assert "left as they are, changed since the killed run wrote them" in out and "pyproject.toml" in out


def test_a_kill_between_writing_the_lock_and_journaling_it_still_restores_it(tree, capsys):
    package_release.write_release_journal(411, _originals(tree))
    journal = package_release.JOURNAL
    record = json.loads(journal.read_text())
    record["pid"] = DEAD_PID
    record["written"] = {}
    journal.write_text(json.dumps(record))
    package_release.journal_intended("uv.lock", b"regenerated-lock\n")
    (tree / "uv.lock").write_text("regenerated-lock\n")
    package_release.restore_from_journal()
    assert (tree / "uv.lock").read_text() == "original-lock\n"
    assert "left as they are" not in capsys.readouterr().out


def _notes(tree: Path, number: int, text: str) -> Path:
    path = tree / package_release.REQUIRED_NOTES_DIR / f"BUILD{number}_NOTES.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_run_killed_after_its_gate_line_gives_the_next_run_the_token_back(tree):
    token = package_release.GATE_RESULT_TOKEN
    notes = _notes(tree, 411, f"# Build 411\n\n## Verification\n\n{token}\n")
    package_release.write_release_journal(411, _originals(tree) | {package_release.notes_key(411): notes.read_text()})
    package_release.stamp_gate_result(411, "3269 passed in 700s (fast lane)")
    assert token not in notes.read_text()
    record = json.loads(package_release.JOURNAL.read_text())
    record["pid"], record["pid_started"] = DEAD_PID, None
    package_release.JOURNAL.write_text(json.dumps(record))

    package_release.restore_from_journal()

    assert token in notes.read_text(), "the killed run's gate line survived into the next run's archive"
    package_release.stamp_gate_result(411, "3270 passed in 710s")
    assert "3270 passed" in notes.read_text() and "fast lane" not in notes.read_text()


def test_notes_with_no_token_are_refused_rather_than_shipped_with_another_run_s_line(tree):
    _notes(tree, 411, "# Build 411\n\n## Verification\n\n3269 passed in 700s\n")
    with pytest.raises(RuntimeError, match="another run's"):
        package_release.stamp_gate_result(411, "3270 passed in 710s")


def test_a_reused_pid_is_not_taken_for_the_release_that_wrote_the_journal(tree):
    package_release.write_release_journal(411, _originals(tree))
    record = json.loads(package_release.JOURNAL.read_text())
    record["pid"], record["pid_started"] = 1, "not-the-start-of-pid-1"
    package_release.JOURNAL.write_text(json.dumps(record))
    assert package_release.live_release() is None
    assert package_release.restore_from_journal() == 411


def test_a_live_release_stops_a_second_one_before_it_touches_the_tree(tree):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        package_release.write_release_journal(411, _originals(tree))
        record = json.loads(package_release.JOURNAL.read_text())
        record["pid"], record["pid_started"] = sleeper.pid, package_release._process_start(sleeper.pid)
        package_release.JOURNAL.write_text(json.dumps(record))
        assert package_release.live_release() == (411, sleeper.pid)
        with pytest.raises(SystemExit, match="is running"):
            package_release.main([])
        assert package_release.current_build() == 410
    finally:
        sleeper.kill()
        sleeper.wait()


def test_a_run_the_live_release_started_itself_is_not_a_second_release(tree):
    package_release.write_release_journal(411, _originals(tree))
    record = json.loads(package_release.JOURNAL.read_text())
    record["pid"], record["pid_started"] = os.getppid(), package_release._process_start(os.getppid())
    package_release.JOURNAL.write_text(json.dumps(record))
    assert package_release.live_release() is None


def test_a_release_is_refused_in_a_live_folder_and_with_a_fixture_rewrite_switch_set(tmp_path, monkeypatch):
    from tools import package_release as P
    assert "GSD_WRITE_REPORT_SNAPSHOT_FIXTURE" in P.before_a_release(tmp_path, {"GSD_WRITE_REPORT_SNAPSHOT_FIXTURE": "1"})
    assert P.before_a_release(tmp_path, {}) is None
    monkeypatch.setattr("graph_scale_dynamics.operations.folder_guard.live_in_folder",
                        lambda root: "var/fleet.pid names pid 7, running")
    assert "run them in a fresh folder" in P.before_a_release(tmp_path, {})
