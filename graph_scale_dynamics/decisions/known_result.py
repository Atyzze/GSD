from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

GATE = "repeats_a_known_result"
CONTRACT = "gsd-seen-enough-1"
PROBES = ("d_V", "d_s")


def chain_word(rung, policy) -> str:
    degree = rung.mean_degree
    if degree is None:
        return "unread"
    if float(degree) <= float(policy.empty_mean_degree):
        return "empty"
    if float(degree) >= float(policy.dense_cap):
        return "dense"
    connected = rung.connected_fraction
    if connected is not None and float(connected) < float(policy.connectivity_floor):
        return "dust"
    value = next((entry[0] for probe in PROBES for entry in [(rung.probes or {}).get(probe)]
                  if entry and entry[0] is not None), None)
    k = f"k{round(float(degree))}"
    return f"{k} d{round(float(value) * 2) / 2:g}" if value is not None else f"{k} unread"


def signature(chains: dict, starts_reading: dict | None, policy, at_n: int) -> str:
    fates = (starts_reading or {}).get("fates") or {}
    words = []
    for name, rungs in (chains or {}).items():
        here = [rung for rung in rungs or () if int(rung.n) == int(at_n)]
        word = chain_word(here[-1], policy) if here else "-"
        fate = (fates.get(name) or [None])[0]
        words.append(f"{name}:{word}" + (f" {fate}" if fate else ""))
    return "|".join(words)


def gate(law: str, decision: E.Decision, chains: dict, starts_reading: dict | None, policy) -> E.Decision:
    if not getattr(policy, "let_through_rule", "") or decision.at_n is None:
        return decision
    at_n = int(decision.at_n)
    if at_n < policy.known_result_size():
        return decision
    found = signature(chains, starts_reading, policy, at_n)
    facts = dict(decision.facts or {}, signature=found)
    passes = (decision.action == E.RUN_NEXT and decision.next_n is not None and int(decision.next_n) > at_n
              and not facts.get("salted"))
    seen = {(int(n), str(s)) for n, s in (policy.known_results or ())}
    if not passes or (at_n, found) not in seen or not int(policy.known_result_after or 0):
        return E.Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason,
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority, facts=facts,
                          observations=decision.observations)
    why = (f"its chains repeat a result {int(policy.known_result_after)} laws already reached at N={at_n:,} and kept "
           f"one size up ({found})")
    share = policy.salt_share(GATE, at_n)
    if policy.let_through(law, GATE, at_n):
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=f"{decision.reason}; {E.let_through_text(GATE, share, policy)}: {why}",
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(facts, salted=[GATE], salted_from={"rule": GATE, "reason": why}),
                          observations=decision.observations)
    kept = {key: value for key, value in facts.items() if key != "lane"}
    return E.Decision(law=law, action=E.STOP, rule=GATE,
                      reason=f"repeats a known result: {why}; parked with everything it measured kept ({decision.rule})",
                      at_n=decision.at_n, next_n=None, priority=None,
                      facts=dict(kept, repeats_a_known_result={"contract": CONTRACT, "signature": found},
                                 refused={"action": decision.action, "rule": decision.rule,
                                          "next_n": int(decision.next_n), "priority": decision.priority}),
                      observations=decision.observations)


__all__ = ["CONTRACT", "GATE", "chain_word", "gate", "signature"]
