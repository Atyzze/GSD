from __future__ import annotations

import math

import numpy as np
import pytest

from graph_scale_dynamics.measurements import d_s_shape as S
from graph_scale_dynamics.measurements import estimators as M


def _torus(side: int) -> list[tuple[int, int]]:
    edges = []
    for x in range(side):
        for y in range(side):
            i = x * side + y
            edges.append((i, ((x + 1) % side) * side + y))
            edges.append((i, x * side + (y + 1) % side))
    return [tuple(sorted(e)) for e in edges]


def _curve(n: int, edges) -> dict:
    adj = M.build_adjacency(n, edges)
    component = M.largest_component(n, adj)
    return M.return_probability(adj, component, np.random.default_rng(3)), len(component)


def test_the_shape_is_fit_ds_s_own_reduction_kept_whole():
    ret, size = _curve(48 * 48, _torus(48))
    fit = M.fit_ds(ret, size)
    shape = S.shape(ret)
    assert fit["valid"] and shape["measured"] and shape["contract"] == S.SHAPE_CONTRACT
    assert shape["one_over_n_taken_off"] is False
    assert shape["d_s_of_the_window"] == pytest.approx(fit["d_s"], abs=1e-4), "the number is the line the probe fits"
    assert shape["moves_across_the_window"] == pytest.approx(fit["window"]["moves_across_it"], abs=1e-4)
    lo, hi = shape["window"]
    assert hi == len(shape["t"]) and hi - lo == fit["window"]["points"] - 1, "the latest stretch, as the probe takes it"
    assert fit["window"]["t_lo"] < shape["t"][lo] and shape["t"][hi - 1] < fit["window"]["t_hi"], "the same window"
    assert len(shape["t"]) == len(shape["d_s_t"]) >= 6
    assert abs(shape["d_s_of_the_window"] - 2.0) < 0.1 and abs(shape["drift_in_window"]) < 0.5, (
        "a square torus: flat near 2")


def test_the_drift_reads_an_exponent_still_moving():
    t = np.arange(1, 400, dtype=float)
    n = 10 ** 7
    flat = {"t": t.tolist(), "p0": (0.5 * t ** -1.5).tolist(), "component_size": n}
    shape = S.shape(flat)
    assert all(abs(v - 3.0) < 1e-3 for v in shape["d_s_t"]) and abs(shape["drift_whole_range"]) < 1e-3
    exponent = 0.5 + 0.25 * np.log(t)
    rising = {"t": t.tolist(), "p0": (0.5 * np.exp(-np.cumsum(exponent / t))).tolist(), "component_size": n}
    assert S.shape(rising)["drift_whole_range"] > 0.3, "an exponent that grows with time drifts upward"


def test_a_curve_without_a_usable_range_says_so():
    short = {"t": [1, 2, 3, 4], "p0": [0.5, 0.3, 0.2, 0.1], "component_size": 100}
    assert S.shape(short) == {"contract": S.SHAPE_CONTRACT, "measured": False, "one_over_n_taken_off": False,
                              "reason": "the return probability reaches the mixing floor before a usable range"}
    assert S.shape({}) == {"contract": S.SHAPE_CONTRACT, "measured": False, "one_over_n_taken_off": False,
                           "reason": "no curve"}


def test_every_analysis_records_it(monkeypatch):
    from graph_scale_dynamics.scaleflow import one_shot
    ret, size = _curve(16 * 16, _torus(16))

    def analyzer(envelope, seed=0):
        return {"analysis_version": "analysis-5.3.0", "d_s": M.fit_ds(ret, size)}, {"return_probability": ret}

    envelope = {"n": 256, "edges": _torus(16), "rung_terminal": {"reason": "completed"}, "given": {"skipped": True}}
    metrics, _ = one_shot.analyze_one_shot_envelope(envelope, analyzer=analyzer)
    assert metrics["d_s_shape"] == S.shape(ret) and metrics["d_s_shape"]["measured"]
    assert not math.isnan(metrics["d_s_shape"]["d_s_of_the_window"])


def test_the_estimator_closure_does_not_hold_it():
    from graph_scale_dynamics.calibration.fingerprint import measurement_closure
    assert not any(path.endswith("d_s_shape.py") for path in measurement_closure()), (
        "outside the estimator closure, so no calibration cell moves")


def _m(law, n, seed, d_s, se=0.1, drift=None):
    metrics = {"d_s": {"valid": True, "d_s": d_s, "se": se}}
    if drift is not None:
        metrics["d_s_shape"] = {"measured": True, "drift_in_window": drift}
    return {"candidate_id": law, "n": n, "seed": seed, "metrics": metrics}


def test_report_28_reads_how_flat_it_is_and_whether_its_error_covers_its_seeds():
    from graph_scale_dynamics.research.d_s_shape_reading import FLAT_DRIFT, record_section, render
    rows = [_m("a", 1024, 0, 2.0, drift=0.05), _m("a", 1024, 1, 2.1, drift=-0.02), _m("a", 1024, 2, 1.9),
            _m("a", 4096, 0, 2.05), _m("a", 4096, 1, 2.0), _m("a", 4096, 2, 2.1),
            _m("b", 1024, 0, 3.0, drift=0.3), _m("b", 1024, 1, 3.0, drift=0.4), _m("b", 1024, 2, 3.0),
            _m("b", 4096, 0, 4.0), _m("b", 4096, 1, 4.1), _m("b", 4096, 2, 3.9)]
    section = record_section(rows)
    rung = section["by_rung"]["1024"]
    assert rung["laws"] == 2 and rung["seeds_with_a_shape"] == 4 and rung["median_abs_drift"] == pytest.approx(0.175)
    assert rung["coverage"] == {"seeds": 6, "within_1": pytest.approx(4 / 6, abs=1e-4), "within_2": 1.0}, (
        "a seed 0.15 from the others' mean, with errors of 0.1, lies 1.2 combined errors off")
    assert section["flat_before_settled"] == {"flat": {"settled": 1, "moved": 0}, "drifting": {"settled": 0, "moved": 1}}
    assert section["flat_drift_under"] == FLAT_DRIFT
    line = render(section, "T0/16")[0]
    assert line.startswith("  T0/16: d_s's error covers its seeds") and "a flat exponent then 1 settled, 0 moved" in line
