from __future__ import annotations

import json

from graph_scale_dynamics.decisions import engine as E

RULE = "memory_ceiling"
FLAG = "memory_ceiling"
CONTRACT = "gsd-memory-ceiling-1"
GIB = 1024 ** 3


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
            if isinstance(entry, dict) and entry.get("next_n") is not None and entry.get("needs_bytes") is not None}


def flag(laws: dict[str, dict[str, dict]]) -> dict:
    return {"contract": CONTRACT, "laws": {str(c): {str(law): dict(e) for law, e in sorted(found.items())}
                                           for c, found in sorted(laws.items()) if found}}


def _gib(value) -> str:
    return f"{float(value) / GIB:,.1f} GiB"


def settle(decision: E.Decision, entry: dict | None, policy: E.Policy) -> E.Decision:
    if not entry or decision.action != E.RUN_NEXT or decision.next_n is None:
        return decision
    if int(decision.next_n) < int(entry["next_n"]):
        return decision
    said = {key: entry.get(key) for key in ("reached", "next_n", "needs_bytes", "reach_bytes", "free_bytes", "from")}
    reason = (f"settled at its memory ceiling: read to N={int(entry.get('reached') or decision.at_n or 0):,}; "
              f"N={int(entry['next_n']):,} would need about {_gib(entry['needs_bytes'])}, priced from its own peaks "
              f"{entry.get('from') or 'below'}, past the host's reach of {_gib(entry.get('reach_bytes') or 0)} "
              f"with {_gib(entry.get('free_bytes') or 0)} kept free; everything it measured is kept")
    return E.Decision(law=decision.law, action=E.STOP, rule=RULE, reason=reason, at_n=decision.at_n, next_n=None,
                      priority=None,
                      facts=dict(decision.facts or {}, memory_ceiling=said,
                                 refused={"action": decision.action, "rule": decision.rule,
                                          "next_n": int(decision.next_n), "priority": decision.priority}),
                      observations=decision.observations)


__all__ = ["CONTRACT", "FLAG", "RULE", "entries_of", "flag", "flag_value", "settle"]
