from __future__ import annotations

CYCLE_RECORD_CONTRACT = "gsd-report-cycle-record-1"

_DIRECT_FIELDS: tuple[tuple[str, str], ...] = (
    ("started_utc", "started_utc"),
    ("finished_utc", "finished_utc"),
    ("total_seconds", "total_seconds"),
    ("snapshot_seconds", "snapshot_seconds"),
    ("snapshot_decompressed_bytes", "snapshot_decompressed_bytes"),
    ("api_bytes_transferred", "api_bytes_transferred"),
    ("trigger_source", "trigger_source"),
)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def cycle_row(manifest: dict) -> dict | None:
    if not isinstance(manifest, dict):
        return None
    cycle = manifest.get("cycle")
    if not isinstance(cycle, dict):
        return None

    cycle_id = manifest.get("cycle_id") or cycle.get("cycle_id")
    started = cycle.get("started_utc")
    if not started and cycle.get("finished_utc") and cycle.get("total_seconds"):
        try:
            from datetime import datetime, timedelta, timezone
            finished = datetime.strptime(str(cycle["finished_utc"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            started = (finished - timedelta(seconds=float(cycle["total_seconds"]))).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            started = None
    if not cycle_id or not started:
        return None

    row: dict = {
        "cycle_id": str(cycle_id),
        "campaign_id": str(manifest.get("campaign_id") or ""),
        "build_number": None,
        "report_seconds": {},
        "cycle_state": manifest.get("cycle_state") or cycle.get("cycle_state"),
    }
    for source, column in _DIRECT_FIELDS:
        row[column] = cycle.get(source)
    if not row.get("started_utc"):
        row["started_utc"] = started

    for column in ("total_seconds", "snapshot_seconds"):
        row[column] = _number(row.get(column))
    for column in ("snapshot_decompressed_bytes", "api_bytes_transferred"):
        value = _number(row.get(column))
        row[column] = int(value) if value is not None else None

    build = _number(manifest.get("build_number"))
    row["build_number"] = int(build) if build is not None else None

    timings = cycle.get("report_seconds")
    if isinstance(timings, dict):
        row["report_seconds"] = {
            str(name): _number(seconds)
            for name, seconds in timings.items()
            if _number(seconds) is not None
        }
    return row


