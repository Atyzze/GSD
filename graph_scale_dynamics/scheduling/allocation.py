from __future__ import annotations

import math


def compute_allocation(*, total_slots: int, max_analyzers: int,
                       analysis_backlog: int, queued_simulations: int,
                       leased_simulations: int, paused: bool = False,
                       analysis_weight: float = 2.0) -> dict[str, int | bool]:
    total = max(0, int(total_slots))
    analyzer_cap = max(0, min(total, int(max_analyzers)))
    backlog = max(0, int(analysis_backlog))
    queued = max(0, int(queued_simulations))
    leased = max(0, int(leased_simulations))
    simulation_work = queued + leased

    if paused or total == 0:
        return {"total_slots": total, "simulation_slots": 0, "analysis_slots": 0,
                "analysis_backlog": backlog, "paused": bool(paused)}

    if backlog == 0 or analyzer_cap == 0:
        simulation_slots = total if simulation_work else 0
        return {"total_slots": total, "simulation_slots": simulation_slots,
                "analysis_slots": 0, "analysis_backlog": backlog, "paused": False}

    if simulation_work == 0:
        analysis_slots = min(analyzer_cap, backlog)
        return {"total_slots": total, "simulation_slots": 0,
                "analysis_slots": analysis_slots, "analysis_backlog": backlog,
                "paused": False}

    if total == 1:
        return {"total_slots": 1, "simulation_slots": 0, "analysis_slots": 1,
                "analysis_backlog": backlog, "paused": False}

    weighted_analysis = backlog * max(0.1, float(analysis_weight))
    proportional = math.ceil(total * weighted_analysis / (weighted_analysis + simulation_work))
    analysis_slots = max(1, min(analyzer_cap, backlog, total - 1, proportional))
    return {"total_slots": total, "simulation_slots": total - analysis_slots,
            "analysis_slots": analysis_slots, "analysis_backlog": backlog,
            "paused": False}


def first_work(runs: dict[int, int], probes: dict[int, int], backlog: int, queued: int) -> tuple[int, int]:
    tiers = sorted({tier for tier, count in runs.items() if count} | {tier for tier, count in probes.items() if count})
    if not tiers:
        return backlog, queued
    first = tiers[0]
    return (sum(count for tier, count in probes.items() if tier <= first),
            sum(count for tier, count in runs.items() if tier <= first))
