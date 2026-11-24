from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "ui" / "system.css").read_text(
    encoding="utf-8")


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+", selector))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-z][\w-]*)", selector))
    return ids, classes, elements


def _rules(prop: str, value: str) -> list[str]:
    found = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
        if re.search(rf"(?:^|;)\s*{prop}\s*:\s*{value}\b", body):
            found += [s.strip() for s in selectors.split(",")]
    return found


def test_the_reason_under_a_study_bundle_being_made_wraps_inside_the_table():
    nowrap = [s for s in _rules("white-space", "nowrap") if s.endswith("td") and "bundle-table" in s]
    wraps = [s for s in _rules("white-space", "normal") if "study-why" in s]
    assert nowrap, "the rule that keeps a bundle table's cells on one line is where this test expects it"
    assert wraps, "nothing lets the reason's cell wrap"
    assert max(_specificity(s) for s in wraps) > max(_specificity(s) for s in nowrap), (wraps, nowrap)
