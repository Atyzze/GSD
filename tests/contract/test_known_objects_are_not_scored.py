from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_PACKAGE = ROOT / "graph_scale_dynamics" / "calibration"

SCORE_MODULE_MARKERS = ("stability_score", "discovery_score", "score")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_instrument_does_not_import_the_score():
    offenders = {}
    for path in sorted(CALIBRATION_PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        hits = sorted(name for name in _imported_modules(path)
                      if any(marker in name for marker in SCORE_MODULE_MARKERS))
        if hits:
            offenders[path.relative_to(ROOT).as_posix()] = hits
    assert offenders == {}, (
        "the calibration package imported the score. The instrument says how far a "
        f"reading can be trusted and never how interesting it is: {offenders}")


def test_the_score_does_not_reach_into_the_calibration_cells():
    path = ROOT / "graph_scale_dynamics" / "research" / "stability_score.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    scorers = {"score_law", "score_block", "score_phenotype"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.dump(node)
        calls_a_scorer = any(
            isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
            and inner.func.id in scorers for inner in ast.walk(node))
        reads_cells = ("'cells'" in body or '"cells"' in body or "cell_key" in body)
        if calls_a_scorer and reads_cells and node.name not in scorers:
            offenders.append(node.name)
    assert offenders == [], (
        "a scoring path reached into the calibration cells: "
        f"{offenders}. Known objects are measured, never scored.")


def test_report_22_scores_no_calibration_family():
    from graph_scale_dynamics.research.stability_score import build_stability_report

    body = build_stability_report([], None)

    families = {"periodic_ring", "periodic_square_lattice", "periodic_cubic_lattice",
                "sierpinski_gasket", "random_4_regular", "uniform_random_tree"}

    def walk(node, trail):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in families and isinstance(value, dict) and "score" in value:
                    raise AssertionError(f"{'/'.join(trail + [key])} carries a score")
                walk(value, trail + [str(key)])
        elif isinstance(node, list):
            for item in node:
                walk(item, trail)

    walk(body, [])
    json.dumps(body)


def test_the_definition_block_describes_the_contract_it_claims():
    from graph_scale_dynamics.research.stability_score import (
        STABILITY_SCORE_CONTRACT, build_stability_report,
    )

    definition = build_stability_report([], None)["definition"]
    assert definition["contract"] == STABILITY_SCORE_CONTRACT
    assert "mean degree stabilization" not in definition["not_in_blocks"]
