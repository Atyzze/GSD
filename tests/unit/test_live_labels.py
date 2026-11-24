from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.readmodel.rung_standing import (
    rung_standings, waiting_reason,
)

ROOT = Path(__file__).resolve().parents[2]
LADDER = [64, 256, 1024, 4096, 16384]


def job(n, status, error=None, updated=None):
    return {"n": n, "status": status, "error": error, "updated_utc": updated}


def test_an_unfiltered_law_with_every_rung_measured_awaits_its_decision():
    rows = rung_standings(ladder=LADDER, measured_ns=set(LADDER),
                          jobs=[job(n, "done") for n in LADDER], largest_n=16384)
    assert waiting_reason(rows) is None, "the ladder itself has nothing left to say"


def test_the_analysing_rung_carries_how_long_it_has_waited():
    rows = rung_standings(ladder=LADDER, measured_ns=set(),
                          jobs=[job(256, "done", updated="2026-09-04T13:00:00Z")],
                          largest_n=1024)
    row = next(r for r in rows if r["n"] == 256)
    assert row["standing"] == "analyzing"
    assert row["since_utc"] == "2026-09-04T13:00:00Z"


def test_the_bounded_query_supplies_the_timestamp_the_clock_needs():
    from graph_scale_dynamics.db.repo import Repo

    captured = {}

    class _Conn:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
            class _Cursor:
                @staticmethod
                def fetchall():
                    return [{"candidate_id": "a", "n": 256, "status": "done",
                             "error": None, "updated_utc": "2026-09-04T13:00:00Z"}]
            return _Cursor()

    repo = Repo.__new__(Repo)
    repo.conn = _Conn()
    out = Repo.dashboard_rung_job_states(repo, "1", ["a"])

    assert out["a"][0]["updated_utc"] == "2026-09-04T13:00:00Z", \
        "the clock needs a timestamp and this is where it comes from"
    assert out["a"][0]["status"] == "done"
    assert "status IN" not in captured["sql"], "the ladder needs terminal rows"
    assert "candidate_id IN" in captured["sql"], "bounded to the visible candidates"
    assert "spec_json" not in captured["sql"], "no historical specs decoded"


def test_an_empty_candidate_list_does_not_query_at_all():
    from graph_scale_dynamics.db.repo import Repo

    class _Conn:
        def execute(self, *a, **k):
            raise AssertionError("should not have queried")

    repo = Repo.__new__(Repo)
    repo.conn = _Conn()
    assert Repo.dashboard_rung_job_states(repo, "1", []) == {}
