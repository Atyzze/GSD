from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ignore_patterns() -> list[str]:
    return [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _is_ignored(relative: str, *, directory: bool = False) -> bool:
    parts = relative.split("/")
    for pattern in _ignore_patterns():
        if pattern.endswith("/"):
            name = pattern.rstrip("/")
            folders = parts if directory else parts[:-1]
            if "/" not in name and any(fnmatch.fnmatch(part, name) for part in folders):
                return True
            if "/" in name and any(fnmatch.fnmatch("/".join(parts[:i]), name) for i in range(1, len(folders) + 1)):
                return True
            continue
        if "/" in pattern:
            if fnmatch.fnmatch(relative, pattern):
                return True
            continue
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def test_everything_the_packager_excludes_is_ignored():
    from tools import package_release as packager

    unprotected: list[str] = []

    for name in sorted(packager.EXCLUDED_NAMES):
        on_disk = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob(name)
                   if p.is_file() and ".git" not in p.parts]
        if on_disk:
            protected = all(_is_ignored(where) for where in on_disk)
        else:
            protected = _is_ignored(name) or any(
                pattern.rstrip("/").rsplit("/", 1)[-1] == name for pattern in _ignore_patterns())
        if not protected:
            unprotected.append(f"EXCLUDED_NAMES: {name}")

    for part in sorted(packager.EXCLUDED_PARTS):
        if part == ".git":
            continue
        if not _is_ignored(part, directory=True):
            unprotected.append(f"EXCLUDED_PARTS: {part}/")

    for suffix in sorted(packager.EXCLUDED_SUFFIXES):
        if not _is_ignored(f"sample{suffix}"):
            unprotected.append(f"EXCLUDED_SUFFIXES: *{suffix}")

    assert not unprotected, (
        "these are kept out of the archive but not ignored by git, so an "
        "applied build deletes a host's copy of each one -- which is how build "
        "363 removed a live cluster's only password:\n  "
        + "\n  ".join(unprotected)
    )


def test_the_credentials_file_is_named_in_both_places():
    from tools import package_release as packager

    assert ".env.postgres" in packager.EXCLUDED_NAMES, "an archive must never carry it"
    assert ".env.postgres" in _ignore_patterns(), "and a host must never lose it"


def test_the_gitignore_states_the_recovery():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "reset-credentials" in text
    assert "apply-build" in text, "the deletion rule this file exists to explain"


@pytest.mark.parametrize("relative", [".env.postgres"])
def test_host_state_is_not_in_the_archive_either(relative):
    from tools import package_release as packager

    assert not packager.include_in_release(ROOT / relative)
    assert _is_ignored(relative)


def test_the_durable_calibration_table_is_gitignored():
    ignore = ROOT / ".gitignore"
    assert ignore.is_file(), (
        "package_release.py has listed .gitignore as an expected root file since "
        "the project was packaged and there was never one")
    lines = [l.strip() for l in ignore.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    assert "calibration/probe_calibration.json" in lines
    for runtime in ("var/", "instance/"):
        assert runtime in lines, f"{runtime} is runtime state"


def test_the_gitignore_says_why_rather_than_only_what():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deletion candidates" in text, (
        "the reason is the deploy tool's deletion rule, not publishing; a future "
        "reader who thinks this is about GitHub will delete the line")


def test_a_file_git_does_not_track_is_left_out_of_the_archive_and_named(tmp_path, monkeypatch):
    import subprocess

    from tools import package_release as packager
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "kept.py").write_text("x = 1\n")
    (tmp_path / "tools" / "left_over_reading.json").write_text("{}\n")
    (tmp_path / "README.md").write_text("a tree\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "tools/kept.py", "README.md"], check=True)
    monkeypatch.setattr(packager, "ROOT", tmp_path)
    shipped = [path.relative_to(tmp_path).as_posix() for path in packager.release_paths()]
    assert shipped == ["README.md", "tools/kept.py"], "host state left in the tree is not shipped"
    assert packager.left_untracked() == ["tools/left_over_reading.json"], "and the release names it"
    (tmp_path / ".git").rename(tmp_path / "not-git")
    assert len(packager.release_paths()) == 3, "an unpacked archive with no git ships what it holds"
