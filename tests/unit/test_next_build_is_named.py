from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEXT = ROOT / "docs" / "agent" / "NEXT_BUILD.md"


def _current_build() -> int:
    return int((ROOT / "BUILD_NUMBER").read_text(encoding="utf-8").strip())


def test_the_next_build_is_named_and_is_the_next_one():
    assert NEXT.exists(), "docs/agent/NEXT_BUILD.md is the page that says what to do next"
    heading = NEXT.read_text(encoding="utf-8").splitlines()[0]
    match = re.match(r"# The next build is (\d+)$", heading.strip())
    assert match, f"the first line must name the next build; it reads {heading!r}"
    assert int(match.group(1)) in (_current_build() + 1, _current_build() + 2), (
        f"NEXT_BUILD.md describes build {match.group(1)} while the tree is at "
        f"{_current_build()}. Rewrite it for the build after this one: a page that "
        "describes a build already shipped is worse than no page, because it will be "
        "believed.")


def test_it_says_what_the_work_is_and_what_blocks_it():
    body = NEXT.read_text(encoding="utf-8")
    for required in ("## How to make a build", "GATE_RESULT", "setsid nohup",
                     "prepare_environment.sh", "Acceptance"):
        assert required in body, f"NEXT_BUILD.md does not mention {required!r}"
    assert "blocker" in body.lower(), (
        "an instruction without its known obstacles sends the next reader to "
        "rediscover them, which is what this file exists to stop")


def test_the_release_procedure_matches_the_packager():
    body = NEXT.read_text(encoding="utf-8")
    packager = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert "GATE_RESULT" in packager, "the packager no longer substitutes the gate token"
    assert "tools/package_release.py" in body
    assert "science_freeze.py --write" in body and "science_freeze.py" in str(
        sorted(p.name for p in (ROOT / "tools").glob("science_freeze.py")))
