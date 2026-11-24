from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.scaleflow.engine_door import run_simulation
from graph_scale_dynamics.measurements.analysis import analyze_envelope

LAW = {
    "terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": -1.4, "scale": "one"}},
              {"op": "degree_square_sum", "params": {}, "coeff": {"c0": -0.05, "scale": "one"}}],
    "dynamics": {"kind": "equilibrium", "beta": 1.0, "sweeps": 6,
                 "move_mix": {"add": 0.45, "delete": 0.45, "swap": 0.10}},
    "init": "empty",
}

TIMING_KEYS = {"probe_seconds", "probe_seconds_snapshots"}


@pytest.fixture(scope="module")
def measured():
    envelope = run_simulation(LAW, 256, 1, record_points=24)
    metrics, curves = analyze_envelope(envelope, seed=3)
    return envelope, metrics, curves


def test_every_probe_group_reports_its_own_wall_time(measured):
    _, metrics, _ = measured
    seconds = metrics["probe_seconds"]
    assert seconds, "a pass that produced readings must attribute time to a probe"
    assert set(seconds) <= {"d_V", "d_s", "d_B", "d_w"}
    assert "d_B_d_w" not in seconds, "the combined channel is retired"
    for label, value in seconds.items():
        assert isinstance(value, float) and value >= 0.0, (label, value)
    assert metrics["probe_seconds_snapshots"] >= 1


def test_the_timing_is_json_serialisable_so_it_needs_no_schema_change(measured):
    _, metrics, _ = measured
    restored = json.loads(json.dumps(metrics))
    assert restored["probe_seconds"] == metrics["probe_seconds"], (
        "this rides in metrics_json, a free-form text column; if it did not "
        "round-trip it would need a migration and a reinitialise")


def test_no_estimator_output_moved(measured):
    envelope, metrics, curves = measured
    again, again_curves = analyze_envelope(envelope, seed=3)
    left = {k: v for k, v in metrics.items() if k not in TIMING_KEYS}
    right = {k: v for k, v in again.items() if k not in TIMING_KEYS}
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True), (
        "analysis is deterministic in its seed; every metric must be identical")
    assert json.dumps(curves, sort_keys=True) == json.dumps(again_curves, sort_keys=True)
    assert set(metrics) - set(right) == TIMING_KEYS


def test_the_timing_is_of_the_one_state_a_chain_is_read_at(measured):
    envelope, metrics, _ = measured
    assert "snapshots" not in CL.block(envelope, CL.FROM_EMPTY) and metrics["probe_seconds_snapshots"] == 1, "a chain is read at its end"
    assert sum(metrics["probe_seconds"].values()) > 0.0


def test_a_graph_below_the_measurable_floor_still_reports_a_timing_block():
    envelope = run_simulation(LAW, 8, 1, record_points=4)
    metrics, _ = analyze_envelope(envelope, seed=3)
    assert "probe_seconds" in metrics, (
        "a pass where every probe refused must still say so with an empty "
        "block, rather than omitting the key and looking like an old record")
    assert isinstance(metrics["probe_seconds"], dict)
