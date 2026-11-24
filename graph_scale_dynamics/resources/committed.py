from __future__ import annotations

import json
from pathlib import Path

REL = Path("graph_scale_dynamics") / "resources" / "readings"
DOCS_READINGS = Path("docs") / "readings"
_PACKAGE_TREE = Path(__file__).resolve().parents[2]


def directory(tree=None) -> Path:
    return (Path(tree) if tree is not None else _PACKAGE_TREE) / REL


def path(name: str, tree=None) -> Path:
    return directory(tree) / str(name)


def relative(name: str) -> str:
    return str(REL / str(name))


def resolve(recorded, tree=None) -> Path:
    root = Path(tree) if tree is not None else _PACKAGE_TREE
    recorded = Path(str(recorded))
    found = recorded if recorded.is_absolute() else root / recorded
    if found.exists():
        return found
    if recorded.parent == DOCS_READINGS:
        moved = directory(root) / recorded.name
        if moved.exists():
            return moved
    return found


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
