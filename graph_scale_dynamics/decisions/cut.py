from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

GATE = "cut"
CONTRACT = "cut-gate-1"


def cut_seeds(rung: E.Rung | None) -> list[int]:
    return [index for index, seed in enumerate(getattr(rung, "seeds", None) or ())
            if seed.termination == E.BUDGET_TERMINATION]


LONGER_CHAIN = "longer_chain"


def _buys(decision: E.Decision) -> bool:
    if decision.action not in (E.RUN_NEXT, E.HOLD) or decision.next_n is None or decision.at_n is None:
        return False
    return int(decision.next_n) > int(decision.at_n) or decision.rule == LONGER_CHAIN


def gate(law: str, decision: E.Decision, rungs, policy: E.Policy) -> E.Decision:
    if not policy.cut_gate or not _buys(decision):
        return decision
    at_n = int(decision.at_n)
    rung = next((r for r in rungs or () if int(r.n) == at_n), None)
    cut = cut_seeds(rung)
    if not cut:
        return decision
    facts_of_gate = {"contract": CONTRACT, "at_n": at_n, "seeds": cut, "of": len(rung.seeds)}
    why = (f"{len(cut)} of its {len(rung.seeds)} seeds at N={at_n:,} ran out of their budget in work before they "
           "settled")
    if policy.let_through(law, GATE, at_n):
        share = policy.salt_share(GATE, at_n)
        how = (E.let_through_text(GATE, share, policy) if policy.let_through_rule else
               f"{share:.0%} of the laws it would park go one rung on, fixed by identity, so what the gate costs is "
               "measured")
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=f"{decision.reason}; let through past {GATE}, which would park it: {why} ({how})",
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(decision.facts or {}, cut=dict(facts_of_gate, salted=True),
                                     salted=list((decision.facts or {}).get("salted") or []) + [GATE]),
                          observations=decision.observations)
    kept = {key: value for key, value in (decision.facts or {}).items() if key != "lane"}
    refused = {"action": decision.action, "rule": decision.rule, "next_n": int(decision.next_n),
               "priority": decision.priority}
    return E.Decision(law=law, action=E.STOP, rule=GATE,
                      reason=(f"{why}; parked there with everything it measured kept "
                              f"({decision.rule}: {decision.reason})"),
                      at_n=at_n, next_n=None, priority=None,
                      facts=dict(kept, cut=facts_of_gate, refused=refused),
                      observations=decision.observations)


__all__ = ["CONTRACT", "GATE", "LONGER_CHAIN", "cut_seeds", "gate"]
