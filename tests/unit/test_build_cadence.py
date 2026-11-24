from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BEHAVIOUR = ("graph_scale_dynamics/", "engine_rs/src/", "tools/", "main.py")


def _build() -> int:
    return int((ROOT / "BUILD_NUMBER").read_text(encoding="utf-8").strip())


def _cadence() -> str:
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "## Build cadence" in roadmap, "the roadmap lost its build cadence section"
    section = roadmap.split("## Build cadence", 1)[1]
    return section.split("\n## ", 1)[0]


def _type(build: int) -> str | None:
    notes = ROOT / "docs" / "build_notes" / f"BUILD{build}_NOTES.md"
    if not notes.is_file():
        return None
    kind = re.search(r"^\*\*Type: ([^*\n]+)", notes.read_text(encoding="utf-8"), re.M)
    assert kind, f"{notes.name} must open with a '**Type: ...' line"
    return kind.group(1)


def test_the_roadmap_states_how_a_consolidation_comes_and_plans_none():
    cadence = _cadence()
    assert re.search(r"^Consolidation builds: \S", cadence, re.M), (
        "the roadmap's Build cadence section states how consolidations come, in one line: 'Consolidation builds: ...'")
    assert not re.search(r"^Next consolidation", cadence, re.M), "a consolidation comes when needed, on no schedule"


def test_the_newest_notes_say_what_kind_of_build_this_is():
    build = _build()
    assert any(_type(n) is not None for n in (build, build + 1)), (
        f"neither build {build} nor the one being made has notes with a '**Type: ...' line")


def test_a_consolidation_changes_no_behaviour():
    import json
    record = json.loads((ROOT / "tests" / "fixtures" / "build_files.json").read_text(encoding="utf-8"))
    build = _build()
    for number in (build, build + 1):
        kind = _type(number)
        if kind is None or "consolidation" not in kind.lower() or int(record.get("build") or 0) >= number:
            continue
        import hashlib
        moved = sorted(rel for rel, digest in (record.get("files") or {}).items()
                       if rel.startswith(BEHAVIOUR) and (ROOT / rel).is_file()
                       and hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != digest)
        assert not moved, f"build {number} says it is a consolidation and changes code: {moved[:10]}"
