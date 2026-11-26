from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "graph_scale_dynamics"
CITATION = re.compile(r"\((?:[5-8]\d\d)(?:[,;] ?[^)]{0,60})?\)"
                      r"|\b(?:since|before|from build|until|after|at build|build) [5-8]\d\d\b")
KEPT = {
    "graph_scale_dynamics/services/reporter/study_run.py": "a value recorded in every report's cost, compared with it",
    "graph_scale_dynamics/research/stability_score.py": "a value in a law's recorded stability, part of its outputs",
    "graph_scale_dynamics/scaleflow/equilibration.py": "a note in a law's outputs, which outputs_of_a_law holds fixed",
    "graph_scale_dynamics/research/claim_ledger.py": "a pointer into docs/HISTORY.md, where the builds are the history",
    "graph_scale_dynamics/research/document_claims.py": "the documents' own words, held as written; the docs keep theirs",
}


def test_no_page_of_the_dashboard_cites_a_build_number():
    found = []
    for path in sorted((PACKAGE / "resources" / "ui").iterdir()):
        if path.suffix not in (".js", ".html"):
            continue
        text = path.read_text(encoding="utf-8")
        found += [f"{path.name}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}" for m in CITATION.finditer(text)]
    assert found == [], "a page says what a build number stood for, in words (874)"


def test_no_report_or_message_cites_a_build_number_and_the_decisions_keep_their_words():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if "/decisions/" in relative or relative in KEPT:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found += [f"{relative}:{node.lineno}: {m.group(0)}" for m in CITATION.finditer(node.value)]
    assert found == [], "a report or a message says what a build number stood for, in words (874)"
    decisions = (PACKAGE / "decisions" / "starts_rule.py").read_text(encoding="utf-8")
    assert "(629)" in decisions, "a decision's reason replays word for word, its build numbers with it"
    for relative in KEPT:
        assert CITATION.search((ROOT / relative).read_text(encoding="utf-8")), f"{relative} no longer needs keeping"
