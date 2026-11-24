from __future__ import annotations

from graph_scale_dynamics.research.density_coupling import (
    MIN_READINGS, OUTLIER_FLOORS, density_coupling,
)

FLOORS = {"d_s": 0.24327579419065748}


def rows_on_a_line(count: int, *, n: int = 65536, slope: float = 1.0,
                   intercept: float = -1.0, wobble: float = 0.0,
                   start: float = 2.0, step: float = 0.02) -> list[dict]:
    out = []
    for i in range(count):
        degree = start + i * step
        value = intercept + slope * degree + (wobble if i % 2 else -wobble)
        out.append({"candidate_id": f"{i:064x}", "sizes": [n],
                    "mean_degree": [degree], "probes": {"d_s": [value]}})
    return out


def test_a_population_on_one_curve_is_reported_as_collapsed():
    out = density_coupling(rows_on_a_line(60), floors=FLOORS)
    rung = out["by_rung"]["65536"]
    assert rung["collapsed_onto_one_curve"] is True
    assert rung["r2"] > 0.999
    assert rung["scatter_in_noise_floors"] < 0.05
    assert out["departure_count"] == 0
    assert "mean degree read through a spectral probe" in out["reading"]


def test_a_loose_population_flags_nothing_however_far_a_law_sits():
    rows = rows_on_a_line(60, wobble=0.6)
    rows.append({"candidate_id": "f" * 64, "sizes": [65536],
                 "mean_degree": [3.0], "probes": {"d_s": [9.0]}})
    out = density_coupling(rows, floors=FLOORS)
    rung = out["by_rung"]["65536"]
    assert rung["collapsed_onto_one_curve"] is False
    assert rung["departures"] is None
    assert "no line tight enough" in rung["why_no_departures"]
    assert out["departure_count"] == 0


def test_a_law_that_leaves_a_tight_line_is_found_and_measured_both_ways():
    rows = rows_on_a_line(60)
    rows.append({"candidate_id": "a" * 64, "sizes": [65536],
                 "mean_degree": [2.5], "probes": {"d_s": [1.5 - 3 * FLOORS["d_s"]]}})
    out = density_coupling(rows, floors=FLOORS)
    assert out["departure_count"] == 1
    found = out["departures"][0]
    assert found["candidate_id"] == "a" * 64
    assert found["residual_in_noise_floors"] >= OUTLIER_FLOORS
    assert found["residual_in_population_scatter"] > found["residual_in_noise_floors"]
    assert "where a geometry would show up first" in out["reading"]


def test_a_rung_with_too_few_readings_is_not_fitted():
    out = density_coupling(rows_on_a_line(MIN_READINGS - 1), floors=FLOORS)
    rung = out["by_rung"]["65536"]
    assert rung.get("r2") is None
    assert f"fewer than {MIN_READINGS}" in rung["why"]


def test_one_density_cannot_be_fitted_and_says_so():
    rows = [{"candidate_id": f"{i:064x}", "sizes": [65536], "mean_degree": [4.0],
             "probes": {"d_s": [2.8 + 0.001 * i]}} for i in range(40)]
    out = density_coupling(rows, floors=FLOORS)
    assert out["by_rung"]["65536"].get("r2") is None
    assert "nothing to fit" in out["by_rung"]["65536"]["why"]


def test_without_a_calibration_floor_nothing_is_called_collapsed():
    out = density_coupling(rows_on_a_line(60), floors=None)
    rung = out["by_rung"]["65536"]
    assert rung["scatter_in_noise_floors"] is None
    assert rung["collapsed_onto_one_curve"] is False
    assert out["departure_count"] == 0


def test_the_measure_gates_nothing():
    out = density_coupling(rows_on_a_line(60), floors=FLOORS)
    assert out["descriptive_advisory_only"] is True and out["gates_nothing"] is True
