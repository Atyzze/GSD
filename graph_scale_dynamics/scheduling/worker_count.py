from __future__ import annotations

import contextlib
import os
import signal

FLAG = "compute_worker_target"

MOST_FLAG = "compute_worker_most"

CONTRACT = "gsd-worker-count-1"


def most_of(raw, fallback: int) -> int:
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, int(fallback))


def wanted(raw, most: int) -> int | None:
    if raw in (None, "", "auto"):
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(int(most), count))


def asked(value, most: int) -> tuple[int | None, str | None]:
    if value in (None, "", "auto"):
        return None, None
    if isinstance(value, bool):
        return None, f"{value!r} is not a number of workers"
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None, f"{value!r} is not a number of workers"
    if isinstance(value, float) and value != count:
        return None, f"{value!r} is not a whole number of workers"
    if count < 1 or count > int(most):
        return None, f"choose between 1 and {int(most)} workers"
    return count, None


def plan(target: int | None, *, live: set[int], held: set[int], exiting: set[int],
         spawned: int) -> dict:
    if target is None:
        return {"stop": [], "restart": sorted(held - exiting), "spawn": [],
                "waiting": sorted(held & exiting)}
    target = max(1, int(target))
    return {
        "stop": sorted(slot for slot in live if slot >= target and slot not in held),
        "restart": sorted(slot for slot in held if slot < target and slot not in exiting),
        "spawn": list(range(int(spawned), target)),
        "waiting": sorted(slot for slot in held if slot < target and slot in exiting),
    }


def reading(target: int | None, most: int, running: int) -> str:
    if target is None:
        return (f"{int(running)} executor slot(s) running; the ramp chooses how many, "
                f"up to {int(most)}")
    return (f"{int(running)} executor slot(s) running toward the {int(target)} asked for; "
            f"a slot above the count stops at once, saves its seed where it is and gives "
            f"the rung back to the queue, so another slot resumes it")


def most_slots(ceiling: int, logical: int, environ) -> int:
    from graph_scale_dynamics.scheduling.concurrency import ramp_ceiling
    sized = (environ or {}).get("GSD_MAX_WORKERS")
    return max(int(ceiling), min(int(logical), ramp_ceiling(baseline=1, logical=int(logical),
                                                           override=int(sized) if sized else None)))


def resumed(repo, most: int, workers: int) -> int:
    return wanted(repo.get_flag(FLAG), most) or int(workers)


def stop_grace() -> float:
    from graph_scale_dynamics.artifact_store.resume_state import STOP_GRACE_SECONDS
    from graph_scale_dynamics.domain.cadence import ticks
    return float(STOP_GRACE_SECONDS + ticks(1))


def executor_slot(record: dict) -> int | None:
    extra = tuple(record.get("extra", ()))
    for index, value in enumerate(extra[:-1]):
        if value == "--slot":
            return int(extra[index + 1])
    return None


def _reap(repo, executors: dict, now: float) -> None:
    for slot, record in executors.items():
        proc = record.get("proc")
        if not record.get("held") or proc is None:
            continue
        if proc.poll() is not None:
            repo._write("DELETE FROM service_heartbeats WHERE service=?", (f"executor-{slot}-{proc.pid}",))
            record["proc"] = None
        elif now >= float(record.get("stop_by") or float("inf")):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)


def tick(repo, *, services: list, state: dict, most: int, paused: bool, launch, spawn, now: float,
         grace: float | None = None, say=None) -> int | None:
    target = wanted(repo.get_flag(FLAG), most)
    executors = {slot: record for record in services
                 if record.get("group") == "compute" and not record.get("disabled")
                 and (slot := executor_slot(record)) is not None}
    _reap(repo, executors, now)
    held = {slot for slot, record in executors.items() if record.get("held")}
    exiting = {slot for slot in held if executors[slot].get("proc") is not None}
    steps = plan(target, live=set(executors) - held, held=held, exiting=exiting, spawned=int(state["spawned"]))
    for slot in steps["stop"]:
        record = executors[slot]
        proc = record.get("proc")
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            record["stop_by"] = now + (stop_grace() if grace is None else float(grace))
        else:
            record["proc"] = None
        record["held"], record["suspended"] = True, True
    for slot in steps["restart"]:
        record = executors[slot]
        record["held"], record["stop_by"] = False, None
        if paused:
            record["suspended"] = True
        else:
            launch(record)
    for slot in steps["spawn"]:
        spawn(slot, start=not paused)
    if steps["spawn"]:
        state["spawned"] = max(int(state["spawned"]), steps["spawn"][-1] + 1)
    if target is not None and not paused and repo.get_flag("compute_active_slots") != str(target):
        repo.set_flag("compute_active_slots", str(target))
        repo.set_flag("compute_total_slots", str(target))
    changed = bool(steps["stop"] or steps["restart"] or steps["spawn"]) or target != state.get("target")
    state["target"] = target
    if not changed:
        return target
    running = sum(1 for record in executors.values() if not record.get("held")) + len(steps["spawn"])
    repo.emit("worker_count", {"contract": CONTRACT, "target": target, "most": int(most), "stopped": steps["stop"],
                               "restarted": steps["restart"], "spawned": steps["spawn"], "waiting": steps["waiting"]})
    line = (f"worker count: {'the ramp decides' if target is None else target}; stopped {steps['stop'] or 'none'}, "
            f"restarted {steps['restart'] or 'none'}, started {steps['spawn'] or 'none'}; {running} executor "
            "process(es) kept")
    (say or (lambda text: print(text, flush=True)))(line)
    return target


def state_of(repo, pool: int) -> dict:
    most = most_of(repo.get_flag(MOST_FLAG), pool)
    target = wanted(repo.get_flag(FLAG), most)
    running = int(repo.get_flag("compute_total_slots", "0") or 0) if target is None else target
    return {"contract": CONTRACT, "target": target, "most": most,
            "active_slots": int(repo.get_flag("compute_active_slots", "0") or 0),
            "reading": reading(target, most, running)}


__all__ = ["CONTRACT", "FLAG", "MOST_FLAG", "asked", "executor_slot", "most_of", "most_slots", "plan", "reading",
           "resumed", "state_of", "stop_grace", "tick", "wanted"]
