from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md")) \
    + sorted((ROOT / "docs" / "agent").glob("*.md"))

REQUIRED = ("README.md", "docs/agent/HANDOFF.md", "docs/agent/ENVIRONMENT.md",
            "docs/agent/TARGET_ENVIRONMENT.md", "docs/OPERATIONS.md",
            "docs/ROADMAP.md", "docs/ARCHITECTURE.md", "docs/RESEARCH_METHOD.md")


def test_every_document_the_reading_order_names_exists():
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    assert not missing, f"named in the README's reading order and absent: {missing}"


def test_no_document_points_at_a_readme_section_by_number():
    offenders = []
    for doc in DOCS:
        if doc.parent.name == "build_notes":
            continue
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"README section \d", line) and "docs/OPERATIONS.md" not in line:
                offenders.append(f"{doc.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    offenders = [o for o in offenders if "README section 4 is the release" not in o]
    assert not offenders, (
        "point at a file, not at a section number:\n" + "\n".join(offenders))


def test_every_relative_document_link_resolves():
    pattern = re.compile(r"`(docs/[A-Za-z0-9_/]+\.md|README\.md)`")
    broken = []
    for doc in DOCS:
        if doc.parent.name == "build_notes":
            continue
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for target in pattern.findall(line):
                if not (ROOT / target).is_file():
                    broken.append(f"{doc.relative_to(ROOT)}:{n} -> {target}")
    assert not broken, "dangling document references:\n" + "\n".join(broken)


def test_the_operational_recipes_have_exactly_one_home():
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    for recipe in ("benchmark_campaign.py lattice-laws", "campaign start --spec",
                   "campaign use", "rebuild-phenotypes", "campaign provenance"):
        assert recipe in operations, f"{recipe!r} is not in docs/OPERATIONS.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    duplicated = [r for r in ("benchmark_campaign.py lattice-laws", "campaign start --spec")
                  if r in readme]
    assert not duplicated, f"copied back into the README: {duplicated}"


def _headings(text: str) -> set[str]:
    found = {m.group(1).strip().strip("`") for m in re.finditer(r"^#{1,4}\s+(.+?)\s*$", text, re.M)}
    return found | {m.group(1).strip().rstrip(".").strip("`") for m in re.finditer(r"^\*\*([^*]+)\*\*", text, re.M)}


def test_every_section_a_document_names_exists():
    pattern = re.compile(r'`((?:docs/[A-Za-z0-9_/]+|README)\.md)`,\s+(?:section\s+(\d+)|"([^"]+)")')
    broken = []
    for doc in DOCS:
        for target, number, title in pattern.findall(" ".join(doc.read_text(encoding="utf-8").split())):
            if not (ROOT / target).is_file():
                continue
            text = (ROOT / target).read_text(encoding="utf-8")
            if number:
                found = re.search(rf"^## {number}\b", text, re.M) is not None
            else:
                name = title.rstrip(".,")
                found = any(h == name or h.startswith(name) for h in _headings(text))
            if not found:
                broken.append(f"{doc.relative_to(ROOT)} -> {target}, {title or 'section ' + number}")
    assert not broken, "a document names a section that is not there (renamed or cut?):\n" + "\n".join(broken)
