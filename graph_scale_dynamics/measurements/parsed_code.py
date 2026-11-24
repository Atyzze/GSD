from __future__ import annotations

import ast
import hashlib
from pathlib import Path


_DOCSTRING_HOSTS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_HOSTS) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body = node.body[1:] or [ast.Pass()]


def _bound_names(tree: ast.AST) -> set[str]:
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.alias):
            bound.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            bound.add(node.name)
    return bound


class _Renamer(ast.NodeTransformer):
    def __init__(self, bound: set[str]):
        self.bound = bound
        self.table: dict[str, str] = {}

    def canon(self, name: str | None) -> str | None:
        if name is None:
            return None
        if name not in self.bound:
            return name
        if name not in self.table:
            self.table[name] = f"_v{len(self.table)}"
        return self.table[name]

    def visit_Name(self, node):
        node.id = self.canon(node.id)
        return node

    def visit_arg(self, node):
        node.arg = self.canon(node.arg)
        self.generic_visit(node)
        return node

    def _visit_def(self, node):
        node.name = self.canon(node.name)
        self.generic_visit(node)
        return node

    visit_FunctionDef = _visit_def
    visit_AsyncFunctionDef = _visit_def
    visit_ClassDef = _visit_def

    def visit_alias(self, node):
        if node.asname is not None:
            node.asname = self.canon(node.asname)
        else:
            self.canon(node.name.split(".")[0])
        return node

    def visit_ExceptHandler(self, node):
        node.name = self.canon(node.name)
        self.generic_visit(node)
        return node

    def visit_Global(self, node):
        node.names = [self.canon(n) for n in node.names]
        return node

    visit_Nonlocal = visit_Global

    def visit_MatchAs(self, node):
        node.name = self.canon(node.name)
        self.generic_visit(node)
        return node

    def visit_MatchStar(self, node):
        node.name = self.canon(node.name)
        return node


def _serialize(node) -> str:
    if isinstance(node, ast.AST):
        parts = []
        for field in node._fields:
            value = getattr(node, field, None)
            if value is None or value == [] or field == "ctx":
                continue
            parts.append(f"{field}={_serialize(value)}")
        return f"{type(node).__name__}({','.join(parts)})"
    if isinstance(node, list):
        return "[" + ",".join(_serialize(v) for v in node) + "]"
    if isinstance(node, (str, bytes)):
        return repr(node)
    if isinstance(node, float):
        return repr(float(node))
    return repr(node)


def normalize_module(source: str) -> str:
    tree = ast.parse(source)
    _strip_docstrings(tree)
    bound = _bound_names(tree)
    renamer = _Renamer(bound)
    tree = renamer.visit(tree)
    return _serialize(tree)


def normalized_digest(path: Path) -> str:
    return hashlib.sha256(normalize_module(Path(path).read_text(encoding="utf-8"))
                          .encode("utf-8")).hexdigest()


def normalized_function_digest(function) -> str:
    import inspect
    import textwrap
    return hashlib.sha256(normalize_module(textwrap.dedent(inspect.getsource(function)))
                          .encode("utf-8")).hexdigest()


def source_digest(path: Path) -> str:
    path = Path(path)
    if path.suffix == ".py":
        return normalized_digest(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()
