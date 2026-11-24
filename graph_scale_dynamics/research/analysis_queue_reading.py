from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime

from graph_scale_dynamics.domain.model import utc_now

CEILING = re.compile(r"RSS (\d+) bytes >= (\d+) bytes")
GIB = 1024 ** 3


def _parse_utc(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _later(wake, now) -> bool:
    a, b = _parse_utc(wake), _parse_utc(now)
    return bool(a and b and a > b)


def failed_by_class(rows: list[dict]) -> dict:
    done = {(str(r.get("candidate_id")), r.get("n"), r.get("seed")) for r in rows if r.get("status") == "done"}
    out: dict = defaultdict(lambda: {"standing": 0, "superseded": 0})
    for row in rows:
        if row.get("status") != "failed":
            continue
        key = (str(row.get("candidate_id")), row.get("n"), row.get("seed"))
        known = row.get("seed") is not None
        out[str(row.get("error_class") or "unknown")]["superseded" if known and key in done else "standing"] += 1
    return {cls: dict(v) for cls, v in sorted(out.items())}


def _gib(value) -> float | None:
    return round(int(value) / GIB, 2) if value else None


def standing_failures(work: list[dict], attempts: list[dict]) -> list[dict]:
    done = {(str(r.get("candidate_id")), r.get("n"), r.get("seed")) for r in work if r.get("status") == "done"}
    tries: dict = defaultdict(list)
    for attempt in attempts:
        tries[(str(attempt.get("candidate_id")), attempt.get("n"), attempt.get("seed"))].append(attempt)
    out = []
    for row in work:
        key = (str(row.get("candidate_id")), row.get("n"), row.get("seed"))
        if row.get("status") != "failed" or (row.get("seed") is not None and key in done):
            continue
        each = []
        for attempt in sorted(tries.get(key, []), key=lambda a: str(a.get("started_utc") or "")):
            ceiling = CEILING.search(str(attempt.get("error") or ""))
            each.append({"started_utc": attempt.get("started_utc"),
                         "class": attempt.get("error_class"),
                         "wall_seconds": round(float(attempt.get("wall_seconds") or 0.0), 1),
                         "peak_rss_gib": _gib(attempt.get("peak_rss_bytes")),
                         "reserved_gib": _gib(attempt.get("memory_reservation_bytes")),
                         "ceiling_gib": _gib(ceiling.group(2)) if ceiling else None})
        out.append({"law": str(row.get("candidate_id") or "")[:12], "n": row.get("n"), "seed": row.get("seed"),
                    "class": str(row.get("error_class") or "unknown"), "attempts": row.get("attempts"),
                    "error": str(row.get("error") or "")[:200] or None, "failed_utc": row.get("updated_utc"),
                    "tries": each})
    return sorted(out, key=lambda f: (str(f["law"]), int(f["n"] or 0), str(f["seed"])))


def analysis_queue_snapshot(snapshot: dict) -> dict:
    now = snapshot.get("collected_utc") or utc_now()
    raw, rebuild = Counter(), Counter()
    raw_claimable = raw_deferred = rebuild_claimable = rebuild_deferred = 0
    work = snapshot.get("analysis_work", [])
    for row in work:
        status = str(row.get("status") or "unknown")
        raw[status] += 1
        if status == "queued":
            if _later(row.get("next_attempt_utc"), now):
                raw_deferred += 1
            else:
                raw_claimable += 1
    for row in snapshot.get("evidence_rebuilds", []):
        status = str(row.get("status") or "unknown")
        rebuild[status] += 1
        if status == "queued":
            if _later(row.get("next_attempt_utc"), now):
                rebuild_deferred += 1
            else:
                rebuild_claimable += 1
    return {
        "raw_counts": dict(raw),
        "failed_by_class": failed_by_class(work),
        "standing_failures": standing_failures(work, snapshot.get("analysis_attempts") or []),
        "evidence_rebuild_counts": dict(rebuild),
        "raw_claimable_now": raw_claimable,
        "raw_deferred": raw_deferred,
        "rebuild_claimable_now": rebuild_claimable,
        "rebuild_deferred": rebuild_deferred,
        "analysis_claimable_now": raw_claimable + rebuild_claimable,
        "analysis_deferred": raw_deferred + rebuild_deferred,
        "analysis_leased": int(raw.get("leased", 0) + rebuild.get("leased", 0)),
        "interpretation": (
            "queued rows with next_attempt_utc in the future are durable but not runnable; scheduler backlog must "
            "be compared with claimable_now rather than the raw queued count. raw_counts counts superseded rows "
            "too; failed_by_class says which failures still stand (they stop a law) and which a later analysis of "
            "the same seed replaced"
        ),
    }
