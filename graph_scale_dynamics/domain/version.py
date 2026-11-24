from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_BUILD_FILE = ROOT / "BUILD_NUMBER"
if _BUILD_FILE.is_file():
    BUILD_NUMBER = int(_BUILD_FILE.read_text().strip())
else:
    try:
        BUILD_NUMBER = int(package_version("gsd").split(".", 1)[0])
    except (PackageNotFoundError, ValueError) as exc:  # pragma: no cover
        raise RuntimeError("could not resolve Graph Scale Dynamics build identity") from exc

RUNTIME_DIRS = ("graph_scale_dynamics",)
RUNTIME_FILES = (
    "main.py",
    "tools/postgres_instance.py",
    "runtime/bootstrap/linux-amd64/unshare",
    "runtime/bootstrap/linux-amd64/ld-linux-x86-64.so.2",
    "runtime/bootstrap/linux-amd64/libc.so.6",
)
RUNTIME_SUFFIXES = (".py", ".html", ".json", ".sql", ".c", ".bin")
DEPLOYMENT_FENCE_EXIT_CODE = 75


class DeploymentProvenanceFence(RuntimeError):
    pass


def source_fingerprint(root: Path) -> str:
    root = Path(root)
    digest = hashlib.sha256()
    digest.update(f"gsd-build:{BUILD_NUMBER}\n".encode())
    paths: list[Path] = []
    for directory in RUNTIME_DIRS:
        base = root / directory
        if base.exists():
            paths.extend(
                path for path in base.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and not any(part.endswith(".egg-info") for part in path.parts)
                and path.suffix in RUNTIME_SUFFIXES
            )
    for name in RUNTIME_FILES:
        path = root / name
        if path.is_file():
            paths.append(path)
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


READING_SETTINGS = {"GSD_SPECTRAL_PROBE_BLOCK": "8"}


def reading_settings() -> dict:
    return {name: os.environ[name] for name, default in READING_SETTINGS.items()
            if os.environ.get(name) not in (None, "", default)}


@lru_cache(maxsize=1)
def runtime_environment() -> dict:
    distributions = {}
    for name in ("numpy", "scipy", "psutil", "psycopg", "psycopg-binary"):
        try:
            distributions[name] = package_version(name)
        except PackageNotFoundError:
            continue
    numerical_backend = {}
    try:
        import numpy as np
        configured = getattr(np.__config__, "CONFIG", {}) or {}
        dependencies = configured.get("Build Dependencies", {}) or {}
        for key in ("blas", "lapack"):
            detail = dependencies.get(key) or {}
            if detail:
                numerical_backend[key] = {
                    name: detail.get(name)
                    for name in ("name", "version", "openblas configuration")
                    if detail.get(name) is not None
                }
    except Exception:  # pragma: no cover
        numerical_backend = {}
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "distributions": distributions,
        "numerical_backend": numerical_backend,
        **({"reading_settings": settings} if (settings := reading_settings()) else {}),
    }


@lru_cache(maxsize=1)
def environment_fingerprint() -> str:
    payload = json.dumps(runtime_environment(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@lru_cache(maxsize=1)
def runtime_fingerprint() -> str:
    supplied = os.environ.get("GSD_RUNTIME_FINGERPRINT", "").strip()
    return supplied or source_fingerprint(ROOT)


def verify_runtime_fingerprint(expected: str | None = None, *, stage: str = "runtime") -> str:
    expected = (expected or os.environ.get("GSD_RUNTIME_FINGERPRINT", "")).strip()
    observed = source_fingerprint(ROOT)
    if expected and observed != expected:
        raise DeploymentProvenanceFence(
            f"{stage} source fingerprint mismatch: expected {expected}, observed {observed}"
        )
    return observed


def verify_environment_fingerprint(expected: str | None, *, stage: str = "runtime") -> str:
    expected = str(expected or "").strip()
    observed = environment_fingerprint()
    if expected and observed != expected:
        raise DeploymentProvenanceFence(
            f"{stage} environment fingerprint mismatch: expected {expected}, observed {observed}"
        )
    return observed


def ensure_build_number(repo, fingerprint: str | None = None) -> tuple[int, str]:
    resolved = fingerprint or runtime_fingerprint()
    repo.set_flag("build_number", str(BUILD_NUMBER))
    repo.set_flag("build_fingerprint", resolved)
    return BUILD_NUMBER, resolved[:8]
