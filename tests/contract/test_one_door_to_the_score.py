from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORERS = {"score_law", "score_phenotype", "score_rung_rows"}
ALLOWED = {"graph_scale_dynamics/research/stability_score.py", "graph_scale_dynamics/research/score_door.py"}
WITHOUT_CONTROL_GATE: set[str] = set()


def _production():
    for path in sorted(list((ROOT / "graph_scale_dynamics").rglob("*.py")) + [ROOT / "main.py"]
                       + sorted((ROOT / "tools").glob("*.py"))):
        if "__pycache__" not in path.parts:
            yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _calls(tree):
    stack = [(tree, "<module>")]
    while stack:
        node, owner = stack.pop()
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            if isinstance(child, ast.Call):
                yield owner, child
            stack.append((child, name))


def test_nothing_outside_the_door_calls_a_scorer_directly():
    direct = []
    for rel, tree in _production():
        if rel in ALLOWED:
            continue
        for owner, call in _calls(tree):
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name in SCORERS:
                direct.append(f"{rel}:{call.lineno} {owner} calls {name}")
    assert not direct, "score through research/score_door.score_evidence:\n" + "\n".join(direct)


def test_the_callers_that_skip_the_control_family_gate_are_the_recorded_ones():
    skipping = set()
    for rel, tree in _production():
        for owner, call in _calls(tree):
            if getattr(call.func, "id", None) == "score_evidence" and \
               "control_reference" not in {k.arg for k in call.keywords}:
                skipping.add(f"{rel}::{owner}")
    assert skipping == WITHOUT_CONTROL_GATE, (
        f"added: {sorted(skipping - WITHOUT_CONTROL_GATE)}; removed: {sorted(WITHOUT_CONTROL_GATE - skipping)}")
