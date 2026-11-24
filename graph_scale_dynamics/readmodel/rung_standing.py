from __future__ import annotations

JOB_STATUSES: tuple[str, ...] = ("queued", "leased", "done", "failed", "cancelled", "lost")


def rung_standings(*, ladder, measured_ns, jobs, largest_n=None):
    ladder = [int(n) for n in (ladder or [])]
    measured = {int(n) for n in (measured_ns or [])}
    rows = list(jobs or [])

    by_status: dict[str, set[int]] = {status: set() for status in JOB_STATUSES}
    cancel_reason: dict[int, str] = {}
    failure_reason: dict[int, str] = {}
    job_ns: set[int] = set()
    since: dict[int, str] = {}

    for job in rows:
        try:
            n = int(job["n"])
        except (KeyError, TypeError, ValueError):
            continue
        job_ns.add(n)
        status = str(job.get("status") or "")
        error = str(job.get("error") or "")
        if status in by_status:
            by_status[status].add(n)
        if status == "done" and job.get("updated_utc"):
            since.setdefault(n, str(job["updated_utc"]))
        if status == "cancelled":
            cancel_reason.setdefault(n, error[:240] or "cancelled")
        elif status == "failed":
            failure_reason.setdefault(n, error[:240] or "failed")

    known = measured | job_ns
    drawn = sorted(set(ladder) | known)
    top = int(largest_n) if largest_n else (max(known) if known else 0)
    pending = [n for n in ladder if n not in known]
    next_n = pending[0] if pending else None

    out = []
    for n in drawn:
        row = {"n": n, "declared": n in ladder}
        if n in by_status["leased"]:
            row["standing"] = "running"
        elif n in by_status["queued"]:
            row["standing"] = "queued"
        elif n in measured:
            row["standing"] = "measured"
        elif n in by_status["failed"]:
            row["standing"] = "failed"
            row["failure"] = failure_reason.get(n)
        elif n in by_status["cancelled"]:
            row["standing"] = "cancelled"
            row["cancelled_reason"] = cancel_reason.get(n)
        elif n in by_status["done"]:
            row["standing"] = "analyzing"
            if since.get(n) is not None:
                row["since_utc"] = since[n]
        elif n in by_status["lost"]:
            row["standing"] = "lost"
        elif next_n is not None and n == next_n:
            row["standing"] = "next"
        elif n < top:
            row["standing"] = "gap"
        else:
            row["standing"] = "future"
        out.append(row)
    return out


def waiting_reason(standings) -> str | None:
    by_standing: dict[str, list[int]] = {}
    for row in standings or []:
        by_standing.setdefault(row["standing"], []).append(int(row["n"]))
    detail = {row["n"]: row for row in standings or []}

    if by_standing.get("running"):
        return None
    if by_standing.get("queued"):
        return "work is admitted and waiting for an executor slot"
    for standing, template in (
        ("failed", "N={n} failed and is recorded as a verdict: {why}"),
        ("lost", "N={n} was lost by its worker and has no result; it needs requeueing"),
        ("analyzing", "N={n} finished simulating and is waiting on the analysis queue; "
                      "no reconciliation is needed"),
        ("cancelled", "N={n} had its jobs cancelled and produced no result: {why}"),
    ):
        found = by_standing.get(standing)
        if found:
            n = min(found)
            row = detail.get(n, {})
            why = row.get("failure") or row.get("cancelled_reason") or "see attempts.error_class"
            return template.format(n=n, why=why)
    if by_standing.get("gap"):
        n = min(by_standing["gap"])
        return (f"N={n} has no result and no job while larger rungs are measured; "
                "the ladder has a gap and needs lifecycle reconciliation")
    return None
