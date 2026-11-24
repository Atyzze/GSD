from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTES_DIR = ROOT / "docs" / "build_notes"
BUILD_NUMBER = ROOT / "BUILD_NUMBER"
PYPROJECT = ROOT / "pyproject.toml"
FREEZE = ROOT / "tests" / "fixtures" / "science_freeze.json"


def current_build() -> int:
    return int(BUILD_NUMBER.read_text(encoding="utf-8").strip())


def test_the_project_version_is_the_build_number():
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert match, "pyproject.toml declares no version"
    assert match.group(1) == str(current_build()), (
        f"pyproject version {match.group(1)!r} does not match BUILD_NUMBER "
        f"{current_build()}. package_release.py writes both together; if they "
        "have drifted, one of them was edited by hand."
    )


def test_this_build_has_notes():
    notes = NOTES_DIR / f"BUILD{current_build()}_NOTES.md"
    assert notes.is_file(), (
        f"no {notes.name} for BUILD_NUMBER {current_build()}. Write the notes in "
        "the same pass as the build, or the number was bumped without a build "
        "behind it."
    )
    body = notes.read_text(encoding="utf-8").strip()
    assert len(body) > 400, f"{notes.name} is a stub; notes are the record, not a placeholder"
    assert "## Verification" in body, (
        f"{notes.name} has no Verification section. Every build states what it "
        "ran and what the result was; a build that cannot be verified from the "
        "dashboard or a report bundle is too big and should be split."
    )


def declared_predecessor(number: int) -> int | None:
    notes = NOTES_DIR / f"BUILD{number}_NOTES.md"
    if not notes.is_file():
        return None
    match = re.search(r"^Follows build:\s*(\d+)\s*$", notes.read_text(encoding="utf-8"),
                      flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def test_the_previous_build_also_has_notes():
    declared = declared_predecessor(current_build())
    previous = current_build() - 1 if declared is None else declared
    assert previous < current_build(), "a build cannot follow itself or a later number"
    notes = NOTES_DIR / f"BUILD{previous}_NOTES.md"
    assert notes.is_file(), (
        f"BUILD_NUMBER is {current_build()} but there is no BUILD{previous}_NOTES.md. "
        "Either a number was spent by a failed release run, or a build shipped "
        "without an account of itself."
    )


def test_a_numbering_restart_is_declared_not_implied():
    declared = declared_predecessor(current_build())
    if declared is None:
        return
    orphans = sorted(
        int(m.group(1))
        for path in NOTES_DIR.glob("BUILD*_NOTES.md")
        if (m := re.fullmatch(r"BUILD(\d+)_NOTES\.md", path.name))
        and declared < int(m.group(1)) < current_build()
    )
    assert not orphans, (
        f"BUILD{current_build()} declares it follows {declared}, but notes exist for "
        f"{orphans} in between. Those numbers were used or the declaration is wrong."
    )


def test_the_freeze_is_anchored_at_this_build():
    baseline = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert baseline["baseline_build"] == current_build(), (
        f"the freeze was taken at build {baseline['baseline_build']}, tree says "
        f"{current_build()}; run `python tools/science_freeze.py --write`"
    )


def test_no_build_notes_claim_a_number_more_than_one_ahead():
    ahead = sorted(
        int(m.group(1))
        for path in NOTES_DIR.glob("BUILD*_NOTES.md")
        if (m := re.fullmatch(r"BUILD(\d+)_NOTES\.md", path.name))
        and int(m.group(1)) > current_build() + 1
    )
    assert not ahead, (
        f"build notes exist more than one number ahead of BUILD_NUMBER "
        f"{current_build()}: " + ", ".join(str(n) for n in ahead)
        + ". One ahead is a build waiting to be released; two is a number that "
        "was skipped or a release that never happened."
    )


HANDOFF_MAX_LAG = 10


def test_the_handoff_describes_a_recent_build():
    import re

    build = int((ROOT / "BUILD_NUMBER").read_text().strip())
    handoff = ROOT / "docs" / "agent" / "HANDOFF.md"
    assert handoff.is_file(), "docs/agent/HANDOFF.md is the pre-build companion to the notes"
    first = handoff.read_text(encoding="utf-8").splitlines()[0]
    match = re.search(r"build\s+(\d+)", first)
    assert match, (
        f"the handoff's first line must name the build it describes; it reads {first!r}")
    described = int(match.group(1))
    assert described <= build + 1, (
        f"the handoff claims build {described} and this tree is {build}")
    assert build - described <= HANDOFF_MAX_LAG, (
        f"the handoff describes build {described} and this is build {build}, "
        f"{build - described} behind. Rewrite it for the current state, or if "
        "nothing material has changed, restate its first line at this build and "
        "say so in the notes. It opens with 'this is what is true'.")
