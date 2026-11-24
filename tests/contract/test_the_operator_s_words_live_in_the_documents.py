from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACES = ("graph_scale_dynamics", "tools", "tests", "main.py")
SUFFIXES = {".py", ".js", ".html", ".css"}
WHO = "oper" + "ator"
DATE = r"20\d\d-\d\d-\d\d"
DATED = re.compile(rf"{WHO}[^\n]{{0,40}}{DATE}|{DATE}[^\n]{{0,30}}{WHO}|{WHO}, \d{{1,2}}:\d\d|{WHO}'s rule")


def _files():
    for place in PLACES:
        path = ROOT / place
        if path.is_file():
            yield path
            continue
        for file in sorted(path.rglob("*")):
            if file.suffix in SUFFIXES and file.is_file() and "__pycache__" not in file.parts:
                yield file


def test_no_code_test_or_printed_line_carries_a_rule_with_its_author_and_date():
    found = [f"{file.relative_to(ROOT)}:{number}: {line.strip()[:140]}"
             for file in _files()
             for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
             if DATED.search(line)]
    assert not found, ("who decided a rule and when lives in docs/HISTORY.md and the build notes; the code says "
                       "what the rule is:\n" + "\n".join(found))
