from __future__ import annotations

import re
from pathlib import Path
from tests.support.readings import readings

ROOT = Path(__file__).resolve().parents[2]
READINGS = readings(ROOT)
INDEX = READINGS / "README.md"


def _named(index: str) -> tuple[set[str], list[re.Pattern]]:
    spans = re.findall(r"`([^`\s]+)`", index)
    names = {span.rsplit("/", 1)[-1] for span in spans}
    patterns = [re.compile(re.escape(name).replace(re.escape("<utc>"), r"[0-9T:-]+Z?") + "$")
                for name in names if "<utc>" in name]
    return names, patterns


def _indexed(name: str, names: set[str], patterns: list[re.Pattern]) -> bool:
    stem = name.rsplit(".", 1)[0]
    candidates = {name, f"{stem}.md", f"{stem}.json"}
    return bool(candidates & names) or any(p.match(c) for p in patterns for c in candidates)


def test_every_reading_is_named_in_the_index():
    names, patterns = _named(INDEX.read_text(encoding="utf-8"))
    missing = sorted(path.name for path in READINGS.iterdir()
                     if path.is_file() and path.name != INDEX.name and not _indexed(path.name, names, patterns))
    assert not missing, f"docs/readings/README.md does not name {missing}: say what each is where it lives"


def test_the_index_names_no_reading_that_is_gone():
    bare = set(re.findall(r"`([a-z0-9_.-]+\.(?:json|md))`", INDEX.read_text(encoding="utf-8")))
    here = {path.name for path in READINGS.iterdir() if path.is_file()}
    readings = {name for name in bare if not name.startswith(("README", "WHERE", "RESEARCH"))}
    gone = sorted(name for name in readings if name not in here and name.rsplit(".", 1)[0] + ".md" not in here
                  and name.rsplit(".", 1)[0] + ".json" not in here)
    assert not gone, f"docs/readings/README.md names files that are not in the folder: {gone}"
