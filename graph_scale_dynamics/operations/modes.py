from __future__ import annotations

import json

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-fleet-mode-1"
FLAG = "fleet_mode"
PUSH, ZONE, BLIND = "push", "zone", "blind"
NAMES = {PUSH: "the N-push", ZONE: "the zone search", BLIND: "the blind ladder"}
ZONE_PARTS = ("N", "S", "E")


def zone_work(state: dict) -> str | None:
    from graph_scale_dynamics.operations import dex_check, focus
    if dex_check.first(state) and dex_check.records(state) and not state.get(dex_check.ZONE):
        return "the dex read in is being checked"
    current = state.get("current") or {}
    if current and current.get("stage") not in focus.ENDED:
        return f"{current.get('label') or str(current.get('law'))[:12]} is in focus"
    if dex_check.taken(state):
        return "a zone is chosen and waits to be taken"
    return None


def kind_of(spec: dict | None) -> str:
    design = (spec or {}).get("study_design") or {}
    part = (design.get("focus") or {}).get("part")
    if design.get("kind") == "focus" and part in ZONE_PARTS or design.get("kind") == "seed":
        return ZONE
    if design.get("kind") == "focus" and part in ("D", "P"):
        return PUSH
    return BLIND


def compute(repo, state: dict | None) -> dict | None:
    from graph_scale_dynamics.operations import push, push_ladder
    if not state or state.get("stopped"):
        return None
    first = push.ahead(state, {})
    if first is not None:
        camp = push_ladder.campaign(repo, state)
        label = (state["contenders"].get(first) or {}).get("label") or first[:12]
        return {"mode": PUSH, "campaigns": [camp], "laws": [first], "why": f"{label} is first on the push list"}
    active = [c for c in repo.all_campaigns() if str(c.get("status") or "active") == "active"]
    by = {ZONE: [], BLIND: [], PUSH: []}
    for c in active:
        by[kind_of(c.get("spec"))].append(str(c["campaign_id"]))
    why = zone_work(state)
    if why is not None:
        return {"mode": ZONE, "campaigns": by[ZONE], "laws": [], "why": why}
    return {"mode": BLIND, "campaigns": by[BLIND], "laws": [], "why": "no law is pushed and no zone has work"}


def keep(repo, state: dict | None) -> dict | None:
    found = compute(repo, state)
    getter, setter = getattr(repo, "get_flag", None), getattr(repo, "set_flag", None)
    if not callable(getter) or not callable(setter):
        return found
    was = here(repo)
    if found is None:
        if was is not None:
            setter(FLAG, "")
        return None
    same = was is not None and all(was.get(k) == found.get(k) for k in ("mode", "campaigns", "laws"))
    found["since"] = was["since"] if same and was.get("since") else utc_now()
    if not same or was.get("why") != found["why"]:
        setter(FLAG, json.dumps(found, sort_keys=True))
    return found


def here(repo) -> dict | None:
    getter = getattr(repo, "get_flag", None)
    if not callable(getter):
        return None
    try:
        found = json.loads(getter(FLAG, "") or "null")
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) and found.get("mode") in NAMES else None


def pushing(repo) -> dict | None:
    found = here(repo)
    if found is None or found["mode"] != PUSH or not found.get("campaigns") or not found.get("laws"):
        return None
    return {"campaign": str(found["campaigns"][0]), "laws": [str(x) for x in found["laws"]], "host": True}


__all__ = ["BLIND", "CONTRACT", "FLAG", "NAMES", "PUSH", "ZONE", "compute", "here", "keep", "kind_of", "pushing",
           "zone_work"]
