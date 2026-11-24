from __future__ import annotations

import hashlib
import json
import time

FLAG_PREFIX = "kappa_seconds:"
KAPPA_SECONDS_CONTRACT = "gsd-kappa-seconds-1"
SCAN_LIMIT = 2000
SCAN_INTERVAL_SECONDS = 30.0
SAMPLE_SIZE = 201
_LAST_SCAN: dict[str, float] = {}


def _key(campaign_id: str) -> str:
    return FLAG_PREFIX + str(campaign_id)


def _load(repo, campaign_id: str) -> dict:
    try:
        state = json.loads(repo.get_flag(_key(campaign_id), "") or "{}")
    except (TypeError, ValueError):
        state = {}
    if state.get("contract") != KAPPA_SECONDS_CONTRACT:
        state = {"contract": KAPPA_SECONDS_CONTRACT, "cursor": ["", ""], "rungs": {}}
    return state


def _slot(campaign_id: str, n: int, count: int) -> int:
    digest = hashlib.sha256(f"{campaign_id}:{n}:{count}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % count


def add(state: dict, campaign_id: str, n: int, seconds: float) -> None:
    rung = state["rungs"].setdefault(str(int(n)), {"count": 0, "sum": 0.0, "sample": []})
    rung["count"] += 1
    rung["sum"] = round(rung["sum"] + float(seconds), 6)
    if len(rung["sample"]) < SAMPLE_SIZE:
        rung["sample"].append(round(float(seconds), 6))
    else:
        j = _slot(campaign_id, int(n), rung["count"])
        if j < SAMPLE_SIZE:
            rung["sample"][j] = round(float(seconds), 6)


def scan(repo, campaign_id: str, *, now: float | None = None, limit: int = SCAN_LIMIT) -> int:
    clock = time.monotonic() if now is None else float(now)
    if clock - _LAST_SCAN.get(str(campaign_id), -1e18) < SCAN_INTERVAL_SECONDS:
        return 0
    _LAST_SCAN[str(campaign_id)] = clock
    state = _load(repo, campaign_id)
    after_utc, after_id = state["cursor"]
    rows = repo.conn.execute(
        "SELECT m.analysis_id, m.created_utc, m.n, (m.metrics_json::jsonb #>> '{probe_seconds,kappa}') AS kappa "
        "FROM (SELECT analysis_id FROM measurements WHERE campaign_id=? AND (created_utc, analysis_id) > (?, ?) "
        "ORDER BY created_utc, analysis_id LIMIT ?) AS page "
        "JOIN measurements m ON m.campaign_id=? AND m.analysis_id=page.analysis_id "
        "ORDER BY m.created_utc, m.analysis_id",
        (str(campaign_id), str(after_utc), str(after_id), int(limit), str(campaign_id))).fetchall()
    counted = 0
    for row in rows:
        state["cursor"] = [str(row["created_utc"]), str(row["analysis_id"])]
        try:
            seconds = float(row["kappa"]) if row["kappa"] is not None else None
        except (TypeError, ValueError):
            seconds = None
        if seconds is None:
            continue
        add(state, str(campaign_id), int(row["n"]), seconds)
        counted += 1
    if rows:
        repo.set_flag(_key(campaign_id), json.dumps(state, separators=(",", ":")))
    return counted


def ladder_cells(repo, campaign_id: str) -> dict[int, dict]:
    state = _load(repo, campaign_id)
    out = {}
    for n, rung in state["rungs"].items():
        sample = sorted(rung.get("sample") or [])
        median = (sample[len(sample) // 2] if len(sample) % 2 else
                  (sample[len(sample) // 2 - 1] + sample[len(sample) // 2]) / 2) if sample else None
        tail = (lambda q: round(sample[min(len(sample) - 1, int(q * len(sample)))], 3) if sample else None)
        out[int(n)] = {"kappa_median_seconds": None if median is None else round(median, 3),
                       "kappa_p05_seconds": tail(0.05), "kappa_p95_seconds": tail(0.95),
                       "kappa_seconds_total": round(float(rung.get("sum") or 0.0), 1),
                       "kappa_timed_measurements": int(rung.get("count") or 0)}
    return out
