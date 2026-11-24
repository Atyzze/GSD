from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECLARED = {"numpy", "scipy", "psutil", "psycopg", "ijson", "gsd_engine_rs"}
OWN = {"graph_scale_dynamics", "tools", "runtime", "main"} | {p.stem for p in (ROOT / "tools").glob("*.py")}


def _guarded(tree: ast.AST) -> set[int]:
    names = {"ImportError", "ModuleNotFoundError"}
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                (isinstance(h.type, ast.Name) and h.type.id in names)
                or (isinstance(h.type, ast.Tuple) and any(getattr(e, "id", "") in names for e in h.type.elts))
                for h in node.handlers):
            out |= {id(sub) for sub in ast.walk(node) if isinstance(sub, (ast.Import, ast.ImportFrom))}
    return out


def test_the_dependencies_named_here_are_the_ones_pyproject_declares():
    import re
    import tomllib

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {re.split(r"[\[<>=!~ ;]", d, maxsplit=1)[0].replace("-", "_") for d in declared}
    assert names == DECLARED, names


def test_every_import_is_the_standard_library_the_project_or_declared():
    allowed = set(sys.stdlib_module_names) | OWN | DECLARED
    found = []
    for path in sorted([ROOT / "main.py", *(ROOT / "graph_scale_dynamics").rglob("*.py"), *(ROOT / "tools").rglob("*.py")]):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = _guarded(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            found += [f"{path.relative_to(ROOT)}: {name}" for name in names
                      if name not in allowed and id(node) not in guarded]
    assert not found, f"imports no declared dependency installs: {found}"


def test_every_import_of_the_tests_is_installed_by_the_lock_with_its_dev_extra():
    import re
    import tomllib

    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]
    dev = {re.split(r"[\[<>=!~ ;]", d, maxsplit=1)[0].replace("-", "_")
           for d in [*project["optional-dependencies"]["dev"], *document["build-system"]["requires"]]}
    allowed = set(sys.stdlib_module_names) | OWN | DECLARED | dev | {"tests", "conftest", "_pytest"}
    allowed |= {p.stem for p in (ROOT / "tests").rglob("*.py")}
    found = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = _guarded(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            found += [f"{path.relative_to(ROOT)}: {name}" for name in names
                      if name not in allowed and id(node) not in guarded]
    assert not found, f"tests import what the lock with its dev extra does not install: {found}"
