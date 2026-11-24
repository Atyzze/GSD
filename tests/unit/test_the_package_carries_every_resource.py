from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / "graph_scale_dynamics" / "resources"


def test_every_resource_is_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["graph_scale_dynamics.resources"]
    missing = [str(p.relative_to(RESOURCES)) for p in RESOURCES.rglob("*")
               if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts
               and not any(fnmatch.fnmatch(str(p.relative_to(RESOURCES)), pattern) for pattern in patterns)]
    assert not missing, missing
