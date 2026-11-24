from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import utc_now
from graph_scale_dynamics.operations.study import STUDY_CONTRACT, budget_state, law_budget, laws_held, set_law_budget

FLAG = "auto_extend"
LAST_FLAG = "auto_extend_last"
LAWS = 50
OPEN = ("active", "completed")


def is_on(repo) -> bool:
    return str(repo.get_flag(FLAG, "") or "") == "1"


def state(repo) -> dict:
    try:
        last = json.loads(repo.get_flag(LAST_FLAG, "") or "null")
    except (TypeError, ValueError):
        last = None
    return {"on": is_on(repo), "laws": LAWS, "last": last if isinstance(last, dict) else None}


def switch(repo, on: bool) -> dict:
    on = bool(on)
    if is_on(repo) != on:
        repo.set_flag(FLAG, "1" if on else "")
        repo.emit("study_auto_extend_switched", {"contract": STUDY_CONTRACT, "on": on, "laws": LAWS, "at": utc_now()})
    return {"ok": True, "auto_extend": state(repo),
            "reading": (f"on: once every campaign with a law budget is finished, each gets {LAWS} more laws, and again "
                        "each time they finish, until this is switched off or the fleet is stopped" if on
                        else "off: a campaign that reaches its law budget and decides its laws is finished")}


def batches(repo) -> list[dict]:
    found = []
    for row in repo.conn.execute("SELECT campaign_id,status FROM campaigns ORDER BY campaign_id").fetchall():
        campaign_id, status = str(row["campaign_id"]), str(row["status"] or "")
        budget = law_budget(repo, campaign_id)
        if budget is not None and status in OPEN:
            found.append({"campaign_id": campaign_id, "status": status, "budget": budget,
                          "held": laws_held(repo, campaign_id)})
    return found


def holds(repo, campaign_id: str) -> bool:
    return is_on(repo) and law_budget(repo, str(campaign_id)) is not None


def finished(repo, batch: dict) -> bool:
    return batch["status"] == "completed" or bool((budget_state(repo, batch["campaign_id"]) or {}).get("done"))


def extend_if_all_finished(repo) -> dict | None:
    if not is_on(repo):
        return None
    found = batches(repo)
    if not found or not all(finished(repo, batch) for batch in found):
        return None
    record = {"contract": STUDY_CONTRACT, "at": utc_now(), "laws": LAWS, "campaigns": {}}
    for batch in found:
        wanted = max(batch["budget"], batch["held"]) + LAWS
        set_law_budget(repo, batch["campaign_id"], wanted,
                       reason=f"auto extend: every campaign was finished, so each gets {LAWS} more laws")
        if batch["status"] != "active":
            repo.set_campaign_status(batch["campaign_id"], "active")
        record["campaigns"][batch["campaign_id"]] = {"from": batch["budget"], "to": wanted, "held": batch["held"]}
    repo.set_flag(LAST_FLAG, json.dumps(record, sort_keys=True))
    repo.emit("study_auto_extended", record)
    return record
