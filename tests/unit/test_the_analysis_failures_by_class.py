from __future__ import annotations

from graph_scale_dynamics.research.analysis_queue_reading import analysis_queue_snapshot


def test_failures_are_split_by_class_into_standing_and_superseded():
    rows = [{"candidate_id": "a", "n": 65536, "seed": 0, "status": "failed", "error_class": "memory_hard_cap"},
            {"candidate_id": "a", "n": 65536, "seed": 1, "status": "failed", "error_class": "memory_hard_cap"},
            {"candidate_id": "a", "n": 65536, "seed": 1, "status": "done", "error_class": None},
            {"candidate_id": "b", "n": 4096, "seed": 2, "status": "failed", "error_class": None},
            {"candidate_id": "b", "n": 4096, "seed": 3, "status": "queued", "next_attempt_utc": None}]
    snapshot = analysis_queue_snapshot({"analysis_work": rows, "collected_utc": "2026-09-29T12:00:00Z"})
    assert snapshot["raw_counts"] == {"failed": 3, "done": 1, "queued": 1}
    assert snapshot["failed_by_class"] == {"memory_hard_cap": {"standing": 1, "superseded": 1},
                                           "unknown": {"standing": 1, "superseded": 0}}
    assert snapshot["raw_claimable_now"] == 1


def test_each_standing_failure_is_named_with_what_each_attempt_held():
    limit = 34 * 1024 ** 3
    rows = [{"candidate_id": "0094d0d4051c" + "0" * 52, "n": 65536, "seed": 0, "status": "failed", "attempts": 2,
             "error_class": "memory_hard_cap"},
            {"candidate_id": "b" * 64, "n": 65536, "seed": 1, "status": "failed", "error_class": "timeout"},
            {"candidate_id": "c" * 64, "n": 16384, "seed": 2, "status": "failed", "error_class": "memory_hard_cap"},
            {"candidate_id": "c" * 64, "n": 16384, "seed": 2, "status": "done"}]
    first = {"candidate_id": rows[0]["candidate_id"], "n": 65536, "seed": 0, "started_utc": "2026-10-12T10:00:00Z",
             "error_class": "memory_hard_cap", "wall_seconds": 812.04, "peak_rss_bytes": 25 * 1024 ** 3,
             "memory_reservation_bytes": 12 * 1024 ** 3,
             "error": f"supervised RSS boundary reached (quarter): observed analyzer process-tree RSS "
                      f"{25 * 1024 ** 3} bytes >= {24 * 1024 ** 3} bytes"}
    second = dict(first, started_utc="2026-10-12T18:00:00Z", peak_rss_bytes=limit + 1,
                  error=f"supervised RSS boundary reached: observed analyzer process-tree RSS {limit + 1} bytes >= "
                        f"{limit} bytes")
    timed = {"candidate_id": "b" * 64, "n": 65536, "seed": 1, "started_utc": "2026-10-13T01:00:00Z",
             "error_class": "timeout", "wall_seconds": 5400.0, "peak_rss_bytes": 3 * 1024 ** 3,
             "error": "analysis timeout after 5400s"}
    snapshot = analysis_queue_snapshot({"analysis_work": rows, "analysis_attempts": [second, timed, first],
                                        "collected_utc": "2026-10-13T15:00:00Z"})
    failures = snapshot["standing_failures"]
    assert [(f["law"], f["n"], f["class"]) for f in failures] == [("0094d0d4051c", 65536, "memory_hard_cap"),
                                                                  ("bbbbbbbbbbbb", 65536, "timeout")]
    held = failures[0]["tries"]
    assert [t["started_utc"] for t in held] == ["2026-10-12T10:00:00Z", "2026-10-12T18:00:00Z"], "in the order run"
    assert (held[0]["peak_rss_gib"], held[0]["ceiling_gib"], held[0]["reserved_gib"]) == (25.0, 24.0, 12.0)
    assert held[1]["ceiling_gib"] == 34.0 and held[1]["peak_rss_gib"] >= held[1]["ceiling_gib"]
    assert failures[1]["tries"][0]["ceiling_gib"] is None and failures[1]["tries"][0]["wall_seconds"] == 5400.0
    assert analysis_queue_snapshot({"analysis_work": rows})["standing_failures"][0]["tries"] == [], (
        "a snapshot without attempts still names the failure")


def test_the_census_cost_reads_each_chain_s_gap_and_the_failed_laws_size_before():
    from graph_scale_dynamics.research.census_cost_reading import census_cost

    def census(method, seconds, size, bound):
        return {"seconds": seconds + 1.0, "largest_component": {
            "size": size, "diameter": {"lower_bound": bound}, "spectral_gap": {"method": method, "seconds": seconds}}}

    law = "8ba7271bbae1" + "0" * 52
    snapshot = {"measurements": [
        {"candidate_id": law, "n": 16384, "seed": 0, "metrics": {"census": {
            "empty": census("lanczos_deflated", 0.5, 2, 1), "given": census("lanczos_deflated", 0.8, 16000, 9),
            "more_given": {"cubic": census("shift_invert", 420.0, 16300, 120)}}}},
        {"candidate_id": "b" * 64, "n": 65536, "seed": 1, "metrics": {"census": {
            "empty": census("shift_invert", 30.0, 65000, 300)}}},
        {"candidate_id": "c" * 64, "n": 4096, "seed": 0, "metrics": {"census": {
            "empty": census("shift_invert", 900.0, 4000, 200)}}}]}
    failed = [{"law": "8ba7271bbae1", "n": 65536, "seed": 0, "class": "memory_hard_cap"}]
    cost = census_cost(snapshot, failed)
    assert cost["by_size_and_method"]["16384"]["shift_invert"] == {
        "reads": 1, "median_seconds": 420.0, "p90_seconds": 420.0, "max_seconds": 420.0}
    assert set(cost["by_size_and_method"]) == {"16384", "65536"}, "4,096 is below the sizes read"
    assert [(r["law"], r["n"], r["chain"], r["seconds"]) for r in cost["slowest"][:2]] == [
        ("8ba7271bbae1", 16384, "cubic", 420.0), ("bbbbbbbbbbbb", 65536, "empty", 30.0)]
    before = cost["failed_laws_before"]
    assert {r["chain"] for r in before} == {"empty", "given", "cubic"} and {r["n"] for r in before} == {16384}
    cubic = next(r for r in before if r["chain"] == "cubic")
    assert (cubic["method"], cubic["giant"], cubic["diameter_lower_bound"]) == ("shift_invert", 16300, 120)


def test_a_standing_failure_keeps_its_row_s_error():
    rows = [{"candidate_id": "a" * 64, "n": 4096, "seed": 1, "status": "failed", "attempts": 1,
             "error": "TRANSIENT_RAW_LOST: producer replay queued"}]
    failure = analysis_queue_snapshot({"analysis_work": rows})["standing_failures"][0]
    assert (failure["class"], failure["error"], failure["tries"]) == (
        "unknown", "TRANSIENT_RAW_LOST: producer replay queued", [])


def test_a_standing_failure_says_when_it_failed():
    rows = [{"candidate_id": "a" * 64, "n": 16384, "seed": 0, "status": "failed", "attempts": 1,
             "updated_utc": "2026-10-14T18:07:30Z", "error": "TRANSIENT_RAW_LOST: producer replay queued"}]
    failure = analysis_queue_snapshot({"analysis_work": rows})["standing_failures"][0]
    assert failure["failed_utc"] == "2026-10-14T18:07:30Z"
