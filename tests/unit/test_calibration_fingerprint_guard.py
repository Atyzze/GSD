from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.calibration.fingerprint import estimator_fingerprint, measurement_closure

ROOT = Path(__file__).resolve().parents[2]


def test_the_runtime_reproduces_the_fingerprint_of_the_table_in_force():
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    from tests.support.calibration_table import require_table
    table = require_table()
    stored = str(table.get("estimator_fingerprint") or "")
    assert stored, "the shipped calibration table must record the fingerprint it was measured under"
    assert estimator_fingerprint() == stored, (
        "an estimator source changed and the calibration table no longer matches this runtime. "
        "If the change is scientific, re-measure with tools/adopt_calibration.py --apply and say so "
        "in the build notes. If it is not, revert it: the closure is "
        f"{', '.join(measurement_closure())}."
    )


def test_the_closure_is_the_set_this_guard_watches():
    assert set(measurement_closure()) == {
        "graph_scale_dynamics/measurements/box_covering.py",
        "graph_scale_dynamics/measurements/estimators.py",
        "graph_scale_dynamics/measurements/fits.py",
        "graph_scale_dynamics/measurements/walk_dimension.py",
    }


def test_a_seed_measured_under_another_estimator_is_declared():
    from graph_scale_dynamics.calibration import owed
    stale = owed.stale_cells()
    if not stale:
        assert owed.recalibration_owed() is None
        return
    document = owed.declaration()
    assert document is not None, (
        f"{len(stale)} seed cells were measured under another estimator and no build declared the recalibration "
        "it owes: re-measure them, or write calibration/recalibration_owed.json and say why in the build notes")
    assert document["estimator_fingerprint"] == estimator_fingerprint(), (
        "the declaration covers an earlier estimator; this tree's changed again since it was written")
    assert document["owed"]["cells"] == len(stale), "the declaration owes exactly the stale cells"
    assert owed.recalibration_owed() is not None
