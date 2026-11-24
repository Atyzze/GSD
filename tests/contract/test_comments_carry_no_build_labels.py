from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = re.compile(r"^\s*#+:?\s*Builds?\s+\d{3}[a-z]?(?:\s*(?:,|and|to|through|&|/)\s*\d{3}[a-z]?)*\s*[:.]\s")
BARE_LABEL = re.compile(r"^\s*#+:?\s*\d{3}[a-z]?(?:\s*(?:,|and|to|through|&|/)\s*\d{3}[a-z]?)*\s*:\s")
NOTED_LABEL = re.compile(r"^\s*#+:?\s*Builds?\s+\d{3}[a-z]?\s*\([^)]*\)\s*:\s")
JS_LABEL = re.compile(r"(?:/\*+|//)\s*Builds?\s+\d{3}[a-z]?\s*[:.]\s")


def test_no_python_comment_opens_with_a_build_label():
    frozen = set(json.loads((ROOT / "tests/fixtures/science_freeze.json").read_text(encoding="utf-8"))["files"])
    found = []
    for path in sorted(list((ROOT / "graph_scale_dynamics").rglob("*.py")) + [ROOT / "main.py"]
                       + sorted((ROOT / "tools").glob("*.py"))):
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in path.parts or rel in frozen:
            continue
        for tok in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline):
            if tok.type == tokenize.COMMENT and any(
                    pattern.match(tok.string) for pattern in (LABEL, BARE_LABEL, NOTED_LABEL)):
                found.append(f"{rel}:{tok.start[0]}")
    assert not found, "comments that open with a build label:\n" + "\n".join(found[:20])


def test_the_label_patterns_refuse_a_label_and_spare_a_sentence():
    for label in ("# 477: two ticks", "#: 484: the states", "# 470, 472: both", "# Build 244 (rule 13): no",
                  "# Build 447: gone"):
        assert any(p.match(label) for p in (LABEL, BARE_LABEL, NOTED_LABEL)), label
    for sentence in ("# Two ticks, as a shutdown (474).", "# 478 put a correlated MIN(n) here",
                     "# Build 412 checked the header", "# 10: not a build"):
        assert not any(p.match(sentence) for p in (LABEL, BARE_LABEL, NOTED_LABEL)), sentence


def test_no_dashboard_comment_opens_with_a_build_label():
    ui = ROOT / "graph_scale_dynamics" / "resources" / "ui"
    found = [f"{p.name}:{text[:m.start()].count(chr(10)) + 1}"
             for p in sorted(ui.glob("*.*")) if p.suffix in {".js", ".css"}
             for text in [p.read_text(encoding="utf-8")] for m in JS_LABEL.finditer(text)]
    assert not found, "dashboard comments that open with a build label: " + ", ".join(found[:20])
