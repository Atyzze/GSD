from __future__ import annotations

from pathlib import Path

import pytest

from graph_scale_dynamics.readmodel.rung_standing import rung_standings, waiting_reason

ROOT = Path(__file__).resolve().parents[2]
LADDER = [64, 256, 1024, 4096, 16384]


def job(n, status, error=None):
    return {"n": n, "status": status, "error": error}


def standing_at(rows, n):
    return next(r["standing"] for r in rows if r["n"] == n)


@pytest.mark.parametrize("status,expected", [
    ("leased", "running"),
    ("queued", "queued"),
    ("failed", "failed"),
    ("cancelled", "cancelled"),
    ("done", "analyzing"),
    ("lost", "lost"),
])
def test_every_job_status_renders_as_itself_not_as_a_gap(status, expected):
    rows = rung_standings(
        ladder=LADDER, measured_ns={64},
        jobs=[job(64, "done"), job(256, status), job(16384, "leased")],
        largest_n=16384)
    assert standing_at(rows, 256) == expected


def test_a_summary_beats_a_finished_job():
    rows = rung_standings(ladder=LADDER, measured_ns={256},
                          jobs=[job(256, "done")], largest_n=4096)
    assert standing_at(rows, 256) == "measured"


def test_live_work_beats_a_previous_terminal_attempt():
    rows = rung_standings(ladder=LADDER, measured_ns=set(),
                          jobs=[job(256, "failed"), job(256, "leased")], largest_n=4096)
    assert standing_at(rows, 256) == "running"


def test_an_operational_cancellation_carries_its_reason():
    rows = rung_standings(
        ladder=LADDER, measured_ns=set(),
        jobs=[job(1024, "cancelled", "cancelled before child execution")],
        largest_n=4096)
    row = next(r for r in rows if r["n"] == 1024)
    assert row["standing"] == "cancelled"
    assert "before child execution" in row["cancelled_reason"]


def test_gap_now_requires_genuinely_no_job_and_no_result():
    rows = rung_standings(ladder=LADDER, measured_ns={64},
                          jobs=[job(64, "done"), job(4096, "leased")], largest_n=4096)
    assert standing_at(rows, 256) == "next"
    assert standing_at(rows, 1024) == "gap"
    assert standing_at(rows, 16384) == "future"


def test_a_fully_scheduled_ladder_has_no_gap_at_all():
    rows = rung_standings(
        ladder=LADDER, measured_ns={64, 256},
        jobs=[job(64, "done"), job(256, "done"), job(1024, "leased"),
              job(4096, "queued"), job(16384, "queued")],
        largest_n=16384)
    assert [r["standing"] for r in rows] == [
        "measured", "measured", "running", "queued", "queued"]


def test_rungs_beyond_the_declared_ladder_are_still_drawn():
    rows = rung_standings(ladder=[64, 256], measured_ns={65536},
                          jobs=[job(65536, "done")], largest_n=65536)
    assert [r["n"] for r in rows] == [64, 256, 65536]
    assert next(r for r in rows if r["n"] == 65536)["declared"] is False


def test_waiting_reason_is_silent_while_work_is_running():
    rows = rung_standings(ladder=LADDER, measured_ns=set(),
                          jobs=[job(1024, "leased")], largest_n=1024)
    assert waiting_reason(rows) is None


def test_waiting_reason_does_not_ask_for_reconciliation_of_a_healthy_lane():
    rows = rung_standings(ladder=LADDER, measured_ns=set(),
                          jobs=[job(256, "done")], largest_n=4096)
    reason = waiting_reason(rows)
    assert "analysis queue" in reason and "no reconciliation" in reason


def test_waiting_reason_still_asks_for_reconciliation_of_a_real_gap():
    rows = rung_standings(ladder=LADDER, measured_ns={64, 4096},
                          jobs=[job(64, "done"), job(4096, "done")], largest_n=4096)
    assert standing_at(rows, 1024) == "gap"
    assert "lifecycle reconciliation" in (waiting_reason(rows) or "")
