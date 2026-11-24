from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRONOUN = re.compile(r"\b(he|He|him|Him|his|His|himself|she|She|her|Her|herself)\b")
TEXT_SUFFIXES = (".md", ".py", ".js", ".css", ".html", ".sql", ".sh", ".toml", ".txt", ".rs", ".cfg", ".ini")
SELF = "tests/contract/test_the_operator_is_they.py"


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return out.split()
    except (OSError, subprocess.CalledProcessError):
        return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts]


def test_no_gendered_pronoun_in_our_own_text():
    frozen = set(json.loads((ROOT / "tests/fixtures/science_freeze.json").read_text(encoding="utf-8"))["files"])
    found = []
    for rel in _tracked():
        if rel in frozen or rel == SELF or rel.startswith("runtime/") or not rel.endswith(TEXT_SUFFIXES):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if PRONOUN.search(line):
                found.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert not found, "say \"the operator\" or \"they\":\n" + "\n".join(found[:30])
