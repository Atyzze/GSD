from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("graph_scale_dynamics", "tools", "tests")
FILES = ("main.py",)
DIRECTIVE = re.compile(r"#\s*(noqa\b|type:|pragma\b)")
DOCSTRING_HOSTS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def python_files() -> list[Path]:
    found = [ROOT / name for name in FILES]
    for base in ROOTS:
        found += [path for path in (ROOT / base).rglob("*.py") if "__pycache__" not in path.parts]
    return sorted(found)


def comments(source: str) -> list[int]:
    lines = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if token.start[0] == 1 and token.string.startswith("#!"):
            continue
        if DIRECTIVE.search(token.string):
            continue
        lines.append(token.start[0])
    return lines


def docstrings(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, DOCSTRING_HOSTS) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                lines.append(first.lineno)
    return lines


def test_no_python_file_carries_a_comment_or_a_docstring():
    found = []
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        found += [f"{rel}:{line} comment" for line in comments(source)]
        found += [f"{rel}:{line} docstring" for line in docstrings(source)]
    assert not found, "say it in a name, or in docs/: " + ", ".join(found[:20])


def test_the_directives_kept_are_only_directives():
    assert comments("x = 1  # noqa: E501\n") == []
    assert comments("#!/usr/bin/env python3\nx = 1\n") == []
    assert comments("x = 1  # why\n") == [1]
    assert docstrings('def f():\n    "what"\n    return 1\n') == [2]
    assert docstrings('def f():\n    return "what"\n') == []


def rust_comments(source: str) -> list[int]:
    lines, quoted = [], False
    for number, line in enumerate(source.splitlines(), start=1):
        index = 0
        while index < len(line):
            if line[index] == "\\" and quoted:
                index += 2
                continue
            if line[index] == '"':
                quoted = not quoted
            elif not quoted and line.startswith(("//", "/*"), index):
                lines.append(number)
                break
            index += 1
    return lines


def test_no_rust_source_of_the_engine_carries_a_comment():
    found = [f"{path.relative_to(ROOT).as_posix()}:{line}" for path in sorted((ROOT / "engine_rs" / "src").glob("*.rs"))
             for line in rust_comments(path.read_text(encoding="utf-8"))]
    assert not found, "say it in a name, or in docs/ARCHITECTURE.md: " + ", ".join(found[:20])


def test_the_rust_check_finds_a_comment_and_not_a_string():
    assert rust_comments('let a = 1; // why\n') == [1]
    assert rust_comments('/// what\nfn f() {}\n') == [1]
    assert rust_comments('let url = "http://x";\n') == []
