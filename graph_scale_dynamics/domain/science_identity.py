from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FROZEN_TREES = (
    "graph_scale_dynamics/scaleflow",
    "graph_scale_dynamics/dsl",
    "graph_scale_dynamics/measurements",
    "graph_scale_dynamics/engine",
    "graph_scale_dynamics/resources/configs",
    "graph_scale_dynamics/resources/calibration",
    "engine_rs/src",
    "graph_scale_dynamics/decisions",
)

FROZEN_FILES = (
    "graph_scale_dynamics/domain/randomness.py",
    "graph_scale_dynamics/calibration/finite_size.py",
    "graph_scale_dynamics/calibration/start_reading.py",
    "graph_scale_dynamics/observability/law_score.py",
    "graph_scale_dynamics/observability/two_chains.py",
    "graph_scale_dynamics/observability/space_score.py",
    "graph_scale_dynamics/observability/starts_reading.py",
)

FROZEN_SUFFIXES = (".py", ".json", ".rs", ".toml")


def frozen_paths() -> list[str]:
    paths: set[str] = set()
    for tree in FROZEN_TREES:
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in FROZEN_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            paths.add(path.relative_to(ROOT).as_posix())
    for name in FROZEN_FILES:
        if (ROOT / name).is_file():
            paths.add(name)
    return sorted(paths)


def digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def science_fingerprint() -> str:
    try:
        joined = "\n".join(f"{rel}:{digest(rel)}" for rel in frozen_paths())
    except OSError:
        return "unavailable"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
