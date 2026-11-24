from __future__ import annotations

from graph_scale_dynamics.services.api import landscape_worker as W


def _rung(n: int, withheld: dict) -> dict:
    return {"n": n, "summary": {"withheld": withheld}}


def test_the_deepest_withheld_value_of_a_probe_with_no_reading():
    entry = {"rungs": [
        _rung(1024, {"d_B": {"values": [2.0], "mean": 2.0, "seeds": 1, "reasons": {"NOT_POWER_LAW": 1}}}),
        _rung(4096, {"d_B": {"values": [3.1, 3.3], "mean": 3.2, "seeds": 2, "reasons": {"NOT_POWER_LAW": 2}},
                     "d_w": {"values": [float("nan")], "mean": float("nan"), "seeds": 1, "reasons": {}},
                     "d_V": {"values": [9.0], "mean": 9.0, "seeds": 1, "reasons": {"EXPONENTIAL_GROWTH": 1}}}),
        _rung(16384, {}),
    ]}
    point = {"d_s_estimate": 3.4, "d_v_estimate": 2.6, "d_b_estimate": None, "d_w_estimate": None}
    found = W.withheld_readings(entry, point)
    assert found == {"d_B": {"value": 3.2, "n": 4096, "seeds": 2, "reasons": {"NOT_POWER_LAW": 2}}}, \
        "the deepest rung that kept one; a reading is never replaced; no number is no mark"


def test_only_a_settled_band_carries_them():
    assert W.SETTLED_BANDS == frozenset(W.LANDSCAPE_BANDS) - {W.BAND_FLOWING}
