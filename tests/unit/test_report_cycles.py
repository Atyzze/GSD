from __future__ import annotations

from graph_scale_dynamics.reporting.cycle_record import cycle_row


def _manifest(cycle_id="cyc-1", **cycle):
    body = {"started_utc": "2026-09-01T05:00:00Z",
            "finished_utc": "2026-09-01T05:04:33Z",
            "total_seconds": 273.0, "snapshot_seconds": 142.0,
            "snapshot_decompressed_bytes": 737_000_000,
            "api_bytes_transferred": 4096,
            "trigger_source": "auto",
            "report_seconds": {"P": 41.2, "A": 3.1}}
    body.update(cycle)
    return {"campaign_id": "1", "cycle_id": cycle_id, "cycle_state": "COMPLETE",
            "build_number": 243, "cycle": body}


def test_the_manifest_cycle_block_becomes_a_row():
    row = cycle_row(_manifest())
    assert row["cycle_id"] == "cyc-1" and row["campaign_id"] == "1"
    assert row["total_seconds"] == 273.0 and row["snapshot_seconds"] == 142.0
    assert row["snapshot_decompressed_bytes"] == 737_000_000
    assert row["build_number"] == 243 and row["trigger_source"] == "auto"
    assert row["report_seconds"] == {"P": 41.2, "A": 3.1}
    assert row["cycle_state"] == "COMPLETE"


def test_a_cycle_with_no_id_or_no_start_is_not_a_row():
    assert cycle_row({"campaign_id": "1", "cycle": {"total_seconds": 10.0}}) is None
    assert cycle_row({"cycle_id": "x", "cycle": {"total_seconds": 10.0}}) is None
    assert cycle_row({"cycle_id": "x"}) is None
    assert cycle_row(None) is None


def test_unusable_numbers_do_not_become_durations():
    row = cycle_row(_manifest(total_seconds="not a number",
                              snapshot_decompressed_bytes=None,
                              report_seconds={"P": None, "A": 2.0}))
    assert row["total_seconds"] is None
    assert row["snapshot_decompressed_bytes"] is None
    assert row["report_seconds"] == {"A": 2.0}


def _row(cycle_id, seconds, *, snapshot=None, size=None):
    return cycle_row(_manifest(cycle_id, total_seconds=seconds,
                               snapshot_seconds=snapshot,
                               snapshot_decompressed_bytes=size))


def test_bundle_stale_is_written_by_the_cycle_outcome():
    from graph_scale_dynamics.operations.report_cycle import apply_cycle_outcome
    complete = apply_cycle_outcome({}, state="COMPLETE", cycle_id="c1", revision="r1",
                                   finished_utc="2026-09-06T16:00:00Z")
    assert complete["bundle_stale"] is False
    failed_after = apply_cycle_outcome(complete, state="FAILED", cycle_id="c2", revision=None,
                                       finished_utc="2026-09-06T16:15:00Z", error="boom")
    assert failed_after["bundle_stale"] is True, "a newer cycle ran and the bundle is c1's"
    assert failed_after["bundle_revision"] == "r1"
    never_complete = apply_cycle_outcome({}, state="FAILED", cycle_id="c0", revision=None,
                                         finished_utc="2026-09-06T15:00:00Z", error="boom")
    assert never_complete["bundle_stale"] is False, "nothing to be stale relative to"
