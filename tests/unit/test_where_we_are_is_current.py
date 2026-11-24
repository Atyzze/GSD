from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "WHERE_WE_ARE.md"
MAX_LINES = 90


def test_the_page_names_the_build_being_released():
    build = int((ROOT / "BUILD_NUMBER").read_text().strip())
    first = PAGE.read_text(encoding="utf-8").splitlines()[0]
    match = re.fullmatch(r"# Where we are, at build (\d+)", first.strip())
    assert match, f"the first line names the build; it reads {first!r}"
    assert int(match.group(1)) in (build, build + 1), (
        f"WHERE_WE_ARE.md describes build {match.group(1)} and this tree is {build}: rewrite it for this build")


def test_the_page_is_one_page_in_the_operator_s_style():
    text = PAGE.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= MAX_LINES, "one page; the detail belongs in the handoff"
    assert "—" not in text and "–" not in text, "no long dashes"
    for heading in ("## The question", "## What we know", "## What is running", "## What comes next",
                    "## The decision in front of you"):
        assert heading in text, heading


def test_the_readme_sends_the_operator_to_it_first():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.index("docs/WHERE_WE_ARE.md") < readme.index("docs/agent/HANDOFF.md")
