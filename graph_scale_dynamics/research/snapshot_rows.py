from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import utc_now

BATCH = 1000

UNREAD_METRICS_SECTIONS = ("move_accounting", "chains_course")
DESCENT_READ = "final_energy"
JOB_SPEC_READ = {"execution": {"sweeps_multiplier": None, "one_shot": ("work_budget",)},
                 "candidate_spec": {"dynamics": ("sweeps",)}, "dynamics": ("sweeps",)}


RUNG_ROWS_SQL = ("SELECT candidate_id,n,summary_json,created_utc FROM rung_summaries "
                 "WHERE campaign_id=? AND analysis_version=? ORDER BY candidate_id,n")
JOB_ROWS_SQL = "SELECT * FROM jobs WHERE campaign_id=? ORDER BY created_utc,job_id"
DECISION_ROWS_SQL = ("SELECT candidate_id,decision_id,at_n,next_n,action,rule,reason,priority,queue_order,jobs_created,"
                     "rows_changed,released_hold,engine,facts_json,created_utc FROM engine_decisions "
                     "WHERE campaign_id=? ORDER BY candidate_id,decision_id")


def _descent_read(descent):
    chains = (descent or {}).get("chains") if isinstance(descent, dict) else None
    if not isinstance(chains, dict):
        return None
    return {"chains": {name: {DESCENT_READ: chain.get(DESCENT_READ)} for name, chain in chains.items()
                       if isinstance(chain, dict) and DESCENT_READ in chain}}


def metrics_read(metrics):
    if isinstance(metrics, dict):
        for name in UNREAD_METRICS_SECTIONS:
            metrics.pop(name, None)
        if "descent" in metrics:
            kept = _descent_read(metrics.pop("descent"))
            if kept:
                metrics["descent"] = kept
    return metrics


def job_spec_read(spec):
    return _kept(spec, JOB_SPEC_READ)


def _kept(value, shape):
    if not isinstance(value, dict):
        return value
    names = shape.items() if isinstance(shape, dict) else ((name, None) for name in shape)
    return {name: value[name] if inner is None else _kept(value[name], inner) for name, inner in names if name in value}


def parsed_rows(conn, sql: str, args, column: str, key: str, *, batch: int = BATCH, default: str | None = None,
                keep=None) -> list[dict]:
    stream = getattr(conn, "stream", None)
    rows_of = stream(sql, args, size=batch) if callable(stream) else _fetched(conn.execute(sql, args), batch)
    out, chunk = [], []
    for row in rows_of:
        chunk.append(row)
        if len(chunk) >= batch:
            out.extend(_parsed(chunk, column, key, default, keep))
            chunk = []
    if chunk:
        out.extend(_parsed(chunk, column, key, default, keep))
    return out


def grouped_rows(rows: list[dict], by: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.pop(by)), []).append(row)
    return grouped


def _fetched(cursor, batch: int):
    while rows := cursor.fetchmany(batch):
        yield from rows


def _parsed(chunk: list, column: str, key: str, default: str | None = None, keep=None) -> list[dict]:
    texts = [row[column] for row in chunk] if default is None else [row[column] or default for row in chunk]
    try:
        values = json.loads("[" + ",".join(texts) + "]")
    except (TypeError, ValueError):
        values = None
    if not isinstance(values, list) or len(values) != len(chunk):
        values = [json.loads(text) for text in texts]
    out = []
    for row, value in zip(chunk, values, strict=True):
        item = dict(row)
        del item[column]
        item[key] = value if keep is None else keep(value)
        out.append(item)
    return out


def snapshot_progress(progress, *, stage: str, current: int, total: int, detail: str = "", campaign_id: str | None = None) -> None:
    if progress is None:
        return
    try:
        progress({
            "stage": str(stage), "current": int(current), "total": int(total),
            "fraction": max(0.0, min(1.0, float(current) / max(1, int(total)))),
            "detail": str(detail or ""), "campaign_id": None if campaign_id is None else str(campaign_id),
            "updated_utc": utc_now(),
        })
    except Exception:
        return
