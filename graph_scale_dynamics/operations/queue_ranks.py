from __future__ import annotations

QUEUE_RANKS_CONTRACT = "gsd-queue-ranks-1"


def rerank_base_block(repo) -> dict:
    from graph_scale_dynamics.db.decision_store import QUEUE_RANK_STEP, queue_priority
    from graph_scale_dynamics.decisions.decider import QUEUE_ORDER
    from graph_scale_dynamics.decisions.engine import Policy
    base = int(QUEUE_ORDER["base"])
    moved: dict[str, int] = {}
    for campaign in repo.active_campaigns():
        top = int(Policy.from_spec(campaign.get("spec") or {}).base_sizes[-1])
        changed = int(repo.conn.execute(
            "UPDATE jobs SET priority=?+n WHERE campaign_id=? AND kind='simulate' AND status='queued' AND n<=? "
            "AND priority>=?", (queue_priority(base, 0), str(campaign["campaign_id"]), top,
                                (base + 1) * QUEUE_RANK_STEP)).rowcount or 0)
        if changed:
            moved[str(campaign["campaign_id"])] = changed
    return {"contract": QUEUE_RANKS_CONTRACT, "moved": moved}


def repair(repo) -> dict:
    return rerank_base_block(repo)


def render(result: dict) -> list[str]:
    moved = result.get("moved") or {}
    if not moved:
        return []
    by = ", ".join(f"campaign {c}: {n:,}" for c, n in sorted(moved.items()))
    return [f"queue: {sum(moved.values()):,} seed(s) of base-block rungs run again now wait at the base block's "
            f"rank ({by})"]
