from __future__ import annotations

import pytest

from graph_scale_dynamics.measurements.calibration import CALIBRATION_FAMILIES
from graph_scale_dynamics.services.calibration_core import (
    SUMMARY_DROPS, probe_ladder_point)

RING = next(f for f in CALIBRATION_FAMILIES if f["name"] == "periodic_ring")


@pytest.fixture(scope="module")
def cell() -> dict:
    return probe_ladder_point(RING, 256, 2)


@pytest.fixture(scope="module")
def summary() -> dict:
    import numpy as np

    from graph_scale_dynamics.measurements.estimators import _measure_graph
    from graph_scale_dynamics.scaleflow.flow import rung_summary

    n, edges = RING["build"](256)
    return rung_summary([
        _measure_graph(n, edges, np.random.default_rng(seed), measure_geometry=True)[0]
        for seed in range(2)])


def test_every_field_the_summary_produces_reaches_the_cell(cell, summary):
    produced = {k for k, v in summary.items() if v is not None}
    lost = sorted(produced - set(cell) - set(SUMMARY_DROPS))
    assert not lost, (
        f"the rung summary produces these and the atlas cell never sees them: {lost}. "
        "Carry them, or name them in SUMMARY_DROPS with a reason.")


def test_every_drop_is_named_with_a_reason():
    assert SUMMARY_DROPS, "the drops are declared, even when the set is small"
    for key, reason in SUMMARY_DROPS.items():
        assert isinstance(reason, str) and len(reason) > 20, (
            f"{key} is dropped without saying why")


def test_the_four_channels_are_dropped_because_they_were_restructured(cell):
    for channel in ("d_s", "d_B", "d_w", "d_V"):
        assert channel in SUMMARY_DROPS
        assert channel in cell["channels"], (
            f"{channel} is dropped from the top level and is not in `channels` either")
        assert "measured" in cell["channels"][channel]


def test_the_calibration_evidence_arrives_with_the_projection(cell):
    assert "d_s_diffusive_evidence" not in SUMMARY_DROPS
    assert cell["d_s_diffusive_evidence"] is not None


def test_the_refusal_counts_reach_the_atlas(cell):
    assert "probe_refusals" in cell
    assert set(cell["probe_refusals"]) == {"d_s", "d_V", "d_B", "d_w"}


def test_the_cell_does_not_ship_a_column_that_is_null_on_every_cell(cell):
    dead = sorted(k for k, v in cell.items() if v is None)
    assert not dead, (
        f"these are written on every cell and can never carry a value here: {dead}")


def test_the_inversion_does_not_move_a_calibration_fingerprint():
    from graph_scale_dynamics.calibration import fingerprint as FP

    closure = FP.estimator_fingerprint(None)
    assert isinstance(closure, str) and closure
    import graph_scale_dynamics.calibration.fingerprint as fp_module
    source = (fp_module.MEASUREMENT_ENTRY, fp_module.FAMILY_SOURCE)
    assert "services/calibration_core.py" not in source


def test_an_identity_projection_is_left_as_an_allowlist_on_purpose():
    from graph_scale_dynamics.observability import telemetry_aggregation as ta

    work = [{"type": "simulation", "work_id": "w1", "campaign_id": "1",
             "candidate_id": "c1", "n": 64, "seed": 0, "owner": None,
             "stage": "base", "requested_by": "controller", "lease_generation": 3,
             "producer_job": None, "status": "queued"}]
    before = ta._work_identity(work)
    after = ta._work_identity([dict(work[0], observed_utc="2026-09-12T00:00:01Z")])
    assert before == after, (
        "a field the identity does not declare changed the identity; this "
        "projection is an allowlist on purpose")
