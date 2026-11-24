from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def validate_member_names(members: list[str]) -> tuple[str, str]:
    assert members, "archive is empty"
    normalized: list[str] = []
    roots: set[str] = set()
    build_candidates: list[str] = []
    for raw in members:
        name = raw.replace("\\", "/")
        assert not name.startswith("/"), f"unsafe absolute path in archive: {raw}"
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if not parts:
            continue
        assert not any(p == ".." for p in parts), f"unsafe parent traversal: {raw}"
        roots.add(parts[0])
        normalized.append("/".join(parts))
        if len(parts) == 2 and parts[1] == "BUILD_NUMBER":
            build_candidates.append("/".join(parts))
    assert len(roots) == 1, (
        "archive must contain exactly one top-level build directory; "
        f"found {sorted(roots)!r}. This is the error apply_build.py prints, and "
        "it is what `tar -cf x.tar .` from inside the tree produces.")
    assert len(build_candidates) == 1, (
        f"archive must contain exactly one <root>/BUILD_NUMBER; found {len(build_candidates)}")
    root = next(iter(roots))
    assert root not in {"", ".", ".."}, f"invalid archive root: {root!r}"
    for member in normalized:
        assert member == root or member.startswith(root + "/"), (
            f"archive member escaped expected root {root!r}: {member}")
    return root, build_candidates[0]


@pytest.fixture(scope="module")
def built_archive(tmp_path_factory):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    package_release = pytest.importorskip("package_release")
    if not __import__("shutil").which("zstd"):
        pytest.skip("zstd is required to build the native archive")
    out = tmp_path_factory.mktemp("release") / "GSD999999.tar.zst"
    package_release.publish_archive(package_release.archive(999999, out), out)
    return out


def _members(archive: Path) -> list[str]:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        tar = Path(raw) / "release.tar"
        subprocess.run(["zstd", "-d", "-q", "-f", str(archive), "-o", str(tar)], check=True)
        with tarfile.open(tar, "r:") as tf:
            return tf.getnames()


def test_the_archive_satisfies_the_deploy_tools_shape_rule(built_archive):
    root, build_member = validate_member_names(_members(built_archive))
    assert root == "graph_scale_dynamics_build_999999", (
        "apply_build.py derives the deploy directory from this name")
    assert build_member == f"{root}/BUILD_NUMBER"


def test_the_archive_root_carries_the_number_in_the_filename(built_archive):
    assert built_archive.name == "GSD999999.tar.zst"
    root, _ = validate_member_names(_members(built_archive))
    assert root.endswith("999999")


def test_nothing_disposable_rides_along(built_archive):
    forbidden = (".git/", "var/", "target/", ".venv/", "venv/",
                 "__pycache__/", ".pytest_cache/", ".env.postgres", "instance/")
    offenders = [m for m in _members(built_archive)
                 if any(f"/{part}" in f"/{m}/" for part in forbidden)]
    assert not offenders, f"disposable paths in the archive: {sorted(offenders)[:10]}"


def test_the_release_carries_what_a_fresh_agent_reads_first():
    for relative in ("README.md", "docs/agent/HANDOFF.md", "docs/agent/ENVIRONMENT.md",
                     "docs/agent/TARGET_ENVIRONMENT.md", "docs/ROADMAP.md",
                     "docs/ARCHITECTURE.md", "docs/RESEARCH_METHOD.md"):
        assert (ROOT / relative).is_file(), f"{relative} is named in the README and is missing"
