from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
BUDGET_BYTES = 120_000


def _read_first() -> list[str]:
    text = README.read_text(encoding="utf-8")
    assert "## Read these first" in text, "the README names the pages read first under '## Read these first'"
    block = text.split("## Read these first", 1)[1].split("Then as needed:", 1)[0]
    return re.findall(r"^\s{4}(\S+)", block, re.M)


def _bytes(entry: str) -> int:
    path = ROOT / entry
    if entry.rstrip("/") == "docs/build_notes":
        numbered = sorted(path.glob("BUILD*_NOTES.md"), key=lambda p: int(re.sub(r"\D", "", p.name)))
        return len(numbered[-1].read_bytes())
    text = path.read_text(encoding="utf-8")
    if entry == "docs/agent/ENVIRONMENT.md":
        section = text.split("\n## 10 ", 1)[1]
        text = "## 10 " + re.split(r"\n## (?!#)", section, maxsplit=1)[0]
    return len(text.encode("utf-8"))


def test_the_read_first_set_is_named_and_exists():
    entries = _read_first()
    assert entries[:2] == ["docs/WHERE_WE_ARE.md", "docs/agent/HANDOFF.md"], entries
    for entry in entries:
        assert (ROOT / entry).exists(), f"the README reads {entry} first, and it is not in the tree"


def test_the_read_first_set_stays_under_about_30k_tokens():
    sizes = {"README.md": len(README.read_bytes())} | {entry: _bytes(entry) for entry in _read_first()}
    total = sum(sizes.values())
    assert total <= BUDGET_BYTES, (
        f"the pages read first are {total:,} bytes, past {BUDGET_BYTES:,} (about 30k tokens): {sizes}. Move a fact to "
        "its one home (docs/agent/HANDOFF.md, 'Where everything else lives') rather than adding it to these")
