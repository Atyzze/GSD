from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = frozenset({".git", "var", "instance", "build", "dist", "__pycache__", ".venv", "venv",
                        "site-packages", "target", "node_modules", ".pytest_cache"})


def _frozen() -> set[str]:
    return set(json.loads((ROOT / "tests/fixtures/science_freeze.json").read_text())["files"])


def bare_zips(source: str) -> list[int]:
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "zip" and not any(k.arg == "strict" for k in node.keywords)]


def test_the_guard_sees_a_bare_zip_and_accepts_a_chosen_one():
    assert bare_zips("pairs = list(zip(a, b))\n") == [1]
    assert bare_zips("pairs = list(zip(a, b, strict=True))\nsteps = zip(a, a[1:], strict=False)\n") == []
    assert bare_zips("import zipfile\nzipfile.ZipFile('x')\n") == []


def test_no_bare_zip_outside_the_frozen_science():
    frozen = _frozen()
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if SKIP_PARTS & set(relative.parts) or relative.as_posix() in frozen:
            continue
        for line in bare_zips(path.read_text(encoding="utf-8")):
            offenders.append(f"{relative}:{line}")
    assert not offenders, (
        "say whether unequal lengths are an error: strict=True where they cannot differ, "
        "strict=False (with the reason, unless it is zip(a, a[1:])) where truncation is meant: "
        + ", ".join(offenders))
