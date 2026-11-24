


def test_a_manifest_without_a_start_still_records_the_cycle_for_the_cadence_rule():
    from graph_scale_dynamics.reporting.cycle_record import cycle_row
    row = cycle_row({"cycle_id": "c1", "campaign_id": "6", "cycle_state": "COMPLETE",
                     "cycle": {"finished_utc": "2026-09-06T13:44:57Z", "total_seconds": 408.356,
                               "snapshot_seconds": 211.4}})
    assert row is not None
    assert row["finished_utc"] == "2026-09-06T13:44:57Z"
    assert row["started_utc"] == "2026-09-06T13:38:08Z"
