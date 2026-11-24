from __future__ import annotations

from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for

CONTRACT = "fleet-ladder-snapshot-1"
EVENT_TYPE = "fleet_ladder_snapshot"
INTERVAL_SECONDS = 60.0


def _compact(value):
    if isinstance(value, dict):
        kept = {k: _compact(v) for k, v in value.items() if v is not None and v != {}}
        return {k: v for k, v in kept.items() if v is not None and v != {}}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def snapshot_detail(rows: list[dict], candidates_by_state: dict) -> dict:
    return {"contract": CONTRACT, "rows": [_compact(dict(row)) for row in rows],
            "candidates_by_state": {str(k): int(v) for k, v in sorted((candidates_by_state or {}).items())}}


class LadderRecorder:
    def __init__(self, interval_seconds: float = INTERVAL_SECONDS):
        self.interval_seconds = float(interval_seconds)
        self.next_at = 0.0
        self.last_detail: dict | None = None

    def maybe_record(self, repo, campaign_id: str, now_monotonic: float) -> bool:
        if now_monotonic < self.next_at:
            return False
        self.next_at = now_monotonic + self.interval_seconds
        rows = rung_distribution_for(repo, str(campaign_id), repo.rung_attempt_durations(str(campaign_id)))
        detail = snapshot_detail(rows, repo.candidate_state_counts(str(campaign_id)))
        if detail == self.last_detail:
            return False
        repo.record_campaign_event(str(campaign_id), EVENT_TYPE, detail)
        self.last_detail = detail
        return True
