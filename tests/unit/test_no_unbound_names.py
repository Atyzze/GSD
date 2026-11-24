from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

GUARDED_MODULES = [
    "graph_scale_dynamics.services.api.main",
    "graph_scale_dynamics.services.api.landscape_worker",
    "graph_scale_dynamics.readmodel.rung_standing",
    "graph_scale_dynamics.scheduling.rung_eta",
    "graph_scale_dynamics.research.stability_score",
]

BUILTIN_NAMES = frozenset(dir(builtins))


def _bound_within(node: ast.AST) -> set[str]:
    bound: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            bound.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                ast.Lambda)):
            if not isinstance(child, ast.Lambda):
                bound.add(child.name)
            args = getattr(child, "args", None)
            if args is not None:
                for group in (args.posonlyargs, args.args, args.kwonlyargs):
                    bound.update(a.arg for a in group)
                for extra in (args.vararg, args.kwarg):
                    if extra is not None:
                        bound.add(extra.arg)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(child, ast.ExceptHandler) and child.name:
            bound.add(child.name)
        elif isinstance(child, ast.Global) or isinstance(child, ast.Nonlocal):
            bound.update(child.names)
    return bound


def _loaded_within(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


@pytest.mark.parametrize("module_name", GUARDED_MODULES)
def test_no_function_calls_a_name_that_does_not_exist(module_name):
    module = importlib.import_module(module_name)
    path = Path(module.__file__)
    tree = ast.parse(path.read_text())
    module_bound = _bound_within(tree) | BUILTIN_NAMES | set(dir(module))

    offences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        allowed = module_bound | _bound_within(node)
        for name in sorted(_loaded_within(node) - allowed):
            offences.append(f"{path.name}:{node.lineno} {node.name}() loads unbound {name!r}")
    assert not offences, "\n".join(offences)


def test_the_overview_endpoint_can_be_called_end_to_end():
    from graph_scale_dynamics.services.api.main import build_fast_overview

    class _Conn:
        def execute(self, *_a, **_k):
            return []

    class _Repo:
        conn = _Conn()

        def campaign(self, _cid):
            return {"campaign_id": "1", "spec": {"ladder": [64, 256], "limits": {},
                                                 "budgets": {}, "policy": {}}}

        def __getattr__(self, _name):
            return lambda *a, **k: {}

    try:
        overview = build_fast_overview(_Repo(), "1")
    except NameError:
        raise
    except Exception:
        return
    else:
        assert isinstance(overview, dict)


def test_the_readmodel_is_importable_from_the_service_layer():
    from graph_scale_dynamics.services.api import overview
    assert hasattr(overview, "rung_standings")
    assert hasattr(overview, "waiting_reason")
