from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from pathlib import Path

from graph_scale_dynamics.calibration.contract import repository_root
from graph_scale_dynamics.measurements.parsed_code import (
    _bound_names, _Renamer, _serialize, _strip_docstrings, normalized_digest,
)

MEASUREMENT_ENTRY = "graph_scale_dynamics/measurements/estimators.py"
FAMILY_SOURCE = "graph_scale_dynamics/measurements/calibration.py"
FAMILY_MEASUREMENT_KEYS = ("name", "build", "build_seeded", "size", "graph_varies_per_seed")

PACKAGE = "graph_scale_dynamics"


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _module_definitions(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def _family_dicts(tree: ast.Module) -> dict[str, ast.Dict]:
    found: dict[str, ast.Dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if (isinstance(key, ast.Constant) and key.value == "name"
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                found[value.value] = node
    return found


def _family_slice(family_name: str, source_path: Path) -> ast.Module:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    families = _family_dicts(tree)
    if family_name not in families:
        raise KeyError(f"family {family_name!r} is not declared in {FAMILY_SOURCE}")
    definitions = _module_definitions(tree)
    family = families[family_name]
    keys: list[ast.expr] = []
    values: list[ast.expr] = []
    pending: set[str] = set()
    for key, value in zip(family.keys, family.values, strict=True):
        if isinstance(key, ast.Constant) and key.value in FAMILY_MEASUREMENT_KEYS:
            keys.append(key)
            values.append(value)
            pending |= _names_in(value)
    body: list[ast.stmt] = []
    seen: set[str] = set()
    while pending:
        name = min(pending)
        pending.discard(name)
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        node = definitions[name]
        body.append(node)
        pending |= _names_in(node) - seen
    body.sort(key=lambda n: n.lineno)
    body.append(ast.Expr(ast.Dict(keys=keys, values=values)))
    return ast.Module(body=body, type_ignores=[])


def modules_a_family_builds_with(family_name: str, path: Path | None = None) -> list[str]:
    source_path = Path(path) if path is not None else repository_root() / FAMILY_SOURCE
    found: set[str] = set()
    for node in ast.walk(_family_slice(family_name, source_path)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names if alias.name.startswith(PACKAGE + ".")}
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PACKAGE):
            found |= {f"{node.module}.{alias.name}" for alias in node.names} | {node.module}
    return sorted(found)


def family_slice_source(family_name: str, path: Path | None = None) -> str:
    source_path = Path(path) if path is not None else repository_root() / FAMILY_SOURCE
    module = _family_slice(family_name, source_path)
    _strip_docstrings(module)
    bound = _bound_names(module)
    module = _Renamer(bound).visit(module)
    return _serialize(module)


def _package_imports(path: Path) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PACKAGE + "."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PACKAGE + "."):
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def _module_file(root: Path, module: str) -> Path | None:
    relative = Path(*module.split("."))
    for candidate in (root / relative.with_suffix(".py"), root / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def measurement_closure(root: Path | None = None) -> list[str]:
    return import_closure(MEASUREMENT_ENTRY, root)


def import_closure(entry: str, root: Path | None = None) -> list[str]:
    root = Path(root) if root is not None else repository_root()
    start = root / entry
    seen: dict[str, Path] = {entry: start}
    frontier = [start]
    while frontier:
        path = frontier.pop()
        for module in _package_imports(path):
            file = _module_file(root, module)
            if file is None:
                continue
            rel = file.relative_to(root).as_posix()
            if rel not in seen:
                seen[rel] = file
                frontier.append(file)
    return sorted(seen)


def _short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def short_hash(text: str) -> str:
    return _short(text)


def closure_digest(entry: str, root: Path | None = None) -> list[str]:
    base = Path(root) if root is not None else repository_root()
    return [f"{rel}:{normalized_digest(base / rel)}" for rel in import_closure(entry, base)]


@lru_cache(maxsize=None)
def estimator_fingerprint(root: str | None = None) -> str:
    base = Path(root) if root else repository_root()
    joined = "\n".join(f"{rel}:{normalized_digest(base / rel)}" for rel in measurement_closure(base))
    return _short(joined)


@lru_cache(maxsize=None)
def family_fingerprint(family_name: str, root: str | None = None) -> str:
    base = Path(root) if root else repository_root()
    own = family_slice_source(family_name, base / FAMILY_SOURCE)
    built_with = [f"{module}:{normalized_digest(file)}"
                  for module in modules_a_family_builds_with(family_name, base / FAMILY_SOURCE)
                  for file in [_module_file(base, module)] if file is not None]
    return _short("\n".join([own, *built_with]) if built_with else own)


ANALYSIS_SOURCE = "graph_scale_dynamics/measurements/version.py"
ANALYSIS_NAME = "ANALYSIS_VERSION"


@lru_cache(maxsize=None)
def analysis_version(root: str | None = None) -> str:
    base = Path(root) if root else repository_root()
    for node in ast.parse((base / ANALYSIS_SOURCE).read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(target, ast.Name) and target.id == ANALYSIS_NAME for target in node.targets)):
            return str(node.value.value)
    raise ValueError(f"{ANALYSIS_SOURCE} names no {ANALYSIS_NAME}")


def cell_fingerprint(family_name: str, root: str | None = None) -> str:
    return _short(f"{analysis_version(root)}|{estimator_fingerprint(root)}|{family_fingerprint(family_name, root)}")


def what_a_cell_was_measured_by(family_name: str, root: str | None = None) -> dict:
    return {"analysis": analysis_version(root), "estimator_fingerprint": estimator_fingerprint(root),
            "family_fingerprint": family_fingerprint(family_name, root),
            "cell_fingerprint": cell_fingerprint(family_name, root)}


def science_fingerprint() -> str:
    try:
        from graph_scale_dynamics.domain.science_identity import science_fingerprint as _fp
        return _fp()
    except Exception:
        return "unavailable"


def clear_caches() -> None:
    analysis_version.cache_clear()
    estimator_fingerprint.cache_clear()
    family_fingerprint.cache_clear()
