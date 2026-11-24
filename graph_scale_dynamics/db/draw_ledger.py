from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import utc_now

ROWS_PER_STATEMENT = 400


def _law_json(draw: dict) -> str:
    return json.dumps(draw.get("law"), sort_keys=True)


def insert_proposal_draws(repo, campaign_id: str, stream_index: int, draws: list[dict]) -> int:
    if not draws:
        return 0
    now = utc_now()
    rows = [(campaign_id, int(stream_index), int(d["draw_index"]), str(d["outcome"]), d.get("candidate_id"),
             _law_json(d), now) for d in draws]
    for start in range(0, len(rows), ROWS_PER_STATEMENT):
        chunk = rows[start:start + ROWS_PER_STATEMENT]
        repo._write(
            "INSERT INTO proposal_draws(campaign_id,stream_index,draw_index,outcome,candidate_id,law_json,"
            "created_utc) VALUES " + ",".join(["(?,?,?,?,?,?,?)"] * len(chunk)) + " ON CONFLICT DO NOTHING",
            tuple(value for row in chunk for value in row))
    return len(rows)


def _row(row) -> dict:
    return dict(row) | {"law": json.loads(row["law_json"])}


def proposal_draws(repo, campaign_id: str) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT * FROM proposal_draws WHERE campaign_id=? ORDER BY stream_index,draw_index", (campaign_id,),
    ).fetchall()
    return [_row(row) for row in rows]
