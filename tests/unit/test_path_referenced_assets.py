from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PATH_REFERENCED_ASSETS: tuple[tuple[str, str, str], ...] = (
    ("runtime/bootstrap/linux-amd64/unshare",
     "tools/postgres_instance.py",
     "the folder-local PostgreSQL cannot enter its user namespace, so the "
     "database does not start on any host without Docker Hub access"),
    ("runtime/bootstrap/linux-amd64/ld-linux-x86-64.so.2",
     "tools/postgres_instance.py",
     "the bundled unshare cannot be loaded"),
    ("runtime/bootstrap/linux-amd64/libc.so.6",
     "tools/postgres_instance.py",
     "the bundled unshare cannot be loaded"),
)


@pytest.mark.parametrize("relative,referenced_by,consequence", PATH_REFERENCED_ASSETS,
                         ids=[a[0] for a in PATH_REFERENCED_ASSETS])
def test_path_referenced_asset_is_present(relative, referenced_by, consequence):
    target = ROOT / relative
    assert target.is_file(), (
        f"{relative} is missing. It is reached by path from {referenced_by}, never "
        f"imported, so neither the static graph nor the runtime-imports oracle can "
        f"see it. If it was parked: {consequence}."
    )


def test_runtime_is_never_imported_as_a_module():
    offenders = []
    sources = [ROOT / "graph_scale_dynamics", ROOT / "tools", ROOT / "tests",
               ROOT / "runtime"]
    candidates = [ROOT / "main.py"]
    for base in sources:
        candidates.extend(base.rglob("*.py"))
    for path in candidates:
        if any(part in {".git", "attic", "__pycache__"} for part in path.parts):
            continue
        if path.parts[-2:] == ("runtime", "__init__.py"):
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import runtime", "from runtime.", "from runtime ")):
                offenders.append(f"{path.relative_to(ROOT)}: {stripped}")
    assert not offenders, (
        "runtime/ is now imported as a module: " + "; ".join(offenders)
        + ". That is fine, but this test documented that it was not, and the "
        "parking evidence should be re-read."
    )
