from __future__ import annotations

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements.analysis import analyze_envelope
from graph_scale_dynamics.measurements.estimators import _measure_graph
from graph_scale_dynamics.observability import attempt_cost
from graph_scale_dynamics.services.worker import engine_rs
from tests.support.engines import require_rust_engine
from graph_scale_dynamics.scaleflow import engine_door


def test_a_process_reads_its_own_bytes_and_cpu_and_the_difference_is_what_it_did(tmp_path):
    before = attempt_cost.snapshot()
    (tmp_path / "x").write_bytes(b"x" * 100000)
    sum(i * i for i in range(200000))
    after = attempt_cost.snapshot()
    moved = attempt_cost.delta(before, after)
    assert moved["io"]["wchar"] >= 100000 and moved["cpu_seconds"] >= 0
    record = attempt_cost.record({"io": {"write_bytes": 5}}, before)
    assert record["child"] == {"io": {"write_bytes": 5}} and "cpu_seconds" in record["bookkeeping"]


def test_the_workers_own_bytes_are_its_delta_less_the_reaped_childs():
    start = {"io": {"write_bytes": 1000, "wchar": 1000}, "cpu_seconds": 1.0}
    real = attempt_cost.snapshot
    try:
        attempt_cost.snapshot = lambda: {"io": {"write_bytes": 1500, "wchar": 1600}, "cpu_seconds": 1.2}
        record = attempt_cost.record({"io": {"write_bytes": 480, "wchar": 550}}, start)
    finally:
        attempt_cost.snapshot = real
    assert record["bookkeeping"]["io"] == {"write_bytes": 20, "wchar": 50}
    assert record["bookkeeping_io_including_child"] == {"write_bytes": 500, "wchar": 600}
    assert abs(record["bookkeeping"]["cpu_seconds"] - 0.2) < 1e-9


def _torus(k):
    return sorted({(min(v, w), max(v, w)) for x in range(k) for y in range(k) for v in [x * k + y]
                   for w in (((x + 1) % k) * k + y, x * k + (y + 1) % k)})


def test_the_box_counts_and_the_walk_are_kept_and_the_numbers_do_not_move():
    result, curves = _measure_graph(1024, _torus(32), np.random.default_rng(3), measure_geometry=True)
    assert result["d_B"]["valid"] and result["d_w"]["valid"], "the smallest square lattice both probes read"
    assert curves["box_covering"]["box_counts"] and curves["walk_displacement"]["mean_square_displacement"]
    again, _ = _measure_graph(1024, _torus(32), np.random.default_rng(3), measure_geometry=True)
    assert result["d_B"] == again["d_B"] and result["d_w"] == again["d_w"]
    assert "_geometry_curves" not in result


def test_a_chain_s_curves_are_kept_for_its_last_state():
    law = {"dsl_version": 1, "init": "empty",
           "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.25, "scale": "log_N"}},
                     {"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 0.3, "scale": "one"}}],
           "dynamics": {"kind": "equilibrium", "beta": 1.0,
                        "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 20}}
    require_rust_engine()
    envelope = engine_door.simulate_of("rust")(law, 256, 1)
    _metrics, at_its_end = analyze_envelope(envelope, seed=1)
    assert CL.block(envelope, CL.FROM_EMPTY)["late_change"], "the engine keeps a late change, and no copy of a graph"
    assert [c["move"] for c in at_its_end["configurations"]] == ["final"], "a chain is read at its end"
    assert all(c["curves"].get("return_probability") for c in at_its_end["configurations"])
    assert at_its_end["return_probability"] == at_its_end["configurations"][0]["curves"]["return_probability"]
