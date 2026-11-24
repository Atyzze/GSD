from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "graph_scale_dynamics"

PLACEHOLDER = re.compile(r"[=(,\s]%s\b")

SQL_HINT = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.IGNORECASE)


def _sql_modules() -> list[Path]:
    out = []
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if ".execute(" in text or ".executescript(" in text:
            out.append(path)
    return out


def _raw_cursor_literals(tree: ast.AST) -> set[int]:
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "executescript", "executemany"}:
            continue
        receiver = node.func.value
        if not ((isinstance(receiver, ast.Attribute) and receiver.attr == "raw")
                or (isinstance(receiver, ast.Name) and receiver.id == "raw")):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                exempt.add(id(arg))
    return exempt


def _offending_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exempt = _raw_cursor_literals(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in exempt:
            continue
        value = node.value
        if not SQL_HINT.search(value):
            continue
        if PLACEHOLDER.search(value):
            found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {value.strip()[:90]}")
    return found


def test_no_sql_literal_uses_a_format_placeholder():
    modules = _sql_modules()
    assert modules, "found no module that executes SQL; the scan is looking in the wrong place"
    offenders = [line for path in modules for line in _offending_literals(path)]
    assert offenders == [], (
        "SQL written with `%s` placeholders. postgres_sql escapes literal `%` when it "
        "translates qmark, so these reach the driver as `%%s` and every call raises:\n  "
        + "\n  ".join(offenders)
    )


def test_the_scan_would_catch_the_query_that_broke():
    broken = ("SELECT DISTINCT n FROM jobs WHERE campaign_id=%s AND candidate_id=%s "
              "AND kind='simulate' ORDER BY n")
    assert PLACEHOLDER.search(broken)


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM jobs WHERE error LIKE '%source fingerprint mismatch%'",
    "SELECT 1 FROM jobs WHERE campaign_id=? AND candidate_id=?",
    "UPDATE jobs SET note='100% complete' WHERE job_id=?",
])
def test_the_scan_does_not_fire_on_legitimate_percent_signs(sql):
    assert not PLACEHOLDER.search(sql)


def test_the_raw_cursor_exemption_is_narrow():
    tree = ast.parse(
        "class C:\n"
        "    def f(self):\n"
        "        self.raw.execute(\"SELECT set_config('lock_timeout', %s, false)\")\n"
        "        self.conn.execute('SELECT 1 FROM jobs WHERE campaign_id=%s')\n"
    )
    exempt = _raw_cursor_literals(tree)
    literals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    exempted = [n.value for n in literals if id(n) in exempt]
    guarded = [n.value for n in literals if id(n) not in exempt]
    assert any("set_config" in v for v in exempted)
    assert any("campaign_id=%s" in v for v in guarded)
