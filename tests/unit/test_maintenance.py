from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_allowlist_excludes_generated_packaging_products():
    from tools.package_release import release_paths, include_in_release

    shipped = [path.relative_to(ROOT).as_posix() for path in release_paths() if include_in_release(path)]
    assert not any(part in {"build", "dist", ".venv", "venv", "__pycache__"}
                   or part.endswith(".egg-info")
                   for relative in shipped for part in Path(relative).parts)
