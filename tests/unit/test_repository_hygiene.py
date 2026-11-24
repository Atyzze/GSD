from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_operator_docs_are_current_and_consolidated():
    docs = ROOT / "docs"
    present = {p.name for p in docs.glob("*.md")}
    canonical = {"ARCHITECTURE.md", "DECISIONS.md", "HISTORY.md", "LESSONS.md", "TOOLS.md",
                 "OPERATIONS.md", "RESEARCH_METHOD.md", "ROADMAP.md", "WHERE_WE_ARE.md"}
    assert present == canonical, present ^ canonical

    notes = {p.name for p in (docs / "build_notes").glob("*.md")}
    assert notes, "every build writes docs/build_notes/BUILD<N>_NOTES.md"
    stray = {name for name in notes if not re.fullmatch(r"BUILD\d+_NOTES\.md", name)}
    assert not stray, stray

    assert (docs / "agent" / "ENVIRONMENT.md").is_file()


def test_the_repository_root_is_not_a_junk_drawer():
    assert (ROOT / "tools" / "prepare_environment.sh").is_file()
    assert (ROOT / "calibration" / "probe_windows.json").is_file()
    assert list((ROOT / "calibration" / "baselines").glob("*.json")), \
        "the certified cost baseline the release gate compares against"


def test_only_current_templates_are_packaged():
    configs = ROOT / "graph_scale_dynamics" / "resources" / "configs"
    assert {p.name for p in configs.glob("*.json")} == {
        "campaign_engine_survey.json",
        "candidate_sparse_anchor.json",
    }


def test_installed_runtime_does_not_depend_on_tools_package():
    for base in (ROOT / "graph_scale_dynamics" / "services", ROOT / "graph_scale_dynamics"):
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(not alias.name.startswith("tools") for alias in node.names), path
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("tools"), path


def test_operator_tools_default_to_the_folder_local_database():
    for path in sorted((ROOT / "tools").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "connect_database" not in source and "Repo(" not in source:
            continue
        tree = ast.parse(source)
        defaults = [
            keyword.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and any(isinstance(arg, ast.Constant) and str(arg.value).startswith("--db")
                    for arg in node.args)
            for keyword in node.keywords if keyword.arg == "default"
        ]
        if not defaults:
            continue
        assert all(isinstance(value, ast.Constant) and value.value == "folder"
                   for value in defaults), path


def test_non_science_runtime_has_no_statically_unused_imports():
    import json

    frozen = set(json.loads((ROOT / "tests/fixtures/science_freeze.json").read_text())["files"])
    for base in (ROOT / "graph_scale_dynamics" / "services", ROOT / "graph_scale_dynamics", ROOT / "tools", ROOT / "runtime"):
        for path in base.rglob("*.py"):
            if path.relative_to(ROOT).as_posix() in frozen:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            used = {node.id for node in ast.walk(tree)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
            used |= {element.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
                     for element in getattr(node.value, "elts", []) if isinstance(element, ast.Constant)}
            imports = []
            for node in tree.body:
                if isinstance(node, ast.Import):
                    imports.extend(alias.asname or alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.extend(alias.asname or alias.name for alias in node.names
                                   if alias.name != "annotations" and alias.name != "*")
            assert not (set(imports) - used), path
