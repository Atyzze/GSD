from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fleet_reading", ROOT / "tools" / "fleet_reading.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)


def _bundle(tmp: Path, built: str, laws: int, cost: dict, queued: dict, hours: list | None = None) -> Path:
    root = tmp / f"study_x_{built.replace(':', '-')}"
    part = root / "campaign_1_reports_x"
    part.mkdir(parents=True)
    (root / "study.json").write_text(json.dumps({"built_utc": built, "build_number": 607,
                                                 "campaigns": [{"campaign_id": "1", "laws": laws}]}))
    rows = [{"n": n, "attempts": count, "wall_seconds": seconds} for n, (count, seconds) in cost.items()]
    (part / "16-efficiency.json").write_text(json.dumps({"body": {"cost_by_n": rows}}))
    (part / "14-compute.json").write_text(json.dumps({"body": {"analysis_queue_now": {"raw_counts": {"queued": 3}}}}))
    (part / "25-fleet-and-host.json").write_text(json.dumps({"body": {
        "live_compute_by_campaign": [{"campaign_id": "1", "queued_by_n": queued}],
        "fleet_ladder_by_hour": {"hours": hours or []}}}))
    return root


def test_between_two_bundles_each_size_and_half_is_read_per_hour(tmp_path):
    first = F.read(_bundle(tmp_path, "2026-10-09T00:00:00Z", 100, {4096: (10, 3600.0), 16384: (2, 1800.0)},
                           {"16384": 50}))
    second = F.read(_bundle(tmp_path, "2026-10-09T02:00:00Z", 160, {4096: (20, 7200.0), 16384: (8, 9000.0)},
                            {"16384": 40}))
    found = F.between(first, second)
    assert found["hours"] == 2.0 and found["attempts"] == {"4096": 10, "16384": 6}
    assert found["attempts_per_hour"] == {"4096": 5.0, "16384": 3.0} and found["workers"] == {"4096": 0.5, "16384": 1.0}
    assert found["halves"]["extension_share_of_wall"] == round(7200 / 10800, 3), "two of three workers' time"
    assert (found["laws"], found["laws_per_hour"], found["queued_seeds"]) == (60, 30.0, {"16384": [50, 40]})


LOG = """2026-10-09T00:00:01.100Z [supervisor] coordinator backend: postgresql
2026-10-09T00:00:01.200Z [supervisor] build 609 (f47bb792): installation-stable runtime source id
2026-10-09T00:30:00.000Z [supervisor]
2026-10-09T00:30:00.004Z [supervisor] interrupt: stopping fleet and killing in-flight engine children (durable state is preserved)
2026-10-09T01:00:00.000Z [supervisor] coordinator backend: postgresql
2026-10-09T01:00:00.050Z [supervisor] build 611 (dcf15adb): installation-stable runtime source id
2026-10-09T01:00:02.000Z [supervisor] repair: 2 law(s) stay stopped `failed` for failures of their own (memory_hard_cap 1, timeout 1): 0094d0d405 (campaign 8, N=65536), 1d19794fe2 (campaign 5, N=65536)
2026-10-09T01:20:00.000Z [web] [web] bundle prepared
2026-10-09T01:30:00.000Z [supervisor] coordinator backend: postgresql
2026-10-09T01:30:00.010Z [supervisor] build 611 (dcf15adb): installation-stable runtime source id
"""


def test_the_supervisor_s_log_says_when_the_fleet_stood_and_what_it_left_stopped(tmp_path):
    first = F.read(_bundle(tmp_path / "a", "2026-10-09T00:00:00Z", 100, {4096: (10, 3600.0)}, {}))
    root = _bundle(tmp_path / "b", "2026-10-09T02:00:00Z", 160, {4096: (20, 7200.0)}, {})
    (root / "campaign_1_reports_x" / "evidence").mkdir()
    (root / "campaign_1_reports_x" / "evidence" / "supervisor_tail.log").write_text(LOG)
    second = F.read(root)
    log = second["supervisor"]
    assert [(s["utc"], s["build"]) for s in log["starts"]] == [
        ("2026-10-09T00:00:01Z", 609), ("2026-10-09T01:00:00Z", 611), ("2026-10-09T01:30:00Z", 611)]
    assert [(s["stopped_utc"], s["resumed_utc"]) for s in log["stops"]] == [
        ("2026-10-09T00:30:00Z", "2026-10-09T01:00:00Z"), ("2026-10-09T01:20:00Z", "2026-10-09T01:30:00Z")]
    assert log["stops"][1]["how"].startswith("no stop line"), "the host went down: from the line before"
    left = log["stopped_failed"]
    assert (left["laws"], left["classes"]) == (2, "memory_hard_cap 1, timeout 1")
    assert [(x["law"], x["campaign"], x["n"]) for x in left["named"]] == [("0094d0d405", "8", 65536),
                                                                          ("1d19794fe2", "5", 65536)]
    found = F.between(first, second)
    assert found["stood"]["hours"] == round(40 / 60, 2) and found["stood"]["whole"] is False, "the log starts later"
    assert found["running_hours"] == round(2 - 40 / 60, 2)
    assert found["laws_per_hour"] == 30.0 and found["laws_per_running_hour"] == round(60 / (2 - 40 / 60), 1)
    page = F.render(dict(second, against=found))
    assert "The fleet stood 0.67 of these hours" in page and "`0094d0d405` (campaign 8, 65,536)" in page
    assert "supervisor" not in first and "stood" not in F.between(first, first), "no log, no reading of one"


def test_the_census_cost_is_shown_where_report_14_carries_it(tmp_path):
    root = _bundle(tmp_path, "2026-10-14T00:00:00Z", 10, {4096: (1, 60.0)}, {})
    read = {"law": "8ba7271bbae1", "n": 16384, "seed": 0, "chain": "cubic", "method": "shift_invert",
            "seconds": 420.0, "giant": 16300, "diameter_lower_bound": 120}
    cost = {"from_n": 16384, "by_size_and_method": {"16384": {"shift_invert": {
        "reads": 1, "median_seconds": 420.0, "p90_seconds": 420.0, "max_seconds": 420.0}}},
        "slowest": [read], "failed_laws_before": [read]}
    (root / "campaign_1_reports_x" / "14-compute.json").write_text(json.dumps({"body": {
        "analysis_queue_now": {"raw_counts": {"queued": 3}}, "census_cost": cost}}))
    reading = F.read(root)
    assert reading["census_cost"] == {"1": cost}
    page = F.render(reading)
    assert "## The census's gap at the deep sizes" in page and "| 1 | `8ba7271bbae1` | 16,384 | 0 | cubic |" in page
    older = F.read(_bundle(tmp_path / "older", "2026-10-13T00:00:00Z", 10, {4096: (1, 60.0)}, {}))
    assert "census_cost" not in older and "census's gap" not in F.render(older)

def test_the_ladder_counts_each_hours_own_attempts(tmp_path):
    hours = [{"hour": "h0", "rungs": [{"n": 16384, "attempts": 5, "queued": 9, "running": 1, "queued_analyses": 2}]},
             {"hour": "h1", "rungs": [{"n": 16384, "attempts": 12, "queued": 7, "running": 2, "queued_analyses": 0}]}]
    reading = F.read(_bundle(tmp_path, "2026-10-09T00:00:00Z", 1, {16384: (12, 60.0)}, {}, hours))
    assert [hour["rungs"]["16384"]["attempts"] for hour in reading["ladder"]] == [5, 7], "the counts are cumulative"
    assert reading["ladder_campaign"] == "1" and reading["queued_analyses"] == {"1": 3}
    assert reading["halves"]["extension_share_of_wall"] == 1.0


def test_a_lost_raw_output_is_set_beside_the_fleets_stops():
    lost = "TRANSIENT_RAW_LOST: producer replay queued"
    standing = {"1": [{"law": "a", "n": 16384, "seed": 0, "error": lost, "failed_utc": "2026-10-14T18:20:00Z"},
                      {"law": "a", "n": 16384, "seed": 1, "error": lost, "failed_utc": "2026-10-15T07:40:00Z"},
                      {"law": "b", "n": 65536, "seed": 0, "error": lost, "failed_utc": "2026-10-15T03:00:00Z"},
                      {"law": "c", "n": 4096, "seed": 0, "error": "analysis timeout after 1800s",
                       "failed_utc": "2026-10-15T03:00:00Z"}],
                "2": [{"law": "d", "n": 16384, "seed": 2, "error": lost, "failed_utc": "2026-10-15T09:00:00Z"}]}
    log = {"stops": [{"stopped_utc": "2026-10-14T18:07:09Z", "resumed_utc": "2026-10-15T07:25:24Z"}]}
    found = F.raw_lost(standing, log)
    assert (found["lost"], found["laws"], found["timed"]) == (4, 3, 4)
    assert found["by_size"] == {"16384": 3, "65536": 1}
    assert (found["at_a_stop"], found["while_running"]) == (3, 1), "18:20 and 03:00 while it stood, 07:40 just after"
    untimed = F.raw_lost({"1": [{"law": "a", "n": 4096, "seed": 0, "error": lost}]}, log)
    assert untimed["timed"] == 0 and "at_a_stop" not in untimed
    page = "\n".join(F._render_supervisor(None, None, untimed))
    assert "carries no time on them" in page
    assert F.raw_lost({"1": [standing["1"][3]]}, log) is None, "a timeout is no lost raw output"
