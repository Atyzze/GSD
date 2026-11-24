from __future__ import annotations

import pytest

from graph_scale_dynamics.research.all_rung_lanes import _rung_row

BASE_SIZES = [64, 256, 1024, 4096, 16384]


def _real_rung_summary() -> dict:
    return {
        "summary_contract": "rung-summary-1",
        "seeds": 3,
        "d_s": {"between_seed_sd": 0.0145, "mean": 2.005, "n_seeds": 3,
                "se": 0.177, "within_seeds_with_se": 3},
        "d_V": {"between_seed_sd": 0.011, "mean": 0.932, "n_seeds": 3,
                "se": 0.111, "within_seeds_with_se": 3},
        "d_B": {"mean": None, "n_seeds": 0, "se": None},
        "d_w": {"mean": None, "n_seeds": 0, "se": None},
        "d_s_valid_fraction": 1.0,
        "d_s_no_window_fraction": 0.0,
        "mean_degree": {"mean": 3.9679, "n_seeds": 3, "se": None},
        "clustering": {"mean": 0.00059, "n_seeds": 3, "se": None},
        "connected_fraction": {"mean": 1.0, "n_seeds": 3, "se": None},
        "stationarity_drift": {"mean": -1.0e-5, "n_seeds": 3, "se": None},
        "effective_samples": 32.2,
        "iat_sweeps": 8.97,
        "probe_refusals": {"d_B": {"NOT_POWER_LAW": 3},
                           "d_w": {"EXPONENTIAL_GROWTH": 3},
                           "d_s": {}, "d_V": {}},
    }


def _real_measurement() -> dict:
    return {
        "candidate_id": "abc", "n": 16384, "seed": 0,
        "metrics": {
            "analysis_version": "analysis-3.0.0",
            "d_s": {"d_s": 2.005, "se": 0.177, "valid": True,
                    "local_slopes": [-0.48, -0.50, -0.51],
                    "window": {"t_lo": 8, "t_hi": 17, "points": 7}},
            "d_V": {"d_V_window": 0.932, "se": 0.228, "valid": True,
                    "exponential_growth_flag": True, "log_curvature": 0.07},
            "d_w": {"d_w": 1.89, "se": 0.21, "valid": True},
            "d_B": {"valid": False, "refusal": "NOT_POWER_LAW", "reason": "..."},
            "health": {"connected_fraction": 1.0, "mean_degree": 3.9679,
                       "clustering": 0.00059, "two_core_fraction": 1.0,
                       "degree_second_moment": 15.78, "max_degree": 5,
                       "rung_terminal": {"classification": "EQUILIBRATED_ACTIVE"}},
        },
    }


def test_the_continuation_lane_reads_the_keys_storage_holds():
    row = _rung_row({"n": 16384, "summary": _real_rung_summary()},
                    _real_measurement()["metrics"])
    assert row["d_s"]["value"] == pytest.approx(2.005)
    assert row["d_s"]["uncertainty"] == pytest.approx(0.177)
    assert row["d_s"]["status"] == "measured"
    assert row["d_V"]["value"] == pytest.approx(0.932)
    assert row["seeds"] == 3
    assert row["mean_degree"] == pytest.approx(3.9679)
    assert row["connectivity"] == pytest.approx(1.0)
    assert row["ess"] == pytest.approx(32.2)
    assert row["iat"] == pytest.approx(8.97)
    assert row["equilibration_status"] == "EQUILIBRATED_ACTIVE"
    assert row["evidence_scope"] == "selected_deep"


def test_a_refused_probe_reports_its_refusal_rather_than_a_bare_null():
    row = _rung_row({"n": 16384, "summary": _real_rung_summary()}, {})
    assert row["d_B"]["value"] is None
    assert row["d_B"]["status"] == "NOT_POWER_LAW", (
        "EXPONENTIAL_GROWTH and NOT_POWER_LAW are findings about the geometry; "
        "a lane that prints null for them loses the finding")
    assert row["d_w"]["status"] == "EXPONENTIAL_GROWTH"


def test_the_pre_369_key_names_are_not_what_storage_writes():
    summary = _real_rung_summary()
    assert "value" not in summary["d_s"]
    assert "uncertainty" not in summary["d_s"]
    assert "status" not in summary["d_s"]
    assert "seeds" not in summary["d_s"]


def test_no_measurement_block_has_ever_carried_a_mean():
    metrics = _real_measurement()["metrics"]
    for probe in ("d_s", "d_V", "d_w", "d_B"):
        assert "mean" not in metrics[probe], (
            f"{probe} carries no `mean`; asking for one returned None for every "
            "measurement at every rung and emptied seed_agreement entirely")
