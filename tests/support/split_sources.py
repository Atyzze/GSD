from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_MODULES = tuple(ROOT / "graph_scale_dynamics" / "services" / "api" / f"{name}.py"
                    for name in ("main", "host", "fleet_snapshots", "overview"))
REPO_MODULES = tuple(sorted((ROOT / "graph_scale_dynamics" / "db").glob("repo*.py")))


def source(paths) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)
