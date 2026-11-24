from __future__ import annotations

from graph_scale_dynamics.observability import ladder_history as H


class _Repo:
    def __init__(self, rows):
        self.rows, self.events = rows, []

    def rung_attempt_durations(self, campaign_id):
        return {}

    def candidate_state_counts(self, campaign_id):
        return {"BASE_BLOCK_RUNNING": 2, "STOPPED": 1}

    def record_campaign_event(self, campaign_id, event_type, detail):
        self.events.append((campaign_id, event_type, detail))


def test_a_snapshot_is_written_once_per_interval_and_never_twice_unchanged(monkeypatch):
    rows = [{"n": 64, "laws": 3, "p05_seconds": None, "stopped_by_rule": {}, "interrupted": 1}]
    monkeypatch.setattr(H, "rung_distribution_for", lambda repo, cid, samples: [dict(r) for r in repo.rows])
    repo, recorder = _Repo(rows), H.LadderRecorder(interval_seconds=60)
    assert recorder.maybe_record(repo, "1", now_monotonic=0.0)
    campaign, kind, detail = repo.events[0]
    assert (campaign, kind, detail["contract"]) == ("1", "fleet_ladder_snapshot", "fleet-ladder-snapshot-1")
    assert detail["rows"] == [{"n": 64, "laws": 3, "interrupted": 1}], "empty fields are not stored"
    assert detail["candidates_by_state"] == {"BASE_BLOCK_RUNNING": 2, "STOPPED": 1}
    assert not recorder.maybe_record(repo, "1", now_monotonic=30.0), "inside the interval"
    assert not recorder.maybe_record(repo, "1", now_monotonic=61.0), "a paused fleet writes no copies"
    repo.rows[0]["laws"] = 4
    assert recorder.maybe_record(repo, "1", now_monotonic=122.0)
    assert len(repo.events) == 2
