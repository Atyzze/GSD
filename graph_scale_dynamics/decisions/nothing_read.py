from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

GATE = "nothing_read"
CONTRACT_PIECES = "nothing-read-gate-2"
PIECE_FROM_N = 4096
PIECE_AT_LEAST = 4096


def piece_nodes(n: int, policy: E.Policy | None = None) -> float:
    share = float(getattr(policy, "nothing_read_piece_share", 0.0) or 0.0)
    return min(float(PIECE_AT_LEAST), share * int(n)) if share > 0.0 else float(PIECE_AT_LEAST)


def piece_holds(rung: E.Rung, policy: E.Policy | None = None) -> bool:
    if int(rung.n) < PIECE_FROM_N:
        return False
    giant = rung.connected_fraction
    return giant is None or float(giant) * int(rung.n) >= piece_nodes(int(rung.n), policy) * (1.0 - 1e-9)


def read_on_a_piece(rung: E.Rung, policy: E.Policy | None = None) -> set:
    if not piece_holds(rung, policy):
        return set()
    return {str(probe) for probe, share in (rung.valid_fractions or {}).items() if share and float(share) > 0.0}


def readings(chains: dict, policy: E.Policy, upto: int) -> dict:
    out = {}
    for name, rungs in (chains or {}).items():
        found = set()
        for rung in rungs or ():
            if not int(policy.nothing_read_from_n) <= int(rung.n) <= int(upto):
                continue
            found |= {(int(rung.n), str(probe)) for probe, entry in (rung.probes or {}).items()
                      if entry and entry[0] is not None}
            found |= {(int(rung.n), probe) for probe in read_on_a_piece(rung, policy)}
        out[str(name)] = sorted(found)
    return out


def _buys(decision: E.Decision) -> bool:
    return (decision.action in (E.RUN_NEXT, E.HOLD) and decision.next_n is not None and decision.at_n is not None
            and int(decision.next_n) > int(decision.at_n))


def _sizes(chains: dict, upto: int) -> list[int]:
    return sorted({int(rung.n) for rungs in (chains or {}).values() for rung in rungs or () if int(rung.n) <= upto})


def gate(law: str, decision: E.Decision, chains: dict, policy: E.Policy) -> E.Decision:
    if not policy.nothing_read_gate or not _buys(decision):
        return decision
    top_of_base = int(policy.base_sizes[-1])
    at_n = int(decision.at_n)
    if at_n < top_of_base:
        return decision
    read = readings(chains, policy, at_n)
    if any(read.values()):
        return decision
    sizes = [n for n in _sizes(chains, at_n) if n >= int(policy.nothing_read_from_n)]
    piece_share = float(policy.nothing_read_piece_share or 0.0)
    facts_of_gate = {"contract": CONTRACT_PIECES, "from_n": int(policy.nothing_read_from_n),
                     "at_n": at_n, "sizes": sizes, "chains": sorted(read),
                     **({"piece_share": piece_share} if piece_share > 0.0 else {})}
    refused = {"action": decision.action, "rule": decision.rule, "next_n": int(decision.next_n),
               "priority": decision.priority}
    where = f"N={int(policy.nothing_read_from_n):,} to N={at_n:,}"
    on_pieces = (f", nor on a piece of {PIECE_AT_LEAST:,} nodes or more from N={PIECE_FROM_N:,} as the score reads"
                 if piece_share <= 0.0 else
                 f", nor on a piece of {piece_share:g} of the graph or of {PIECE_AT_LEAST:,} nodes from "
                 f"N={PIECE_FROM_N:,}")
    why = (f"no chain of the {len(read)} read any probe at any size from {where}{on_pieces}: nothing a deeper rung "
           "could settle")
    kept = {key: value for key, value in (decision.facts or {}).items() if key != "lane"}
    if at_n > top_of_base and not policy.let_through_rule:
        below = max((n for n in sizes if n < at_n), default=top_of_base)
        spent = {"gate": GATE, "salted_at": int(below), "held_at": at_n}
        return E.Decision(law=law, action=E.STOP, rule=GATE,
                          reason=(f"{why}; let through past it at N={int(below):,} and reading nothing again at "
                                  f"N={at_n:,}: the let-through's one rung is spent; parked with everything it "
                                  f"measured kept ({decision.rule}: {decision.reason})"),
                          at_n=at_n, next_n=None, priority=None,
                          facts=dict(kept, nothing_read=dict(facts_of_gate, salt_spent=spent), salt_spent=spent,
                                     refused=refused),
                          observations=decision.observations)
    share = policy.salt_share(GATE, at_n)
    if policy.let_through(law, GATE, at_n):
        how = (E.let_through_text(GATE, share, policy) if policy.let_through_rule else
               f"{share:.0%} of the laws it would park go one rung on, fixed by identity, so what the gate costs is "
               "measured")
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=(f"{decision.reason}; let through past {GATE}, which would park it: {why} ({how})"),
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(decision.facts or {}, nothing_read=dict(facts_of_gate, salted=True),
                                     salted=list((decision.facts or {}).get("salted") or []) + [GATE]),
                          observations=decision.observations)
    return E.Decision(law=law, action=E.STOP, rule=GATE,
                      reason=(f"{why}; parked at the top of the base block with everything it measured kept "
                              f"({decision.rule}: {decision.reason})"),
                      at_n=at_n, next_n=None, priority=None,
                      facts=dict(kept, nothing_read=facts_of_gate, refused=refused),
                      observations=decision.observations)


__all__ = ["CONTRACT_PIECES", "GATE", "PIECE_AT_LEAST", "PIECE_FROM_N", "gate", "piece_holds", "piece_nodes",
           "read_on_a_piece", "readings"]
