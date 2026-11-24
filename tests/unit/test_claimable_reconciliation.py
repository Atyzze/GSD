from __future__ import annotations

from graph_scale_dynamics.operations.compute_ecology import current_capacity_diagnosis

CAMPAIGN_5_QUEUE = {
    "analysis_claimable_now": 590,
    "analysis_deferred": 0,
    "analysis_leased": 0,
}


def _snapshot(*, host_analysis_backlog=0, active_analysis_claims=0, total_slots=32):
    return {
        "campaign_id": "5",
        "collected_utc": "2026-09-13T15:39:49Z",
        "active_campaign_count": 1,
        "host_analysis_backlog": host_analysis_backlog,
        "host_active_analysis_claims": active_analysis_claims,
        "host_simulation_work": {"leased": 0, "queued": 0},
        "scheduler_snapshot": {
            "total_slots": total_slots, "paused": False,
            "leased_simulations": 0, "queued_simulations": 0,
            "analysis_backlog": host_analysis_backlog,
        },
        "memory_reservation_snapshot": {"total": 0, "budget": 37452568167},
        "latest_telemetry": {
            "memory_used_bytes": 60036722970, "memory_total_bytes": 98748137472,
            "cpu_percent": 15.07, "active_analyses": 0,
            "sampled_utc": "2026-09-13T15:38:58Z",
        },
        "recent_memory_refusals": [],
    }


def test_a_stale_cache_does_not_zero_out_the_durable_queue():
    diagnosis = current_capacity_diagnosis(_snapshot(), CAMPAIGN_5_QUEUE, {})
    assert diagnosis["work"]["claimable_analyses"] == 590, (
        "590 durable rows were runnable; the page reported 0 because a cached "
        f"backlog of 0 won: {diagnosis['work']}")
    assert diagnosis["work"]["claimable_total"] == 590


def test_the_verdict_changes_from_idle_to_underfill():
    diagnosis = current_capacity_diagnosis(_snapshot(), CAMPAIGN_5_QUEUE, {})
    assert diagnosis["state"] == "SCHEDULER_UNDERFILL", (
        "runnable work beside 32 unused slots is scheduler underfill, not an "
        f"idle pipeline: {diagnosis['state']}")
    assert diagnosis["severity"] == "error", "an operator must be able to see this one"
    assert "no claimable work" not in diagnosis["explanation"], (
        "the page must stop asserting the opposite of its own queue")


def test_the_disagreement_is_published_not_absorbed():
    diagnosis = current_capacity_diagnosis(_snapshot(), CAMPAIGN_5_QUEUE, {})
    source = diagnosis["claimable_analysis_source"]
    assert source["from_durable_queue"] == 590
    assert source["from_scheduler_state"] == 0
    assert source["used"] == 590
    assert source["scheduler_state_behind_queue"] is True
    assert "stale" in diagnosis["explanation"].lower(), (
        "the verdict line itself must say the scheduler figures beside it are stale")


def test_a_larger_host_backlog_still_wins_because_the_host_is_the_superset():
    snapshot = _snapshot(host_analysis_backlog=900, active_analysis_claims=10)
    diagnosis = current_capacity_diagnosis(snapshot, CAMPAIGN_5_QUEUE, {})
    source = diagnosis["claimable_analysis_source"]
    assert source["from_scheduler_state"] == 890
    assert source["used"] == 890, "a fleet running other campaigns has more work, not less"
    assert source["scheduler_state_behind_queue"] is False
    assert "stale" not in diagnosis["explanation"].lower()


def test_an_agreeing_pair_is_left_alone():
    snapshot = _snapshot(host_analysis_backlog=590)
    diagnosis = current_capacity_diagnosis(snapshot, CAMPAIGN_5_QUEUE, {})
    source = diagnosis["claimable_analysis_source"]
    assert source["used"] == source["from_durable_queue"] == source["from_scheduler_state"] == 590
    assert source["scheduler_state_behind_queue"] is False


def test_a_genuinely_empty_queue_still_reads_as_idle():
    snapshot = _snapshot(host_analysis_backlog=0)
    diagnosis = current_capacity_diagnosis(
        snapshot, {"analysis_claimable_now": 0, "analysis_deferred": 0, "analysis_leased": 0},
        {})
    assert diagnosis["work"]["claimable_total"] == 0
    assert diagnosis["state"] == "PIPELINE_IDLE"
    assert diagnosis["claimable_analysis_source"]["scheduler_state_behind_queue"] is False


def test_a_snapshot_without_scheduler_state_falls_back_to_the_queue():
    snapshot = _snapshot()
    snapshot.pop("host_analysis_backlog")
    diagnosis = current_capacity_diagnosis(snapshot, CAMPAIGN_5_QUEUE, {})
    source = diagnosis["claimable_analysis_source"]
    assert source["from_scheduler_state"] is None
    assert source["used"] == 590
    assert source["scheduler_state_behind_queue"] is False
