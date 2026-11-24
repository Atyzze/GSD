from __future__ import annotations


def _service_crash_disposition(record: dict, now: float) -> tuple[str, float | None]:
    crashes = [stamp for stamp in record.get("crashes", []) if now - stamp < 60.0]
    crashes.append(now)
    record["crashes"] = crashes
    if len(crashes) > 5:
        return ("fatal", None) if record.get("critical", True) else ("backoff", 60.0)
    return "restart", min(5.0, 0.25 * (2 ** (len(crashes) - 1)))


def _launched(launch, record: dict, now: float) -> bool:
    try:
        launch(record)
        return True
    except OSError as exc:
        print(f"service {record['module']} could not start: {type(exc).__name__}: {exc}", flush=True)
        record["proc"] = None
        disposition, delay = _service_crash_disposition(record, now)
        if disposition == "fatal":
            raise RuntimeError(f"{record['module']} could not start, in a crash loop") from exc
        record["retry_at"] = now + (60.0 if disposition == "backoff" else float(delay or 1.0))
        return False


def _back_off(repo, services: list[dict], record: dict, until: float | None) -> None:
    record["retry_at"] = until
    if until is not None:
        print(f"side service {record['module']} in a crash loop ({len(record['crashes'])} exits/minute): "
              "started again in a minute; the research fleet continues", flush=True)
    try:
        _sync_crash_alerts(repo, services)
    except Exception as exc:
        print(f"crash-loop alert not written: {type(exc).__name__}: {exc}", flush=True)


def _sync_crash_alerts(repo, services: list[dict]) -> None:
    repo.sync_operational_alerts("supervisor", [{
        "key": f"crash_loop:{r['module']}", "severity": "error", "category": "service",
        "message": f"{r['module']} is in a crash loop: started again every minute; the research fleet continues",
        "detail": {"exits_last_minute": len(r["crashes"])}} for r in services if r.get("retry_at") is not None])
