from __future__ import annotations

from graph_scale_dynamics.calibration.deviation import AVAILABILITY_FLOOR, FAILING_STATUSES, _rung_row


def _cell(seed, value, reason=None):
    ch = {"valid": value is not None, "value": value, "se": 0.05 if value is not None else None,
          "reason": reason}
    return {"family": "periodic_cubic_lattice", "parameter": 16, "n": 4096, "seed": seed,
            "status": "ok", "channels": {"d_B": ch, "d_s": {"valid": True, "value": 3.3, "se": 0.9, "reason": None}}}


def _family():
    return {"name": "periodic_cubic_lattice", "expectation": "MEASURE",
            "theory": {"d_B": 3.0, "d_s": 3.0}, "ladder": [{"n": 4096, "parameter": 16}]}


def test_one_seed_in_ten_is_refused_majority_not_within_tolerance():
    cells = {f"periodic_cubic_lattice:16:{s}": _cell(s, 2.3 if s == 1 else None,
                                                   None if s == 1 else "box counts fall exponentially")
             for s in range(10)}
    row = _rung_row(_family(), {"n": 4096, "parameter": 16}, cells, 10)
    d_b = row["channels"]["d_B"]
    assert d_b["valid_fraction"] == 0.1
    assert d_b["availability_floor"] == AVAILABILITY_FLOOR
    assert d_b["status"] == "REFUSED_MAJORITY" and "REFUSED_MAJORITY" in FAILING_STATUSES
    assert d_b["measured"] == 2.3, "the survivors' mean is still reported, just not believed"
    assert row["channels"]["d_s"]["status"] in ("WITHIN_TOLERANCE", "OUT_OF_TOLERANCE")
    assert row["channels"]["d_s"]["valid_fraction"] == 1.0


def test_a_majority_of_seeds_returning_keeps_the_accuracy_verdict():
    cells = {f"periodic_cubic_lattice:16:{s}": _cell(s, 2.9 if s < 8 else None, None if s < 8 else "x")
             for s in range(10)}
    row = _rung_row(_family(), {"n": 4096, "parameter": 16}, cells, 10)
    assert row["channels"]["d_B"]["status"] == "WITHIN_TOLERANCE"
    assert row["channels"]["d_B"]["valid_fraction"] == 0.8
