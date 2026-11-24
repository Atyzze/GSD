from __future__ import annotations

import datetime as dt

from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, utc_now


def _cutoff(seconds: float) -> str:
    value = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _age(value: str | None) -> float | None:
    if not value:
        return None
    try:
        then = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return max(0.0, (dt.datetime.now(dt.timezone.utc) - then).total_seconds())
    except ValueError:
        return None


def liveness_findings(conn, *, queue_age_seconds: int = 600,
                      heartbeat_age_seconds: int = 90,
                      scheduler_age_seconds: int = 30) -> list[dict]:
    findings: list[dict] = []
    active = int(conn.execute(
        "SELECT COUNT(*) c FROM campaigns WHERE status='active'"
    ).fetchone()["c"])
    paused_row = conn.execute("SELECT value FROM control WHERE key='paused'").fetchone()
    paused = bool(paused_row and paused_row["value"] == "1")
    terminal = tuple(sorted(TERMINAL_CANDIDATE_STATES))
    marks = ",".join("?" for _ in terminal)

    queued_sim = int(conn.execute(
        "SELECT COUNT(*) c FROM jobs j JOIN campaigns c ON c.campaign_id=j.campaign_id "
        "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
        "AND cc.candidate_id=j.candidate_id WHERE j.kind='simulate' AND j.status='queued' "
        f"AND c.status='active' AND c.workers_target IS DISTINCT FROM 0 "
        f"AND cc.state NOT IN ({marks})", terminal,
    ).fetchone()["c"])
    now_utc = utc_now()
    queued_analysis = int(conn.execute(
        "SELECT COUNT(*) c FROM analysis_queue q JOIN campaigns c ON c.campaign_id=q.campaign_id "
        "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id "
        "AND cc.candidate_id=q.candidate_id WHERE q.status='queued' AND c.status='active' "
        "AND (q.next_attempt_utc IS NULL OR q.next_attempt_utc<=?) "
        f"AND cc.state NOT IN ({marks})", (now_utc, *terminal),
    ).fetchone()["c"])
    recent_executors = int(conn.execute(
        "SELECT COUNT(*) c FROM service_heartbeats WHERE service LIKE ? "
        "AND sampled_utc>=?", ("executor-%", _cutoff(heartbeat_age_seconds)),
    ).fetchone()["c"])
    if active and not paused and (queued_sim or queued_analysis) and recent_executors == 0:
        findings.append({
            "key": "liveness:no-recent-executors", "severity": "error",
            "category": "executor_liveness",
            "message": "active queued work has no recent executor heartbeat",
            "detail": {"queued_simulations": queued_sim, "queued_analysis": queued_analysis,
                       "heartbeat_age_seconds": heartbeat_age_seconds},
        })

    scheduler = None
    scheduler_age = None
    if active:
        scheduler = conn.execute(
            "SELECT updated_utc,total_slots,simulation_slots,analysis_slots,queued_simulations,"
            "leased_simulations FROM scheduler_state WHERE singleton=TRUE"
        ).fetchone()
        scheduler_age = _age(scheduler["updated_utc"]) if scheduler else None
        if scheduler is None or scheduler_age is None or scheduler_age > scheduler_age_seconds:
            findings.append({
                "key": "liveness:stale-scheduler", "severity": "error",
                "category": "scheduler_liveness",
                "message": "scheduler allocation is absent or stale while campaigns are active",
                "detail": {"age_seconds": scheduler_age,
                           "limit_seconds": scheduler_age_seconds},
            })

    if not paused:
        oldest_sim = conn.execute(
            "SELECT MIN(j.created_utc) oldest FROM jobs j "
            "JOIN campaigns c ON c.campaign_id=j.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=j.campaign_id "
            "AND cc.candidate_id=j.candidate_id "
            "WHERE j.kind='simulate' AND j.status='queued' AND c.status='active' "
            "AND c.workers_target IS DISTINCT FROM 0 "
            "AND (c.workers_target IS NULL OR (SELECT COUNT(*) FROM jobs leased "
            "WHERE leased.campaign_id=j.campaign_id AND leased.kind='simulate' "
            "AND leased.status='leased') < c.workers_target) "
            f"AND cc.state NOT IN ({marks})", terminal,
        ).fetchone()["oldest"]
        oldest_analysis = conn.execute(
            "SELECT MIN(COALESCE(q.next_attempt_utc,q.created_utc)) oldest "
            "FROM analysis_queue q JOIN campaigns c ON c.campaign_id=q.campaign_id "
            "JOIN campaign_candidates cc ON cc.campaign_id=q.campaign_id "
            "AND cc.candidate_id=q.candidate_id WHERE q.status='queued' "
            "AND c.status='active' AND (q.next_attempt_utc IS NULL OR q.next_attempt_utc<=?) "
            f"AND cc.state NOT IN ({marks})", (now_utc, *terminal),
        ).fetchone()["oldest"]
        analysis_busy = int(conn.execute(
            "SELECT (SELECT COUNT(*) FROM analysis_queue WHERE status='leased') + "
            "(SELECT COUNT(*) FROM candidate_evidence_rebuilds WHERE status='leased') c"
        ).fetchone()["c"])
        scheduler_fresh = bool(
            scheduler and scheduler_age is not None and scheduler_age <= scheduler_age_seconds
        )
        unused_compute_slots = 0
        if scheduler_fresh:
            unused_compute_slots = max(
                0,
                int(scheduler["total_slots"])
                - int(scheduler["leased_simulations"])
                - analysis_busy,
            )
        claimable_sim = int(scheduler["queued_simulations"]) if scheduler_fresh else 0
        for kind, count, oldest in (
            ("simulation", claimable_sim, oldest_sim),
            ("analysis", queued_analysis, oldest_analysis),
        ):
            age = _age(oldest)
            if count and unused_compute_slots and age is not None and age > queue_age_seconds:
                findings.append({
                    "key": f"liveness:old-{kind}-queue", "severity": "warning",
                    "category": "queue_starvation",
                    "message": f"claimable {kind} work remains queued while compute slots are unused",
                    "detail": {
                        "count": count,
                        "oldest_queue_item_utc": oldest,
                        "oldest_queue_item_age_seconds": round(age, 1),
                        "threshold_seconds": queue_age_seconds,
                        "unused_compute_slots": unused_compute_slots,
                    },
                })

        if scheduler_fresh and int(scheduler["total_slots"] or 0) > 0:
            total_slots = int(scheduler["total_slots"] or 0)
            material_idle = unused_compute_slots >= max(2, int(total_slots * 0.25))
            if material_idle and claimable_sim == 0 and queued_analysis == 0:
                old_cutoff = _cutoff(queue_age_seconds)
                from graph_scale_dynamics.db.decision_store import held_sql
                stranded_rows = conn.execute(
                    "SELECT cc.state,COUNT(*) c FROM campaign_candidates cc "
                    "JOIN campaigns cm ON cm.campaign_id=cc.campaign_id "
                    "WHERE cm.status='active' "
                    f"AND cc.state NOT IN ({marks}) AND cc.state NOT IN ('PROPOSED','VALIDATING') "
                    f"AND NOT {held_sql('cc')} "
                    "AND cc.updated_utc<=? "
                    "AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.campaign_id=cc.campaign_id "
                    "AND j.candidate_id=cc.candidate_id AND j.status IN ('queued','leased')) "
                    "AND NOT EXISTS(SELECT 1 FROM analysis_queue q WHERE q.campaign_id=cc.campaign_id "
                    "AND q.candidate_id=cc.candidate_id AND q.status IN ('queued','leased')) "
                    "AND NOT EXISTS(SELECT 1 FROM candidate_evidence_rebuilds r "
                    "WHERE r.campaign_id=cc.campaign_id AND r.candidate_id=cc.candidate_id "
                    "AND r.status IN ('queued','leased')) GROUP BY cc.state ORDER BY COUNT(*) DESC",
                    (*terminal, old_cutoff),
                ).fetchall()
                stranded = {str(row["state"]): int(row["c"]) for row in stranded_rows}
                proposed_old = int(conn.execute(
                    "SELECT COUNT(*) c FROM campaign_candidates cc JOIN campaigns cm "
                    "ON cm.campaign_id=cc.campaign_id WHERE cm.status='active' "
                    "AND cc.state='PROPOSED' AND cc.updated_utc<=?", (old_cutoff,),
                ).fetchone()["c"])
                if stranded:
                    findings.append({
                        "key": "liveness:work-supply-starved", "severity": "error",
                        "category": "pipeline_starvation",
                        "message": "compute capacity is idle because non-terminal candidates are not producing runnable work",
                        "detail": {
                            "unused_compute_slots": unused_compute_slots,
                            "total_slots": total_slots,
                            "claimable_simulations": claimable_sim,
                            "claimable_analysis": queued_analysis,
                            "stranded_candidates": sum(stranded.values()),
                            "stranded_by_state": stranded,
                            "old_proposals_waiting": proposed_old,
                            "age_threshold_seconds": queue_age_seconds,
                            "report_hint": "Report N / capacity_diagnosis + pipeline_blockers",
                        },
                    })
                elif proposed_old:
                    findings.append({
                        "key": "liveness:admission-supply-starved", "severity": "warning",
                        "category": "pipeline_starvation",
                        "message": "compute capacity is idle while old proposals wait upstream of runnable work",
                        "detail": {
                            "unused_compute_slots": unused_compute_slots,
                            "total_slots": total_slots,
                            "old_proposals_waiting": proposed_old,
                            "age_threshold_seconds": queue_age_seconds,
                            "report_hint": "Report N / capacity_diagnosis + pipeline_blockers",
                        },
                    })

    live_terminal = conn.execute(
        "SELECT COUNT(*) c FROM campaign_candidates cc WHERE "
        f"cc.state IN ({marks}) AND (EXISTS(SELECT 1 FROM jobs j WHERE "
        "j.campaign_id=cc.campaign_id AND j.candidate_id=cc.candidate_id "
        "AND j.status IN ('queued','leased')) OR EXISTS(SELECT 1 FROM analysis_queue q WHERE "
        "q.campaign_id=cc.campaign_id AND q.candidate_id=cc.candidate_id "
        "AND q.status IN ('queued','leased')))", terminal,
    ).fetchone()["c"]
    if int(live_terminal):
        findings.append({
            "key": "liveness:terminal-candidate-work", "severity": "error",
            "category": "workflow_integrity",
            "message": "terminal candidates still own queued or leased work",
            "detail": {"candidates": int(live_terminal)},
        })
    return findings
