from __future__ import annotations


def share_waiting(conn, excluding: str) -> bool:
    from graph_scale_dynamics.domain.model import utc_now
    row = conn.execute(
        "SELECT 1 FROM campaigns c WHERE c.status='active' AND c.campaign_id<>? AND c.workers_target > 0 "
        "AND (SELECT COUNT(*) FROM jobs j WHERE j.campaign_id=c.campaign_id AND j.status='leased') < c.workers_target "
        "AND EXISTS (SELECT 1 FROM jobs q WHERE q.campaign_id=c.campaign_id AND q.status='queued' "
        "AND q.kind='simulate' AND COALESCE(q.next_attempt_utc,'')<=?) LIMIT 1", (str(excluding), utc_now())).fetchone()
    return row is not None
