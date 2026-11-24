from __future__ import annotations

import hashlib
import re
from pathlib import Path

from graph_scale_dynamics.resources import committed

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / "docs" / "readings"
def test_no_reader_builds_a_path_into_docs_readings():
    pattern = re.compile(r'"docs"\s*/\s*"readings"|Path\("docs"\)\s*/\s*"readings"')
    offenders = []
    for path in sorted([*(ROOT / "graph_scale_dynamics").rglob("*.py"), *(ROOT / "tools").rglob("*.py"),
                        ROOT / "main.py"]):
        if path.name == "committed.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_a_path_recorded_before_635_finds_the_same_bytes():
    for name in ("controls_criterion_2.json",):
        found = committed.resolve(f"docs/readings/{name}")
        assert found == committed.path(name) and found.is_file(), name
    assert committed.resolve("docs/readings/findings.json") == READINGS / "findings.json", "a reading stays a reading"
    assert committed.resolve("docs/readings/no_such_file.json") == ROOT / "docs" / "readings" / "no_such_file.json"


def test_the_design_is_the_bytes_the_campaigns_were_made_with(tmp_path):
    from graph_scale_dynamics.operations import study_design as SD
    from tests.support import designs
    tree = designs.tree_with_a_design(tmp_path, "261")
    design = SD.design_for(tree, "261")
    raw = SD.design_path(tree, "261").read_bytes()
    assert design["sha256"] == hashlib.sha256(raw).hexdigest()
    assert design["path"] == "graph_scale_dynamics/resources/readings/study_261_design.json"
    assert SD.designed_studies(tree) == ["261"]
    assert SD.designed_studies(ROOT) == ["169", "170", "171", "172", "173", "174", "175", "176"], (
        "the designs in the tree: 169's, written on 813, 170's on 820, 171's on 827, 172's on 835, 173's on 841, "
        "174's on 844, 175's on 847 and 176's on 855")


def test_the_readings_folder_is_small_and_names_no_archive():
    size = sum(path.stat().st_size for path in READINGS.rglob("*") if path.is_file())
    assert size < 100_000_000, f"docs/readings/ is {size / 1e6:.1f} MB: a reading worth keeping that large belongs in the archive"
    assert not list(READINGS.glob("archived*.json")), "the manifests of the readings taken out left at 790"