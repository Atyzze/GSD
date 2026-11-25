from __future__ import annotations

import json

from graph_scale_dynamics.decisions import engine as E
from graph_scale_dynamics.decisions import gates as G

RULE = "run_on"
FLAG = "run_on"
CONTRACT = "gsd-run-on-1"


def flag_value(raw) -> dict:
    if isinstance(raw, dict):
        found = raw
    else:
        try:
            found = json.loads(raw or "null")
        except (TypeError, ValueError):
            return {}
    return found if isinstance(found, dict) and found.get("contract") == CONTRACT else {}


def entries_of(raw, campaign_id: str) -> dict[str, dict]:
    laws = (flag_value(raw).get("laws") or {}).get(str(campaign_id)) or {}
    return {str(law): dict(entry) for law, entry in laws.items()
            if isinstance(entry, dict) and entry.get("gate") and entry.get("at_n") is not None}


def flag(listed: dict, made: dict[str, dict[str, dict]]) -> dict:
    return {"contract": CONTRACT, "list": str(listed.get("path") or ""), "sha256": str(listed.get("sha256") or ""),
            "laws": {str(campaign): {str(law): dict(entry) for law, entry in sorted(laws.items())}
                     for campaign, laws in sorted(made.items())}}


def matches(decision: E.Decision, entry: dict) -> bool:
    return (decision.action == E.STOP and G.today(decision.rule) == G.today(entry.get("gate"))
            and decision.at_n is not None and int(decision.at_n) == int(entry["at_n"]))


def run_on(decision: E.Decision, entry: dict | None, policy: E.Policy) -> E.Decision:
    if not entry or not matches(decision, entry):
        return decision
    following = next((int(n) for n in policy.ladder() if int(n) > int(decision.at_n)), None)
    if following is None:
        return decision
    said = {"gate": str(decision.rule), "at_n": int(decision.at_n), "list": str(entry.get("list") or ""),
            "class": entry.get("class"), "held": {"action": decision.action, "reason": decision.reason}}
    facts = dict(decision.facts or {}, run_on=said)
    return E.Decision(law=decision.law, action=E.RUN_NEXT, rule=RULE,
                      reason=(f"run on by the operator's word past {decision.rule} at N={int(decision.at_n):,}, "
                              f"to N={following:,}" + (f" ({said['list']})" if said["list"] else "")
                              + f"; {decision.rule}: {decision.reason}"),
                      at_n=decision.at_n, next_n=following, priority=2, facts=facts,
                      observations=decision.observations)


__all__ = ["CONTRACT", "FLAG", "RULE", "entries_of", "flag", "flag_value", "matches", "run_on"]
