from __future__ import annotations

from typing import Iterable, Mapping

CYCLE_CONTRACT = "gsd-report-cycle-1"

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
FAILED = "FAILED"

CYCLE_STATES = (COMPLETE, PARTIAL, FAILED)

MAX_RESOLVED_ERRORS = 20

_CYCLE_STATE_BY_GENERATION_STATUS = {
    "complete": COMPLETE,
    "complete_with_errors": PARTIAL,
    "error": FAILED,
}


def classify_cycle(*, snapshot_ok: bool, failed_reports: Iterable[str],
                   published: bool = True) -> str:
    if not snapshot_ok or not published:
        return FAILED
    return PARTIAL if list(failed_reports) else COMPLETE


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if text in CYCLE_STATES:
        return text
    return _CYCLE_STATE_BY_GENERATION_STATUS.get(text.lower())


def resolve_errors(manifest: Mapping, *, cycle_id: str | None,
                   resolved_utc: str, keep: int = MAX_RESOLVED_ERRORS) -> dict:
    updated = dict(manifest)
    history = list(updated.get("resolved_errors") or [])
    current = updated.get("service_error")
    if current:
        history.append({
            "error": str(current),
            "failed_cycle_id": updated.get("failed_cycle_id") or updated.get("cycle_id"),
            "failed_utc": updated.get("service_error_utc") or updated.get("generation_finished_utc"),
            "resolved_by_cycle_id": cycle_id,
            "resolved_utc": resolved_utc,
        })
    updated["service_error"] = None
    updated["service_error_utc"] = None
    updated["failed_cycle_id"] = None
    updated["resolved_errors"] = history[-int(max(0, keep)):]
    updated["resolved_error_count"] = len(updated["resolved_errors"])
    return updated


def record_current_error(manifest: Mapping, *, error: str, cycle_id: str | None,
                         failed_utc: str) -> dict:
    updated = dict(manifest)
    updated["service_error"] = str(error)
    updated["service_error_utc"] = failed_utc
    updated["failed_cycle_id"] = cycle_id
    updated.setdefault("resolved_errors", [])
    updated["resolved_error_count"] = len(updated.get("resolved_errors") or [])
    return updated


def apply_cycle_outcome(manifest: Mapping, *, state: str, cycle_id: str | None,
                        revision: str | None, finished_utc: str,
                        failed_reports: Mapping | None = None,
                        error: str = "", seconds: float | None = None) -> dict:
    state = str(state)
    if state not in CYCLE_STATES:
        raise ValueError(f"unknown report cycle state: {state}")
    updated = dict(manifest)
    failed = dict(failed_reports or {})
    updated["cycle_contract"] = CYCLE_CONTRACT
    updated["cycle_state"] = state
    updated["cycle_id"] = cycle_id
    updated["generation_status"] = state
    updated["generation_finished_utc"] = finished_utc
    updated["failed_reports"] = sorted(failed)
    updated["failed_report_errors"] = {str(k): str(v) for k, v in failed.items()}
    if seconds is not None:
        updated["cycle_seconds"] = round(float(seconds), 3)

    if state == COMPLETE:
        updated["bundle_revision"] = revision
        updated["bundle_cycle_id"] = cycle_id
        updated["bundle_complete"] = True
        updated["bundle_downloadable"] = True
        updated["bundle_generated_utc"] = finished_utc
        updated["bundle_stale"] = False
        updated = resolve_errors(updated, cycle_id=cycle_id, resolved_utc=finished_utc)
        updated["headline"] = f"COMPLETE · revision {revision or 'unknown'}"
        return updated

    updated["bundle_complete"] = False
    updated["bundle_downloadable"] = bool(updated.get("bundle_revision"))
    updated["bundle_stale"] = bool(updated.get("bundle_generated_utc"))
    if state == PARTIAL:
        message = error or ("individual reports failed: " + ", ".join(sorted(failed)))
        updated = record_current_error(updated, error=message, cycle_id=cycle_id,
                                       failed_utc=finished_utc)
        updated["partial_source_revision"] = revision
        updated["headline"] = f"PARTIAL · {len(failed)} report(s) failed"
        return updated

    updated = record_current_error(updated, error=error or "report cycle failed",
                                   cycle_id=cycle_id, failed_utc=finished_utc)
    updated["headline"] = "FAILED · no new bundle revision published"
    return updated
