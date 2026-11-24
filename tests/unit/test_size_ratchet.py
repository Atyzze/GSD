from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

FILE_LIMIT_BYTES = 100 * 1024
FUNCTION_LIMIT_LINES = 400

SKIP_PARTS = frozenset({
    ".git", "var", "instance", "build", "dist", "__pycache__",
    ".pytest_cache", "gsd.egg-info", "node_modules",
    ".venv", "venv", ".env", "site-packages", "target", ".cargo", ".rustup",
    ".mypy_cache", ".ruff_cache", ".uv-cache",
})

CEILING_SLACK_BYTES = 6 * 1024
CEILING_SLACK_LINES = 40

FILE_ALLOWLIST: dict[str, int] = {
    "main.py": 130000,
}

FUNCTION_ALLOWLIST: dict[str, int] = {
    "graph_scale_dynamics/services/api/main.py::build_handler": 1160,
    "graph_scale_dynamics/services/api/main.py::_get": 560,
    "main.py::_cmd_run_locked": 655,
    "graph_scale_dynamics/services/api/overview.py::build_fast_overview": 520,
    "graph_scale_dynamics/services/worker/main.py::run_one": 440,
}


def _sources() -> list[Path]:
    return [p for p in sorted(ROOT.rglob("*.py"))
            if not set(p.relative_to(ROOT).parts) & SKIP_PARTS]


def _measure() -> tuple[dict[str, int], dict[str, int]]:
    files: dict[str, int] = {}
    functions: dict[str, int] = {}
    for path in _sources():
        rel = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        if size > FILE_LIMIT_BYTES:
            files[rel] = size
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = (node.end_lineno or node.lineno) - node.lineno + 1
                if lines > FUNCTION_LIMIT_LINES:
                    functions[f"{rel}::{node.name}"] = lines
    return files, functions


MEASURED_FILES, MEASURED_FUNCTIONS = _measure()


def test_no_new_file_joins_the_oversized_list():
    joined = sorted(set(MEASURED_FILES) - set(FILE_ALLOWLIST))
    assert not joined, (
        f"these files crossed {FILE_LIMIT_BYTES // 1024} KB: {joined}. Split one "
        "rather than adding it to FILE_ALLOWLIST; the list only shrinks.")


def test_no_new_function_joins_the_oversized_list():
    joined = sorted(set(MEASURED_FUNCTIONS) - set(FUNCTION_ALLOWLIST))
    assert not joined, (
        f"these functions passed {FUNCTION_LIMIT_LINES} lines: {joined}. Split "
        "one rather than adding it to FUNCTION_ALLOWLIST; the list only shrinks.")


@pytest.mark.parametrize("path", sorted(FILE_ALLOWLIST))
def test_an_allowlisted_file_does_not_grow(path: str):
    actual = (ROOT / path).stat().st_size
    assert actual <= FILE_ALLOWLIST[path], (
        f"{path} grew to {actual} bytes, past its recorded {FILE_ALLOWLIST[path]}. "
        "This file is already over the bound. First try putting the new code "
        "somewhere the right size -- that is what this test is for, and it is "
        "what build 401 did, moving two readers into `domain/model.py` rather "
        "than adding 2.5 KB here. If the growth is genuinely unavoidable, raise "
        "the number above in the same change and say why in the build notes: "
        "what this forbids is silent growth, not deliberate growth.")


@pytest.mark.parametrize("name", sorted(FUNCTION_ALLOWLIST))
def test_an_allowlisted_function_does_not_grow(name: str):
    actual = MEASURED_FUNCTIONS.get(name)
    if actual is None:
        return
    assert actual <= FUNCTION_ALLOWLIST[name], (
        f"{name} grew to {actual} lines, past its recorded {FUNCTION_ALLOWLIST[name]}.")


def test_the_allowlist_is_not_carrying_slack():
    stale: list[str] = []
    for path, ceiling in sorted(FILE_ALLOWLIST.items()):
        actual = (ROOT / path).stat().st_size
        if actual <= FILE_LIMIT_BYTES:
            stale.append(f"{path}: now {actual} B, under the limit -- remove it from the allowlist")
        elif ceiling - actual > CEILING_SLACK_BYTES:
            stale.append(f"{path}: recorded {ceiling}, actually {actual} -- lower it")
    for name, ceiling in sorted(FUNCTION_ALLOWLIST.items()):
        actual = MEASURED_FUNCTIONS.get(name)
        if actual is None:
            stale.append(f"{name}: now under {FUNCTION_LIMIT_LINES} lines -- remove it")
        elif ceiling - actual > CEILING_SLACK_LINES:
            stale.append(f"{name}: recorded {ceiling}, actually {actual} -- lower it")
    assert not stale, "the allowlist has drifted above what it guards:\n  " + "\n  ".join(stale)


def test_the_bound_is_the_one_the_roadmap_states():
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "No Python file over 100 KB and no function over ~400 lines" in roadmap
    assert FILE_LIMIT_BYTES == 100 * 1024
    assert FUNCTION_LIMIT_LINES == 400
