from __future__ import annotations

import functools

from graph_scale_dynamics.domain.model import utc_now


def age_seconds(stamp) -> float:
    from datetime import datetime, timezone
    try:
        started = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    now = datetime.fromisoformat(utc_now().replace("Z", "+00:00"))
    return max(0.0, (now - started).total_seconds())


def base_sizes_set(spec: dict, ladder) -> set:
    return {int(n) for n in ((spec.get("base_block") or {}).get("sizes") or ladder or [])}


RESUME_ROOT = None
BUDGET_TEXT = ("a seed's simulation ends between two chunks when the next would not fit its rung's budget in units "
               "of work, with the graphs it has; they are read and the law decided as any other, the seed marked as "
               "ended at its budget; no clock ends a seed")


@functools.lru_cache(maxsize=4)
def _resume_root(blob_root):
    from graph_scale_dynamics.artifact_store.resume_state import resume_root
    return resume_root(blob_root)


def _seconds_between(earlier, later) -> float | None:
    from datetime import datetime, timezone
    try:
        a = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    a, b = (x if x.tzinfo else x.replace(tzinfo=timezone.utc) for x in (a, b))
    return (b - a).total_seconds()


def spent_before(note: dict | None, lease_started) -> float | None:
    if not note:
        return None
    spent = float(note.get("seconds_spent") or 0.0)
    if spent <= 0.0:
        return None
    since = _seconds_between(lease_started, note.get("saved_utc")) if lease_started else None
    if since is not None and since > 0.0:
        spent -= since
    return round(spent, 1) if spent >= 1.0 else None


def resume_note_of(job_id) -> dict | None:
    if RESUME_ROOT is None or not job_id:
        return None
    from graph_scale_dynamics.artifact_store.resume_state import read_resume_note
    return read_resume_note(_resume_root(RESUME_ROOT), str(job_id)) or read_resume_note(RESUME_ROOT, str(job_id))


def resumed_seconds_of(job_id, lease_started) -> float | None:
    return spent_before(resume_note_of(job_id), lease_started)


def lane_and_budget(job: dict, base_set: set) -> dict:
    row = {"lane": "base" if int(job["n"]) in base_set else "extension", "budget_seconds": job_budget_seconds(job),
           "budget_units": job_budget_units(job)}
    if RESUME_ROOT is not None and job.get("job_id"):
        note = resume_note_of(job["job_id"])
        before = spent_before(note, job.get("started_utc") or job.get("updated_utc"))
        if before is not None:
            row["resumed_seconds"] = before
            row["resumed_chunks"] = int(note.get("chunks") or 0)
            row["resumed_saved_utc"] = note.get("saved_utc")
    return row


def probe_rows(rows, base_set: set) -> list[dict]:
    return [{"n": int(a["n"]),
             "seed": None if a.get("seed") is None else int(a["seed"]),
             "lane": "base" if int(a["n"]) in base_set else "extension",
             "started_utc": a.get("updated_utc"),
             "since_s": round(age_seconds(a.get("updated_utc")), 1)}
            for a in (rows or []) if a.get("status") == "leased"]


def job_budget_units(job: dict) -> int | None:
    one_shot = ((job.get("spec") or {}).get("execution") or {}).get("one_shot") or {}
    value = one_shot.get("work_budget")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def job_budget_seconds(job: dict) -> float | None:
    from graph_scale_dynamics.scheduling.rung_eta import job_budget_seconds as estimate
    found = estimate(job)
    return round(found, 1) if found else None


def units_text(units: int) -> str:
    value = float(units)
    for scale, prefix in ((1e15, "P"), (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
        if value >= scale:
            return f"{value / scale:.3g} {prefix}"
    return f"{int(value)}"


def _duration(seconds: float) -> str:
    seconds = float(seconds)
    if seconds >= 2 * 86400 and seconds % 86400 == 0:
        return f"{seconds / 86400:.0f} days"
    if seconds >= 3600:
        hours, minutes = divmod(round(seconds / 60), 60)
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    if seconds >= 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"


def selection_summary(spec: dict) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy, is_engine_campaign
    from graph_scale_dynamics.scheduling.limits import estimated_seconds
    if not is_engine_campaign(spec):
        return {"headline": "no decision engine declared: the campaign is refused", "mechanisms": [],
                "every_rung": [], "stages": [], "exemption": "", "base_sizes": [], "extension_sizes": []}
    policy = Policy.from_spec(spec)
    sizes, deep = [int(n) for n in policy.base_sizes], [int(n) for n in policy.deep_sizes]
    memory = spec.get("resource_limits") or {}
    fraction = memory.get("hard_single_job_fraction_total")
    out: list[dict] = []

    def add(name: str, from_n, does: str, rule: str | None = None) -> None:
        out.append({"name": name, "rule": rule, "from_n": (int(from_n) if from_n is not None else None),
                    "applies_from": (f"N\u2265{int(from_n)}" if from_n is not None else "every rung"),
                    "does": does, "active": True})

    add("budget in work", None, BUDGET_TEXT, "budget")
    add("over budget", sizes[1] if len(sizes) > 1 else None,
        "a law whose first chunk at the next size is predicted, from its own seeds a size below, to cost more than "
        "that size's budget is parked there and not started", "over_budget")
    add("too dense", policy.dense_from_n, f"mean degree at or above {policy.dense_cap:g} stops the law "
        "(not the audit sample)", "too_dense")
    add("empty", policy.empty_from_n, f"mean degree at or below {policy.empty_mean_degree:g} at every rung so far "
        "stops the law (not the audit sample)", "empty")
    add("disconnected", policy.connectivity_from_n, f"a largest component under {policy.connectivity_floor:g} "
        "of the graph stops the law (not the audit sample)", "disconnected")
    add("buy by settling", sizes[-1] if sizes else None,
        "above the base block the next rung goes to laws whose d_s settled at the last step, whatever "
        "their mean degree does; the rest are held until nothing else waits", "d_s_settled")
    if policy.structure_gate:
        add("structure gate", policy.gate_at_n,
            f"a rung above this one goes only to a law whose graphs have a finite dimension on both chains "
            f"(gap exponent at most {policy.gap_exponent_at_most:g}, diameter exponent at least "
            f"{policy.diameter_exponent_at_least:g}); none on either stops it, and a split or undecidable "
            "reading gets one more rung, once", "no_finite_dimension")
        add("fragmented", policy.gate_at_n, f"a giant component under {policy.giant_fraction_at_least:.0%} of the "
            "graph where the structure gate reads it stops the law", "no_giant_component")
    if fraction:
        add("memory boundary", None, f"one process above {float(fraction):.0%} of host memory is stopped and recorded")

    stages: list[dict] = []
    for n in sizes + deep:
        changes: list[str] = []
        if n == policy.dense_from_n:
            changes.append(f"from here a law stops if its mean degree reaches {policy.dense_cap:g}")
        if n == policy.empty_from_n:
            changes.append("from here a law whose graphs have been empty at every rung stops")
        if n == policy.connectivity_from_n:
            changes.append(f"from here a law stops if its largest component holds under "
                           f"{policy.connectivity_floor:g} of the graph")
        if sizes and n == sizes[0]:
            changes.append("every admitted law starts here; only its budget in work can end a seed at this rung")
        if sizes and n == sizes[-1]:
            changes.append("the last base rung: above it the engine buys one rung at a time by settling")
        if policy.structure_gate and n == policy.early_gate_at_n:
            changes.append("the structure gate reads its clear case here and records it; it acts only once "
                           f"its switch is on and {policy.early_gate_agreements} of its refusals agree with the "
                           "full rule")
        if policy.structure_gate and n == policy.gate_at_n:
            changes.append("from here the structure gate: a law with no finite dimension on both chains is not "
                           "given the next rung")
        units = int(policy.work_budget(n)) if policy.work_budgets else None
        seconds = estimated_seconds(spec, n) if units else None
        stages.append({"sizes": [n], "lane": "extension" if n in deep else "base", "title": f"N={n}",
                       "limit_units": units, "limit_seconds": round(seconds, 1) if seconds else None,
                       "limit": (f"{units_text(units)} units" + (f", about {_duration(seconds)}" if seconds else "")
                                 if units else "none"), "changes": changes})
    every_rung = [f"{policy.seeds} seeds, each with its chains from every start"]
    if fraction:
        every_rung.append(f"one process may use up to {float(fraction):.0%} of host memory")
    every_rung.append("a chain that never passes its certificate stops at its sampling ceiling")
    every_rung.append("each seed's simulation has the rung's budget in units of work (right, with the hours it would "
                      "take on the machine the unit was fitted on); a seed whose next chunk would not fit ends, keeps "
                      "its graphs, and they are read and the law decided as any other")
    exemption = (f"{policy.audit_fraction:.0%} of laws are the audit sample: no final-verdict stop applies to them, "
                 "so how often a stop loses a law that would have read can be measured")
    headline = " \u00b7 ".join((f"decision engine \u00b7 {len(sizes)} base rungs, {len(deep)} bought by settling",
                                f"{policy.audit_fraction:.0%} audit sample"))
    return {"headline": headline, "mechanisms": out, "every_rung": every_rung, "stages": stages,
            "exemption": exemption, "base_sizes": sizes, "extension_sizes": deep}
