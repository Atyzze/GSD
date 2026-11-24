from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "engine_rs_sources.json"
sys.path.insert(0, str(ROOT))


def sources_sha256(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    base = root / "engine_rs" / "src"
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix == ".rs"):
        digest.update(path.relative_to(base).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def current() -> dict:
    from graph_scale_dynamics.services.worker.engine_registry import rust_source_version
    return {"crate_version": rust_source_version(ROOT), "sources_sha256": sources_sha256()}


def test_the_sources_move_only_with_the_crate_version():
    recorded, now = json.loads(FIXTURE.read_text(encoding="utf-8")), current()
    if now["crate_version"] == recorded["crate_version"]:
        assert now["sources_sha256"] == recorded["sources_sha256"], (
            f"engine_rs/src changed under crate version {now['crate_version']}: an installed extension of that "
            "version would run in its place. Bump the crate version (engine_rs/Cargo.toml, engine_rs/pyproject.toml, "
            "engine_rs/Cargo.lock, uv.lock's gsd-engine-rs) and rebuild")
    else:
        raise AssertionError(f"the crate version moved to {now['crate_version']}: record it with "
                             "python3 tests/unit/test_the_rust_engine_is_versioned.py --write")


if __name__ == "__main__" and "--write" in sys.argv:
    FIXTURE.write_text(json.dumps(current(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(ROOT)}")
