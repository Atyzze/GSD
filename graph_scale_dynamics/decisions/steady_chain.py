from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

GATE = "no_steady_chain"
CONTRACT = "steady-chain-gate-1"
FROM_N, AT_N = 1024, 4096
GIANT_AT_LEAST = 0.5
UNDER_THE_CAP = 15.9
ABOVE_A_RING = 2.05
DEGREE_WITHIN = 0.03
REACH_GROWS = 1.35
SQUARES_A_NODE_AT_MOST = 1680.0
WHAT = ("a chain steady from N=1,024 to N=4,096: in one piece (its largest component half the nodes or more), under "
        "the degree cap (mean degree below 15.9), above a ring (mean degree above 2.05), its mean degree at 4,096 "
        "within 3% of that at 1,024, its reach at 4,096 at least 1.35 times that at 1,024, and at most 1,680 "
        "squares a node at both (the complete graph on 17 nodes, the most a graph inside the cap holds); moved "
        "when it is not a lattice start no edge of which the law changed")


def _cell(rows, n: int, columns: list, name: str):
    at = next((row for row in rows or () if int(row[0]) == int(n)), None)
    if at is None or name not in columns:
        return None
    value = at[columns.index(name)]
    return float(value) if isinstance(value, (int, float)) else None


def _start_degree(chain: str, n: int, references: dict) -> float | None:
    from graph_scale_dynamics.observability.starts_reading import NAMED
    family = NAMED.get(str(chain))
    ref = ((references or {}).get(family) or {}).get(int(n)) if family else None
    value = (((ref or {}).get("start") or {}).get("mean_degree") or {}).get("mean")
    return float(value) if isinstance(value, (int, float)) else None


def block(values: dict, columns: list, references: dict | None = None) -> dict | None:
    from graph_scale_dynamics.observability.starts_reading import table_references
    refs = table_references() if references is None else references
    columns = list(columns)
    steady, over, read = [], [], []
    for chain, rows in sorted((values or {}).items()):
        cells = {n: {name: _cell(rows, n, columns, name) for name in
                     ("mean_degree", "giant_fraction", "reach", "squares_per_node")} for n in (FROM_N, AT_N)}
        if any(cells[n]["mean_degree"] is None for n in (FROM_N, AT_N)):
            continue
        read.append(str(chain))
        if max(cells[n]["squares_per_node"] or 0.0 for n in (FROM_N, AT_N)) > SQUARES_A_NODE_AT_MOST:
            over.append(str(chain))
            continue
        low, high = cells[FROM_N], cells[AT_N]
        if None in (low["giant_fraction"], high["giant_fraction"], low["reach"], high["reach"]) or not low["reach"]:
            continue
        if min(low["giant_fraction"], high["giant_fraction"]) < GIANT_AT_LEAST:
            continue
        if max(low["mean_degree"], high["mean_degree"]) >= UNDER_THE_CAP:
            continue
        if min(low["mean_degree"], high["mean_degree"]) <= ABOVE_A_RING:
            continue
        if abs(high["mean_degree"] - low["mean_degree"]) > DEGREE_WITHIN * low["mean_degree"]:
            continue
        if high["reach"] / low["reach"] < REACH_GROWS:
            continue
        starts = [_start_degree(chain, n, refs) for n in (FROM_N, AT_N)]
        frozen = all(start is not None and abs(cells[n]["mean_degree"] - start) / 2.0 * n < 0.5
                     for n, start in zip((FROM_N, AT_N), starts, strict=True))
        steady.append([str(chain), "frozen" if frozen else "moved"])
    if not read:
        return None
    return {"contract": CONTRACT, "from_n": FROM_N, "at_n": AT_N, "read": read, "steady": steady,
            "moved": [name for name, how in steady if how == "moved"], "over_squares": over}


def _buys(decision: E.Decision) -> bool:
    return (decision.action in (E.RUN_NEXT, E.HOLD) and decision.next_n is not None and decision.at_n is not None
            and int(decision.next_n) > int(decision.at_n))


def gate(law: str, decision: E.Decision, starts_reading: dict | None, policy: E.Policy) -> E.Decision:
    if not policy.steady_chain_gate or not _buys(decision) or int(decision.at_n) != AT_N:
        return decision
    found = (starts_reading or {}).get("steady")
    if not isinstance(found, dict) or found.get("moved"):
        return decision
    frozen = [name for name, how in found.get("steady") or () if how == "frozen"]
    why = (f"no chain of the {len(found.get('read') or ())} read was steady and moved by the law from N={FROM_N:,} "
           f"to N={AT_N:,}" + (f" ({', '.join(frozen)} steady, no edge of it changed: a known answer)" if frozen else "")
           + (f"; {', '.join(found['over_squares'])} above {SQUARES_A_NODE_AT_MOST:,.0f} squares a node"
              if found.get("over_squares") else ""))
    facts_of_gate = dict(found, what=WHAT)
    refused = {"action": decision.action, "rule": decision.rule, "next_n": int(decision.next_n),
               "priority": decision.priority}
    share = policy.salt_share(GATE, AT_N)
    if policy.let_through(law, GATE, AT_N):
        how = E.let_through_text(GATE, share, policy) if policy.let_through_rule else f"{share:.0%} let through"
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=f"{decision.reason}; let through past {GATE}, which would park it: {why} ({how})",
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(decision.facts or {}, steady_chain=dict(facts_of_gate, salted=True),
                                     salted=list((decision.facts or {}).get("salted") or []) + [GATE]),
                          observations=decision.observations)
    kept = {key: value for key, value in (decision.facts or {}).items() if key != "lane"}
    return E.Decision(law=law, action=E.STOP, rule=GATE,
                      reason=(f"{why}: parked at the top of the base block with everything it measured kept "
                              f"({decision.rule}: {decision.reason})"),
                      at_n=AT_N, next_n=None, priority=None,
                      facts=dict(kept, steady_chain=facts_of_gate, refused=refused),
                      observations=decision.observations)


__all__ = ["AT_N", "CONTRACT", "FROM_N", "GATE", "SQUARES_A_NODE_AT_MOST", "WHAT", "block", "gate"]
