from __future__ import annotations

from pathlib import Path

import graph_scale_dynamics

READINGS = Path("graph_scale_dynamics") / "resources" / "readings"


def code_tree_without_study_ledgers(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "code-tree"
    (root / READINGS).mkdir(parents=True)
    monkeypatch.setattr(graph_scale_dynamics, "PROJECT_ROOT", root)
    return root
