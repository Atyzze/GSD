from __future__ import annotations

from graph_scale_dynamics.scheduling.memory import (
    AGGREGATE_MEMORY_TARGET_FRACTION, HOST_EMERGENCY_MEMORY_FRACTION_CAP, host_available_floor_bytes)


def _fraction(value: int | float | None, total: int | float | None) -> float | None:
    try:
        numerator = float(value or 0)
        denominator = float(total or 0)
    except (TypeError, ValueError):
        return None
    if denominator <= 0:
        return None
    return max(0.0, numerator / denominator)


def _gib(value) -> str:
    return f"{max(0, int(value or 0)) / (1 << 30):.1f} GiB"


def _utc(epoch) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(epoch)))


def memory_room(conn, admission: dict | None, *, now: float | None = None) -> dict:
    import time
    from graph_scale_dynamics.scheduling import memory_hold
    clock = time.time() if now is None else float(now)
    row = memory_hold.read(conn) or {}
    scratch = memory_hold.scratch_room(conn, now=clock)
    admission = admission or {}
    hold = None
    if row.get("state") == "holding" and clock < float(row.get("until_epoch") or 0):
        ask = int(row.get("requested_bytes") or 0)
        hold = {**{k: row.get(k) for k in ("job_id", "campaign_id", "n", "requested_bytes", "since_utc")},
                "until_utc": _utc(row["until_epoch"]),
                "left_to_simulations_bytes": max(0, int(admission.get("headroom_bytes") or 0) - ask),
                "left_to_small_seeds_bytes": max(0, int(admission.get("small_pool_headroom_bytes") or 0) - ask),
                "analyses_held_back": False}
    unfit = row.get("unfit") or None
    if unfit and clock - float(unfit.get("at_epoch") or 0) > memory_hold.UNFIT_SHOWN_SECONDS:
        unfit = None
    parts = {"available_bytes": int(admission.get("available_bytes") or 0),
             "children_bytes": int(admission.get("held_bytes") or 0),
             "movable_bytes": int((scratch or {}).get("movable_bytes") or 0),
             "floor_bytes": int(admission.get("floor_bytes") or 0)}
    resting = row.get("state") == "rested" and clock < float(row.get("rest_until_epoch") or 0)
    return {"hold": hold, "unfit": unfit, "scratch": scratch,
            "reach": dict(parts, reach_bytes=memory_hold.reach_bytes(**parts)) if admission else None,
            "rested_until_utc": _utc(row["rest_until_epoch"]) if resting else None,
            "run_outs": int(row.get("run_outs") or 0)}


def room_reading(room: dict | None) -> str:
    room = room or {}
    said = []
    hold, unfit, scratch = room.get("hold"), room.get("unfit"), room.get("scratch")
    if hold:
        said.append(f"A {int(hold.get('n') or 0):,} seed (job {str(hold.get('job_id'))[:12]}, campaign "
                    f"{hold.get('campaign_id')}) is held for: it asks {_gib(hold.get('requested_bytes'))}, held since "
                    f"{hold.get('since_utc')} until {hold.get('until_utc')}; "
                    f"{_gib(hold.get('left_to_simulations_bytes'))} of the headroom is left to other simulations "
                    f"({_gib(hold.get('left_to_small_seeds_bytes'))} to seeds of at most 1% of the host), and no "
                    "analysis is held back.")
    elif room.get("rested_until_utc"):
        said.append(f"No seed is held until {room['rested_until_utc']}: the last hold ran out "
                    f"({int(room.get('run_outs') or 0)} in a row).")
    if unfit and not (hold and str(hold.get("job_id")) == str(unfit.get("job_id"))):
        said.append(f"A {int(unfit.get('n') or 0):,} seed asks {_gib(unfit.get('requested_bytes'))}; with the RAM "
                    f"scratch spilled and nothing running, this host gives at most {_gib(unfit.get('reach_bytes'))} "
                    f"({_gib(unfit.get('available_bytes'))} available + {_gib(unfit.get('children_bytes'))} held by "
                    f"running children + {_gib(unfit.get('movable_bytes'))} the relief may move - the "
                    f"{_gib(unfit.get('floor_bytes'))} floor), so no room is held for it: it waits, refused, as any "
                    "seed larger than the room does, and smaller seeds run meanwhile.")
    if scratch:
        said.append(f"The RAM scratch holds {_gib(scratch.get('used_bytes'))} of {_gib(scratch.get('total_bytes'))} "
                    f"({float(scratch.get('fraction') or 0.0):.0%}); the relief {scratch.get('doing')}.")
    return " ".join(said)


def memory_floor_verdict(admission: dict | None, *, waiting: int, deferred: int, idle: int,
                         reservation_percent: float = 0.0, slots: int = 0,
                         room: dict | None = None) -> tuple[str, str, str] | None:
    material = max(2, int(int(slots) * 0.25)) if int(slots) > 0 else 2
    if not admission or int(idle) < material or int(waiting) + int(deferred) <= 0:
        return None
    if int(deferred) <= 0 and float(reservation_percent or 0.0) < 97.0:
        return None
    held = (room or {}).get("hold")
    reading = room_reading(room)
    tail = f" {reading}" if reading else ""
    small = int(admission.get("small_pool_limit_bytes") or (1 << 30))
    if int(admission.get("headroom_bytes") or 0) >= small:
        left = (f"the headroom less the {_gib(held.get('requested_bytes'))} held for a {int(held.get('n') or 0):,} "
                "seed" if held else "the headroom, no room being held for a lane's seed")
        return ("SEEDS_LARGER_THAN_HEADROOM", "normal",
                f"The fleet is not at its floor: {_gib(admission.get('headroom_bytes'))} headroom beyond the "
                f"{_gib(admission.get('floor_bytes'))} the host keeps available ({_gib(admission.get('available_bytes'))} "
                f"available, {_gib(admission.get('unrealised_bytes'))} still to be taken by running children). "
                f"{int(deferred)} seed(s) were refused in the last few seconds: each asked more than the room left "
                f"to it, {left}. A worker refused takes a smaller seed "
                f"instead, so {int(idle)} slot(s) stay idle only while every seed that waits is larger than that."
                + tail)
    return ("MEMORY_FLOOR", "normal",
            f"The fleet is using memory down to the {_gib(admission.get('floor_bytes'))} the host keeps available: "
            f"{_gib(admission.get('available_bytes'))} available, {_gib(admission.get('unrealised_bytes'))} more "
            f"reserved by running children than they have taken yet, {_gib(admission.get('headroom_bytes'))} "
            f"headroom. {int(waiting) + int(deferred)} job(s) wait for memory with {int(idle)} slot(s) idle. "
            "This is the operating point the floor sets: work starts as children finish or the host frees "
            f"memory, and simulations are stopped if the host's own use takes available memory under "
            f"{_gib(admission.get('shed_below_bytes'))}." + tail)


def capacity_diagnosis(*, total_slots: int, simulation_active: int,
                       analysis_active: int, simulation_claimable: int,
                       analysis_claimable: int, memory_reserved_bytes: int,
                       memory_budget_bytes: int, host_memory_used_bytes: int | None = None,
                       host_memory_total_bytes: int | None = None,
                       host_cpu_percent: float | None = None, paused: bool = False,
                       active_campaigns: int = 1, stranded_nonterminal: int = 0, held: int = 0,
                       proposed_waiting: int = 0, deferred_analysis: int = 0,
                       recent_memory_refusals: int = 0,
                       orphaned_or_phantom_leases: int = 0) -> dict:
    total_slots = max(0, int(total_slots or 0))
    simulation_active = max(0, int(simulation_active or 0))
    analysis_active = max(0, int(analysis_active or 0))
    simulation_claimable = max(0, int(simulation_claimable or 0))
    analysis_claimable = max(0, int(analysis_claimable or 0))
    used_slots = simulation_active + analysis_active
    runnable = simulation_claimable + analysis_claimable
    unused_slots = max(0, total_slots - used_slots)
    cpu_slot_fraction = _fraction(used_slots, total_slots)
    memory_fraction = _fraction(memory_reserved_bytes, memory_budget_bytes)
    host_memory_fraction = _fraction(host_memory_used_bytes, host_memory_total_bytes)

    executor_near_capacity = bool(total_slots and cpu_slot_fraction is not None and cpu_slot_fraction >= 0.75)
    host_cpu_saturated = bool(host_cpu_percent is not None and float(host_cpu_percent) >= 90.0)
    actual_memory_saturated = bool(host_memory_fraction is not None and host_memory_fraction >= 0.90)
    materially_underfilled = bool(total_slots and unused_slots >= max(2, int(total_slots * 0.25)))

    state = "UNKNOWN_UNDERFILL"
    pressure = "unknown"
    severity = "warning"
    explanation = "Compute capacity is underfilled and no single named limiter explains it."
    next_focus = "Inspect pipeline blockers, deferred work, and scheduler/lease reconciliation."

    if paused:
        state = "PAUSED"
        pressure = "operator"
        severity = "info"
        explanation = "The fleet is explicitly paused by operator control."
        next_focus = "Resume the fleet when desired."
    elif executor_near_capacity and runnable and host_cpu_saturated:
        state = "CPU_LIMITED"
        pressure = "cpu"
        severity = "good"
        explanation = "Runnable work substantially occupies the executor fleet and measured host CPU is saturated."
        next_focus = "The CPU is the current limiting resource; measure throughput before increasing executor exposure."
    elif executor_near_capacity and runnable:
        state = "EXECUTOR_CONCURRENCY_LIMITED"
        pressure = "executor_concurrency"
        severity = "warning"
        explanation = (
            f"Configured executor capacity is substantially occupied but host CPU is only {float(host_cpu_percent or 0.0):.1f}%; "
            "configured executor concurrency, not CPU saturation, is the throughput-scale ceiling."
        )
        next_focus = "Increase/repair usable executor concurrency unless measured RAM or I/O evidence prevents it."
    elif actual_memory_saturated and (runnable or used_slots):
        state = "RAM_ADMISSION_CAP"
        pressure = "memory"
        severity = "warning"
        explanation = "Measured host memory use is at the admission boundary before executor capacity is full."
        next_focus = "Inspect actual PSS/USS and memory-deferred work; reservation percentage alone is not pressure evidence."
    elif deferred_analysis and recent_memory_refusals and materially_underfilled:
        state = "MEMORY_DEFERRED"
        pressure = "memory_prediction"
        severity = "error"
        explanation = "Analysis work exists but is deferred after recent memory-admission refusals while compute is underfilled."
        next_focus = "Inspect deferred rows and recent memory-admission refusal predictions."
    elif runnable and used_slots and materially_underfilled and host_cpu_saturated:
        state = "HOST_CPU_CONTENTION"
        pressure = "host_cpu"
        severity = "warning"
        explanation = (
            "Measured host CPU is saturated before all configured executor slots are occupied. "
            "Unused logical slots therefore do not, by themselves, prove scheduler underfill; "
            "external processes, oversubscription, or per-job parallelism may already consume the CPU."
        )
        next_focus = "Inspect GSD/external CPU attribution and per-job CPU demand before increasing executor concurrency or debugging scheduler admission."
    elif runnable and materially_underfilled:
        state = "SCHEDULER_UNDERFILL"
        pressure = "scheduler"
        severity = "error"
        explanation = "Runnable work exists while a material fraction of configured compute slots is unused."
        next_focus = "Inspect leases, child launches, campaign caps, and admission decisions."
    elif materially_underfilled and stranded_nonterminal:
        state = "WORK_SUPPLY_STARVED"
        pressure = "pipeline"
        severity = "error"
        explanation = (
            "The compute fleet is starved upstream: active non-terminal candidates exist, but they own no runnable "
            "simulation/analysis/rebuild work."
        )
        next_focus = "Inspect pipeline_blockers; state/action groups identify where lifecycle reconciliation stopped producing work."
    elif materially_underfilled and proposed_waiting:
        state = "ADMISSION_SUPPLY_STARVED"
        pressure = "admission_pipeline"
        severity = "error"
        explanation = "Compute is underfilled while proposals wait upstream and no runnable scientific work reaches executors."
        next_focus = "Inspect proposal/admission state and active-candidate capacity."
    elif active_campaigns and materially_underfilled and not runnable:
        state = "PIPELINE_IDLE"
        pressure = "pipeline"
        severity = "warning"
        explanation = "Active campaigns have no claimable work and compute capacity is materially idle." + (
            f" {int(held)} held law(s) own no work by design; the engine buys a held law's next rung when the "
            "simulation queue is empty." if held else "")
        next_focus = "Inspect pipeline blockers and control-event lag; the scheduler cannot create scientific work itself."
    elif not active_campaigns and not used_slots and not runnable:
        state = "IDLE_COMPLETE"
        pressure = "none"
        severity = "info"
        explanation = "No active campaign or runnable work remains."
        next_focus = "No action required."
    elif not materially_underfilled:
        state = "NEAR_CAPACITY"
        pressure = "executor_concurrency"
        severity = "good"
        explanation = "Configured executor capacity is substantially occupied; no queued work currently needs additional slots."
        next_focus = "Continue observing throughput and measured memory/I/O headroom."

    if orphaned_or_phantom_leases and materially_underfilled:
        state = "LEASE_CHILD_MISMATCH"
        pressure = "lease_lifecycle"
        severity = "error"
        explanation = "Leases consume scheduler state without corresponding live compute children."
        next_focus = "Inspect lease ownership/expiry and child-launch fencing before changing resource limits."

    invariant = (
        "When eligible scientific work exists, configured executor capacity or measured host resources should saturate; "
        "otherwise underfill must have an explicit pipeline/scheduler/operator explanation."
    )
    if state in {"CPU_LIMITED", "HOST_CPU_CONTENTION", "EXECUTOR_CONCURRENCY_LIMITED", "RAM_ADMISSION_CAP", "NEAR_CAPACITY"}:
        invariant_status = "SATURATED"
    elif state in {"PAUSED", "IDLE_COMPLETE"}:
        invariant_status = "NOT_APPLICABLE"
    elif state in {
        "WORK_SUPPLY_STARVED", "ADMISSION_SUPPLY_STARVED", "MEMORY_DEFERRED",
        "SCHEDULER_UNDERFILL", "PIPELINE_IDLE", "LEASE_CHILD_MISMATCH",
    }:
        invariant_status = "EXPLAINED_UNDERFILL"
    else:
        invariant_status = "UNEXPLAINED_UNDERFILL"

    return {
        "state": state,
        "pressure": pressure,
        "severity": severity,
        "invariant_status": invariant_status,
        "invariant": invariant,
        "explanation": explanation,
        "next_focus": next_focus,
        "cpu": {
            "configured_slots": total_slots,
            "active_simulations": simulation_active,
            "active_analyses": analysis_active,
            "active_compute": used_slots,
            "unused_slots": unused_slots,
            "slot_fraction": cpu_slot_fraction,
            "host_cpu_percent": host_cpu_percent,
        },
        "memory": {
            "reserved_bytes": int(memory_reserved_bytes or 0),
            "budget_bytes": int(memory_budget_bytes or 0),
            "reservation_fraction": memory_fraction,
            "host_used_bytes": None if host_memory_used_bytes is None else int(host_memory_used_bytes),
            "host_total_bytes": None if host_memory_total_bytes is None else int(host_memory_total_bytes),
            "host_fraction": host_memory_fraction,
        },
        "work": {
            "claimable_simulations": simulation_claimable,
            "claimable_analyses": analysis_claimable,
            "claimable_total": runnable,
            "deferred_analysis": max(0, int(deferred_analysis or 0)),
            "stranded_nonterminal_candidates": max(0, int(stranded_nonterminal or 0)),
            "held_candidates": max(0, int(held or 0)),
            "proposed_waiting": max(0, int(proposed_waiting or 0)),
            "recent_memory_refusals": max(0, int(recent_memory_refusals or 0)),
        },
    }


def current_capacity_diagnosis(snapshot: dict, queue: dict, blockers: dict) -> dict:
    scheduler = snapshot.get("scheduler_snapshot") or {}
    reservations = snapshot.get("memory_reservation_snapshot") or {}
    telemetry = snapshot.get("latest_telemetry") or {}
    recent_refusals = [row for row in snapshot.get("recent_memory_refusals", [])
                       if row.get("age_seconds") is not None and float(row["age_seconds"]) <= 300]
    host_simulation = snapshot.get("host_simulation_work")
    if isinstance(host_simulation, dict):
        simulation_active = int(host_simulation.get("leased") or 0)
        simulation_claimable = int(host_simulation.get("queued") or 0)
    else:
        simulation_active = int(scheduler.get("leased_simulations") or 0)
        simulation_claimable = int(scheduler.get("queued_simulations") or 0)
    if "host_active_analysis_claims" in snapshot:
        analysis_active = int(snapshot.get("host_active_analysis_claims") or 0)
    else:
        analysis_active = int(queue.get("analysis_leased") or telemetry.get("active_analyses") or 0)
    queue_claimable = int(queue.get("analysis_claimable_now") or 0)
    host_claimable = None
    if "host_analysis_backlog" in snapshot:
        host_claimable = max(0, int(snapshot.get("host_analysis_backlog") or 0) - analysis_active)
    analysis_claimable = queue_claimable if host_claimable is None else max(host_claimable, queue_claimable)
    claimable_source = {
        "used": analysis_claimable,
        "from_durable_queue": queue_claimable,
        "from_scheduler_state": host_claimable,
        "scheduler_state_behind_queue": bool(host_claimable is not None and host_claimable < queue_claimable),
        "reading": (
            "two counts of the same quantity: `from_scheduler_state` is refresh_scheduler_state's "
            "cached backlog less what is leased, `from_durable_queue` counts the queued analysis and "
            "evidence-rebuild rows that are runnable now. The larger is used, because the snapshot is a "
            "subset of the host and a smaller host figure can only be stale. When "
            "`scheduler_state_behind_queue` is true the cached figure has stopped being refreshed, and "
            "every number derived from it understates the work that exists"
        ),
    }
    diagnosis = capacity_diagnosis(
        total_slots=int(scheduler.get("total_slots") or 0),
        simulation_active=simulation_active,
        analysis_active=analysis_active,
        simulation_claimable=simulation_claimable,
        analysis_claimable=analysis_claimable,
        memory_reserved_bytes=int(reservations.get("total") or 0),
        memory_budget_bytes=int(reservations.get("budget") or 0),
        host_memory_used_bytes=telemetry.get("memory_used_bytes"),
        host_memory_total_bytes=telemetry.get("memory_total_bytes"),
        host_cpu_percent=telemetry.get("cpu_percent"),
        paused=bool(scheduler.get("paused")),
        active_campaigns=int(snapshot.get("active_campaign_count") or 0),
        stranded_nonterminal=int(blockers.get("stranded_nonterminal") or 0),
        held=int(blockers.get("held") or 0),
        proposed_waiting=int(blockers.get("proposed_waiting") or 0),
        deferred_analysis=int(queue.get("analysis_deferred") or 0),
        recent_memory_refusals=len(recent_refusals),
    )
    memory_detail = diagnosis.setdefault("memory", {})
    host_total = int(telemetry.get("memory_total_bytes") or 0)
    memory_detail["target_host_fraction"] = AGGREGATE_MEMORY_TARGET_FRACTION
    memory_detail["emergency_host_fraction"] = HOST_EMERGENCY_MEMORY_FRACTION_CAP
    memory_detail["minimum_host_available_bytes"] = host_available_floor_bytes(host_total) if host_total else 0
    memory_detail["budget_host_fraction"] = (
        float(reservations.get("budget") or 0) / float(host_total) if host_total else None
    )

    diagnosis["scope"] = {
        "scheduler_and_memory": "host-wide active fleet",
        "pipeline_blockers": f"campaign {snapshot.get('campaign_id')}",
        "latest_telemetry_utc": telemetry.get("sampled_utc"),
        "report_collected_utc": snapshot.get("collected_utc"),
    }
    diagnosis["recent_memory_refusals_5m"] = recent_refusals[:20]
    diagnosis["claimable_analysis_source"] = claimable_source
    if claimable_source["scheduler_state_behind_queue"]:
        diagnosis["explanation"] = (
            f"{diagnosis.get('explanation', '')} Scheduler state reports "
            f"{claimable_source['from_scheduler_state']} claimable analyses while the durable queue "
            f"holds {claimable_source['from_durable_queue']}; the cache is behind the queue, so this "
            "verdict is computed from the queue and the scheduler-state figures on this page are stale."
        ).strip()
    gates = blockers.get("controller_gate_counts") or {}
    stale_count = sum(int(gates.get(key) or 0) for key in (
        "STALE_DECISION_ALREADY_DRAINED",
        "DETERMINISTIC_JOB_COLLISION_PRIOR_GENERATION",
        "DRAINED_JOB_ANALYSIS_MISSING",
    ))
    mismatch_count = int(gates.get("CHECKPOINT_EVIDENCE_MISMATCH") or 0)
    terminal_failure_count = int(gates.get("EXISTING_JOB_TERMINAL_FAILURE") or 0)
    if diagnosis.get("state") == "WORK_SUPPLY_STARVED" and mismatch_count:
        diagnosis["state"] = "CHECKPOINT_EVIDENCE_MISMATCH"
        diagnosis["pressure"] = "decision_lifecycle"
        diagnosis["severity"] = "error"
        diagnosis["explanation"] = (
            f"{mismatch_count} stranded cumulative jobs are marked done/analyzed but their "
            "measurement evidence does not certify the requested checkpoint multiplier."
        )
        diagnosis["next_focus"] = (
            "mismatched deterministic checkpoints are retried with a bounded generation; "
            "inspect pipeline_blockers retry/evidence detail if they persist."
        )
        diagnosis["invariant_status"] = "EXPLAINED_UNDERFILL"
    elif diagnosis.get("state") == "WORK_SUPPLY_STARVED" and terminal_failure_count:
        diagnosis["state"] = "CHECKPOINT_RETRY_REQUIRED"
        diagnosis["pressure"] = "decision_lifecycle"
        diagnosis["severity"] = "warning"
        diagnosis["explanation"] = (
            f"{terminal_failure_count} stranded cumulative checkpoint jobs are terminal failures; "
            "bounded retry generations should materialize automatically."
        )
        diagnosis["next_focus"] = "Inspect controller retry generations if this state persists beyond one reconciliation interval."
        diagnosis["invariant_status"] = "EXPLAINED_UNDERFILL"
    elif diagnosis.get("state") == "WORK_SUPPLY_STARVED" and stale_count:
        diagnosis["state"] = "STALE_DECISION_LOOP"
        diagnosis["pressure"] = "decision_lifecycle"
        diagnosis["severity"] = "error"
        diagnosis["explanation"] = (
            f"{stale_count} stranded candidates are replaying compute decisions whose deterministic "
            "checkpoint jobs are already terminal or collide with an earlier generation."
        )
        diagnosis["next_focus"] = (
            "Inspect pipeline_blockers sampling revisions and latest decision applications; completed "
            "sampling evidence must advance decision identity before another checkpoint is materialized."
        )
        diagnosis["invariant_status"] = "EXPLAINED_UNDERFILL"
    return diagnosis
