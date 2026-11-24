from __future__ import annotations

import importlib
import os

import pytest

BUILD_HINT = ("build it with tools/build_engine.sh (./tools/prepare_environment.sh on a fresh sandbox); "
              "GSD_ENGINE=python skips these cases on purpose")


def python_engine_requested() -> bool:
    return os.environ.get("GSD_ENGINE", "").strip().lower() == "python"


def every_door_of_every_engine():
    require_rust_engine()
    from graph_scale_dynamics.services.worker import engine_registry as R
    return [(f"{name}:{door}", R.door_of(name, door)) for name, engine in R.ENGINES.items() for door in engine.doors]


def a_chain_request(n: int, terms: list, edges, energy: float, *, total_moves: int = 1, points: int = 1,
                    words=None, index: int = 624, **more) -> dict:
    return {"n": n, "terms": terms, "beta": 1.0, "p_add": 0.5, "p_del": 0.5, "p_swap": 0.0, "proposal_locality": 0.0,
            "total_moves": total_moves, "start_move": 0, "points": points, "late_from_move": None,
            "mt_words": list(words if words is not None else [0] * 623 + [1]), "mt_index": index,
            "edge_list": [list(edge) for edge in edges], "energy": energy, **more}


def require_rust_engine(*, module_level: bool = False):
    if python_engine_requested():
        pytest.skip("GSD_ENGINE=python: this case runs the Rust engine, the default, and is skipped on purpose",
                    allow_module_level=module_level)
    try:
        return importlib.import_module("gsd_engine_rs")
    except ImportError as error:
        pytest.fail(f"the Rust engine is the default and is not installed in this interpreter ({error}); "
                    + BUILD_HINT, pytrace=False)
