from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "readings" / "findings.json"
STUDIES = ROOT / "graph_scale_dynamics" / "resources" / "readings" / "studies.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _numbered_findings() -> dict[int, str]:
    text = (ROOT / "docs" / "WHERE_WE_ARE.md").read_text(encoding="utf-8")
    section = text.split("## What we know", 1)[1].split("\n## ", 1)[0]
    return {int(m.group(1)): " ".join(m.group(2).split())
            for m in re.finditer(r"^(\d+)\. (.+(?:\n {2,}\S.*)*)", section, re.M)}


def test_every_numbered_finding_has_its_entry():
    items = _numbered_findings()
    entries = {entry["item"]: entry for entry in _manifest()["where_we_are"]}
    assert items, "WHERE_WE_ARE.md lost its numbered findings"
    assert sorted(entries) == sorted(items), (
        f"WHERE_WE_ARE.md numbers its findings {sorted(items)} and findings.json carries {sorted(entries)}: "
        "a finding added, dropped or renumbered moves its entry with it")
    for number, text in items.items():
        starts = entries[number]["starts"]
        assert text.replace("**", "").startswith(starts), (
            f"finding {number} reads {text[:90]!r}, and its entry in findings.json starts {starts!r}")


def test_every_section_that_states_a_finding_has_its_entry():
    headings = re.findall(r"^## (.+)$", (ROOT / "docs" / "RESEARCH_METHOD.md").read_text(encoding="utf-8"), re.M)
    manifest = _manifest()
    named = [entry["section"] for entry in manifest["research_method"]]
    skipped = manifest["not_findings"]
    assert len(named) == len(set(named))
    assert set(named) <= set(headings), f"entries for sections that are gone: {sorted(set(named) - set(headings))}"
    assert set(skipped) <= set(headings), f"not_findings names sections that are gone: {sorted(set(skipped) - set(headings))}"
    missing = [heading for heading in headings if heading not in named and heading not in skipped]
    assert not missing, f"sections of RESEARCH_METHOD.md with no entry in findings.json: {missing}"


def test_every_file_named_is_in_the_tree_and_every_tool_named_exists():
    manifest = _manifest()
    for entry in manifest["where_we_are"] + manifest["research_method"]:
        assert entry["status"] and entry["command"], entry
        for name in entry["data"]:
            assert (ROOT / name).is_file(), f"{name} is named for a finding and is not in the tree"
        assert not {"archived", "archived_784"} & set(entry), (
            f"a finding rests on what is in the tree; the archives' manifests left at 790: {entry}")
        for tool in re.findall(r"tools/\w+\.py", entry["command"]):
            assert (ROOT / tool).is_file(), (
                f"{tool} is named to read a finding again and is not in the tree")
        if not entry["data"]:
            assert entry["status"].startswith(("pending", "historical")), (
                f"a finding with no file in the tree must say why: {entry}")


def test_the_register_of_studies():
    register = json.loads(STUDIES.read_text(encoding="utf-8"))
    guideline = register["guideline"]
    assert guideline["laws_at_most"] == 100_000 and "graphs_at_most" not in guideline, "study A's sizes"
    ids = [study["id"] for study in register["studies"]]
    assert len(ids) == len(set(ids)) and ids == sorted(ids, key=int)
    for study in register["studies"]:
        for key in ("readings", "data"):
            for name in study.get(key) or []:
                assert (ROOT / name).is_file(), f"study {study['id']}: {name} is not in the tree"
        assert not study.get("archived"), f"study {study['id']}: the archives' manifests left at 790"
        if study.get("criterion"):
            assert (ROOT / study["criterion"]).is_file(), study["criterion"]
        size = study.get("size") or {}
        if isinstance(size.get("laws"), int):
            assert size["laws"] <= guideline["laws_at_most"], study["id"]
    assert not list((ROOT / "docs" / "readings").glob("archived*.json")), "no manifest of the readings taken out"
