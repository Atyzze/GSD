from __future__ import annotations

import hashlib
import math
import time
from functools import lru_cache
from pathlib import Path

CONTRACT = "gsd-start-reading-1"
SEEDS = 3
READ_FROM_NODES = 1024
COUNTED = ("mean_degree", "triangles_per_node", "squares_per_node", "giant_fraction", "kappa")
MEASURABLE = 16


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _per_node(value, n: int) -> float | None:
    value = _number(value)
    return None if value is None else value / max(1, int(n))


def is_a_lattice_start(family: str, n) -> bool:
    from graph_scale_dynamics.measurements import known_answers
    from graph_scale_dynamics.measurements.calibration import SIZES_A_LAW_RUNS
    if not isinstance(n, int) or isinstance(n, bool):
        return False
    return n >= READ_FROM_NODES and n in SIZES_A_LAW_RUNS and known_answers.reaches(str(family), n)


def wanted(family: str, n, seed) -> bool:
    return int(seed) < SEEDS and is_a_lattice_start(family, n)


def reach(n: int, edges, seed: int) -> float | None:
    import numpy as np

    from graph_scale_dynamics.measurements import estimators
    adjacency = estimators.build_adjacency(int(n), edges)
    component = estimators.largest_component(int(n), adjacency)
    if len(component) < MEASURABLE:
        return None
    for_the_balls = estimators.streams_of(np.random.default_rng(int(seed)), 3)[0]
    balls = estimators.volume_growth(adjacency, component, for_the_balls,
                                     sources=estimators.sources_for_the_verdict(len(component)))
    return _number(balls.get("half_volume_radius"))


def read(n: int, edges, seed: int) -> dict:
    from graph_scale_dynamics.measurements.curvature_probe import read as curvature
    from graph_scale_dynamics.measurements.random_starts import _random_wiring
    from graph_scale_dynamics.measurements.structure_census import census
    n = int(n)
    counted = census(n, edges)
    kappa = curvature(n, edges)
    wiring = _random_wiring(n, edges, seed=int(seed))
    return {"mean_degree": 2.0 * float(counted.get("edges") or 0) / n,
            "triangles_per_node": _per_node((counted.get("cliques") or {}).get("triangles"), n),
            "squares_per_node": _per_node(counted.get("squares"), n),
            "giant_fraction": _per_node((counted.get("largest_component") or {}).get("size"), n),
            "kappa": _number(kappa.get("mean")) if kappa.get("measured") else None,
            "random_wiring": {"reach": reach(n, wiring, seed), "mean_degree": 2.0 * len(wiring) / n}}


@lru_cache(maxsize=None)
def sources() -> dict:
    from graph_scale_dynamics.measurements import curvature_probe, structure_census
    from graph_scale_dynamics.measurements.parsed_code import normalized_digest, normalized_function_digest
    from graph_scale_dynamics.measurements.random_starts import _random_wiring
    found = {module.__name__: normalized_digest(Path(module.__file__))
             for module in (structure_census, curvature_probe)}
    for function in (_random_wiring, read, reach):
        found[f"{function.__module__}.{function.__name__}"] = normalized_function_digest(function)
    return found


def fingerprint() -> str:
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(sources().items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def measure(n: int, edges, seed: int) -> dict:
    started = time.monotonic()
    record = {"contract": CONTRACT, "fingerprint": fingerprint()}
    try:
        record.update(read(n, edges, seed))
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def current(cell: dict | None) -> bool:
    block = cell.get("start") if isinstance(cell, dict) else None
    return isinstance(block, dict) and not block.get("error") and block.get("fingerprint") == fingerprint()


def current_where_wanted(cell: dict | None) -> bool:
    if not isinstance(cell, dict):
        return False
    try:
        asked = wanted(str(cell.get("family")), cell.get("n"), cell.get("seed") or 0)
    except (TypeError, ValueError):
        return False
    return current(cell) if asked else True
