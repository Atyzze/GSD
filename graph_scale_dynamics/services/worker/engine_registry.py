from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ENGINE_ENV = "GSD_ENGINE"
DOOR_ENV = "GSD_ENGINE_DOOR"
_TREE = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Engine:
    name: str
    reference: bool
    sources: tuple[str, ...]
    extension: str | None = None
    version_file: str | None = None
    doors: tuple[str, ...] = ()
    library: str | None = None
    defines: tuple[str, ...] = ()
    covers: tuple[str, ...] | None = None


ENGINES = {
    "python": Engine(name="python", reference=True, sources=("graph_scale_dynamics/engine/*.py",)),
    "rust": Engine(name="rust", reference=False, sources=("engine_rs/src/*.rs",), extension="gsd_engine_rs",
                   version_file="engine_rs/Cargo.toml", doors=("in_process", "c_abi")),
    "c": Engine(name="c", reference=False, sources=("engine_c/*.c", "engine_c/*.h"), version_file="engine_c/engine.toml",
                doors=("c_abi",), library="libgsd_engine_c"),
    "asm": Engine(name="asm", reference=False, sources=("engine_c/*.c", "engine_c/*.h", "engine_asm/*.S"),
                  version_file="engine_asm/engine.toml", doors=("c_abi",), library="libgsd_engine_asm",
                  defines=("GSD_ASM",), covers=("edge_count", "degree_square_sum", "wedge_count", "degree_anchor",
                                                "degree_anchor_abs")),
}
REFERENCE = next(name for name, engine in ENGINES.items() if engine.reference)
DEFAULT_ENGINE = "rust"
ENGINE_PYTHON = REFERENCE
ENGINE_RUST = DEFAULT_ENGINE
COMPILED = tuple(name for name, engine in ENGINES.items() if engine.extension)


def _source_files(engine: Engine, root: Path | None = None) -> list[Path]:
    root = Path(root) if root is not None else _TREE
    return sorted(path for pattern in engine.sources for path in root.glob(pattern) if path.name != "__init__.py")


def _python_fingerprint() -> str:
    source = b"".join(path.name.encode() + b"\0" + path.read_bytes()
                      for path in _source_files(ENGINES[REFERENCE]))
    return "py:" + hashlib.sha256(source).hexdigest()[:16]


_ENGINE_SOURCES: dict = {}


def engine_sources_digest() -> str:
    if "digest" not in _ENGINE_SOURCES:
        files = [path for engine in ENGINES.values() for path in _source_files(engine)]
        source = b"".join(path.name.encode() + b"\0" + path.read_bytes() for path in files)
        _ENGINE_SOURCES["digest"] = hashlib.sha256(source).hexdigest()[:16]
    return _ENGINE_SOURCES["digest"]


def _extension(name: str = DEFAULT_ENGINE):
    import importlib
    return importlib.import_module(str(ENGINES[name].extension))


def library_path(name: str, *, build: bool = True) -> Path | None:
    import shutil
    import subprocess
    import tempfile
    engine = ENGINES[name]
    files = _source_files(engine)
    if not files:
        return None
    digest = hashlib.sha256(b"".join(path.name.encode() + b"\0" + path.read_bytes() for path in files)).hexdigest()[:16]
    built = _TREE / "var" / "engines" / f"{engine.library}-{digest}.so"
    if built.is_file() or not build:
        return built if built.is_file() else None
    compiler = shutil.which(os.environ.get("CC") or "cc") or shutil.which("gcc")
    if compiler is None:
        return None
    built.parent.mkdir(parents=True, exist_ok=True)
    version = rust_source_version(None, name) or "0.0.0"
    with tempfile.TemporaryDirectory(dir=built.parent) as scratch:
        made = Path(scratch) / built.name
        done = subprocess.run([compiler, "-std=gnu99", "-O2", "-fPIC", "-shared", "-ffp-contract=off",
                               f'-DGSD_ENGINE_C_VERSION="{version}"', *[f"-D{name}" for name in engine.defines],
                               "-o", str(made), *[str(path) for path in files if path.suffix in (".c", ".S")], "-lm"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"the {name} engine did not compile: {done.stderr.strip()[:2000]}")
        made.replace(built)
    return built


def covers(name: str, ops) -> bool:
    found = ENGINES[name].covers
    return found is None or set(ops) <= set(found)


def _rust_available(name: str = DEFAULT_ENGINE) -> bool:
    if ENGINES[name].library:
        try:
            return library_path(name) is not None
        except RuntimeError:
            return False
    try:
        extension = _extension(name)
    except ImportError:
        return False
    return extension is not None


def _rust_fingerprint(name: str = DEFAULT_ENGINE) -> str:
    if ENGINES[name].library:
        built = library_path(name)
        return f"{name}:{rust_source_version(None, name)}+{hashlib.sha256(built.read_bytes()).hexdigest()[:16]}"
    version = str(getattr(_extension(name), "FINGERPRINT", "unknown"))
    origin = rust_extension_path(name)
    if origin is None:
        return f"rs:{version}+nobinary"
    try:
        digest = hashlib.sha256(origin.read_bytes()).hexdigest()[:16]
    except OSError:
        return f"rs:{version}+unreadable"
    return f"rs:{version}+{digest}"


def rust_extension_path(name: str = DEFAULT_ENGINE) -> Path | None:
    import importlib.machinery
    import sys
    module = str(ENGINES[name].extension)
    extension = _extension(name)
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    for loaded in sorted(sys.modules):
        if loaded == module or loaded.startswith(module + "."):
            origin = getattr(sys.modules[loaded], "__file__", None)
            if origin and str(origin).endswith(suffixes):
                return Path(origin)
    origin = getattr(extension, "__file__", None)
    if origin and Path(origin).name == "__init__.py":
        found = sorted(p for p in Path(origin).parent.iterdir() if p.name.endswith(suffixes))
        return found[0] if found else None
    return None


def rust_science_version(root: Path | None = None, name: str = DEFAULT_ENGINE) -> str | None:
    import re
    path = (Path(root) if root is not None else _TREE) / str(ENGINES[name].version_file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "[package.metadata.gsd]" in text:
        found = re.search(r'^science\s*=\s*"([^"]+)"', text.split("[package.metadata.gsd]", 1)[1].split("\n[", 1)[0],
                          re.MULTILINE)
        if found:
            return found.group(1)
    return rust_source_version(root, name)


def rust_source_version(root: Path | None = None, name: str = DEFAULT_ENGINE) -> str | None:
    import re
    path = (Path(root) if root is not None else _TREE) / str(ENGINES[name].version_file)
    try:
        package = path.read_text(encoding="utf-8").split("[package]", 1)[1].split("\n[", 1)[0]
    except (OSError, IndexError):
        return None
    found = re.search(r'^version\s*=\s*"([^"]+)"', package, re.MULTILINE)
    return found.group(1) if found else None


def stale_rust_engine(root: Path | None = None, name: str = DEFAULT_ENGINE) -> str | None:
    if ENGINES[name].library:
        return None
    declared = rust_source_version(root, name)
    if declared is None or not _rust_available(name):
        return None
    installed = str(getattr(_extension(name), "FINGERPRINT", "unknown"))
    if installed == declared:
        return None
    return f"the installed {ENGINES[name].extension} is {installed} and this tree's engine_rs is {declared}"


def rust_engine_current_after_build(root: Path | None = None) -> bool:
    import subprocess
    import sys
    code = ("from graph_scale_dynamics.services.worker.engine_registry import stale_rust_engine as s; "
            "raise SystemExit(1 if s() else 0)")
    cwd = Path(root) if root is not None else _TREE
    return subprocess.run([sys.executable, "-c", code], cwd=cwd).returncode == 0


def available_engines() -> dict[str, dict]:
    engines = {}
    for name, engine in ENGINES.items():
        if engine.reference:
            engines[name] = {"fingerprint": _python_fingerprint(), "available": True}
        elif _rust_available(name):
            engines[name] = {"fingerprint": _rust_fingerprint(name), "available": True}
        else:
            engines[name] = {"fingerprint": None, "available": False}
    return engines


_DOORS: dict = {}


def door_of(name: str = DEFAULT_ENGINE, door: str | None = None) -> Callable:
    from graph_scale_dynamics.engine import boundary
    door = str(door or os.environ.get(DOOR_ENV) or boundary.IN_PROCESS)
    engine = ENGINES[name]
    if door not in engine.doors:
        raise ValueError(f"engine {name!r} answers the boundary through {engine.doors}, not {door!r}")
    if (name, door) not in _DOORS:
        if door == boundary.IN_PROCESS:
            _DOORS[(name, door)] = boundary.in_process(_extension(name))
        else:
            found = library_path(name) if engine.library else rust_extension_path(name)
            if found is None:
                raise ValueError(f"engine {name!r} is not built on this host and cannot be: no C compiler")
            _DOORS[(name, door)] = boundary.through_the_c_abi(found)
    return _DOORS[(name, door)]


def simulate_of(name: str, door: str | None = None) -> Callable:
    from graph_scale_dynamics.scaleflow import engine_door
    if ENGINES[name].reference:
        return engine_door.run_simulation
    from graph_scale_dynamics.services.worker import engine_rs
    if door is None and ENGINES[name].doors and "in_process" not in ENGINES[name].doors:
        door = ENGINES[name].doors[0]
    if door is None and not os.environ.get(DOOR_ENV):
        return engine_rs.run_simulation
    return engine_rs.simulation_through(door_of(name, door))


def requested_engine(execution: dict | None) -> str:
    name = str((execution or {}).get("engine") or os.environ.get(ENGINE_ENV) or DEFAULT_ENGINE)
    return name.strip().lower()


def resolve_engine(execution: dict | None) -> tuple[str, Callable, str]:
    name = requested_engine(execution)
    engines = available_engines()
    if name not in engines:
        raise ValueError(f"unknown engine {name!r}; known: {sorted(engines)}")
    if not engines[name]["available"]:
        raise ValueError(f"engine {name!r} is not installed on this host (build the {ENGINES[name].extension} "
                         f"extension, or run with {ENGINE_ENV}={REFERENCE})")
    return name, simulate_of(name), engines[name]["fingerprint"]
