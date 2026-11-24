from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from graph_scale_dynamics.engine import boundary
from graph_scale_dynamics.services.worker import engine_registry as R
from tests.support.engines import require_rust_engine

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.scientific]
TERMS = [{"op": "edge_count", "coeff": -0.4, "k": 0, "scale": "one", "params_k": None},
         {"op": "triangle_count", "coeff": -0.3, "k": 0, "scale": "one", "params_k": None},
         {"op": "degree_anchor", "coeff": 0.2, "k": 4, "scale": "one", "params_k": 4}]


def _mt():
    _version, words, _gauss = random.Random(11).getstate()
    return list(words[:624]), int(words[624])


THE_CLOCK = ("seconds",)


def _plain(found):
    return {key: value for key, value in json.loads(json.dumps(found)).items() if key not in THE_CLOCK}


def _requests():
    words, index = _mt()
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0), (0, 2), (5, 6)]
    return {
        "init_random_graph": {"n": 40, "terms": TERMS, "target_edges": 60, "mt_words": words, "mt_index": index,
                              "energy": 0.0, "energy_is_int": True},
        "init_declared": {"n": 12, "terms": TERMS, "edges": edges, "energy": 0.0, "energy_is_int": True},
        "rebuild_graph": {"n": 12, "terms": TERMS, "edge_list": edges},
        "run_chain": {"n": 40, "terms": TERMS, "beta": 1.5, "p_add": 0.45, "p_del": 0.45, "p_swap": 0.1,
                      "proposal_locality": 0.0, "total_moves": 4000, "start_move": 0, "points": 20,
                      "late_from_move": 3400, "mt_words": words, "mt_index": index, "edge_list": edges,
                      "energy": 0.0, "accounting": None, "trajectory_len": 0},
    }


def test_the_registry_is_the_one_place_an_engine_is_named():
    assert R.REFERENCE == "python" and R.DEFAULT_ENGINE in R.ENGINES
    assert all(engine.doors == ("in_process", "c_abi") for engine in R.ENGINES.values() if not engine.reference)
    named = re.compile(r"import gsd_engine_rs|gsd_engine_rs\.")
    found = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "graph_scale_dynamics").rglob("*.py")
                   if named.search(path.read_text(encoding="utf-8")))
    assert found == ["graph_scale_dynamics/measurements/curvature_probe.py"], (
        "the curvature probe keeps its own door until the recalibration, its source being in the table's key", found)


@pytest.mark.parametrize("operation", boundary.OPERATIONS)
def test_both_doors_of_every_engine_answer_every_operation_alike(operation):
    require_rust_engine()
    for name, engine in R.ENGINES.items():
        if engine.reference:
            continue
        answers = [_plain(R.door_of(name, door)(operation, _requests()[operation])) for door in engine.doors]
        assert answers[0] == answers[1], (name, operation)
        assert json.dumps(answers[0], sort_keys=True) == json.dumps(answers[1], sort_keys=True)


def test_a_fault_comes_back_through_either_door_as_the_same_error():
    require_rust_engine()
    request = dict(_requests()["run_chain"], locality=1.5)
    for door in boundary.DOORS:
        with pytest.raises(ValueError, match="locality must lie in"):
            R.door_of(R.DEFAULT_ENGINE, door)("run_chain", request)
        with pytest.raises(KeyError):
            R.door_of(R.DEFAULT_ENGINE, door)("rebuild_graph", {"n": 4, "terms": TERMS})
        with pytest.raises(boundary.UnknownOperation):
            R.door_of(R.DEFAULT_ENGINE, door)("grow", {})


def test_a_float_crosses_the_c_door_to_the_last_bit():
    require_rust_engine()
    for value in (0.1, 1.0, -2.5e-300, 1e16, 123456789.123456789, 5e-324):
        request = dict(_requests()["init_declared"], energy=value, edges=[])
        for door in boundary.DOORS:
            found = R.door_of(R.DEFAULT_ENGINE, door)("init_declared", request)
            assert found["energy"] == value and isinstance(found["energy"], float), (door, value)
