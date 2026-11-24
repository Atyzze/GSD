from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

NOT_PROMISING = "not_promising"
DIMENSION = "dimension_shows"
APART_BY_HISTORY = "starts_apart_by_history"
MERIT_RULES = frozenset({"starts_shape", "d_s_settled"})
SHAPED = ("one_space", "grows", "converts", "selects", "holds")
MAJORITY = 0.5


def _below(policy: E.Policy, n: int) -> int | None:
    return max((int(m) for m in policy.ladder() if int(m) < int(n)), default=None)


def class_at(reading: dict | None, n) -> str | None:
    if n is None:
        return None
    row = ((reading or {}).get("by_n") or {}).get(str(int(n)))
    return str(row[0]) if row and row[0] not in (None, "not_read") else None


def groups_at(reading: dict | None, n) -> list:
    row = ((reading or {}).get("by_n") or {}).get(str(int(n))) if n is not None else None
    return list(row[1]) if row and len(row) > 1 and isinstance(row[1], list) else []


def carriers(reading: dict | None, n) -> list[str]:
    if not reading or n is None or str((reading or {}).get("at_n")) != str(int(n)):
        return []
    holding = {name for name, (fate, _kept) in (reading.get("fates") or {}).items() if fate == "holds"}
    return [name for group in groups_at(reading, n) if holding & set(group) for name in group]


def chain_checks(rungs: list, policy: E.Policy) -> dict:
    rungs = sorted(rungs, key=lambda r: r.n)
    top = rungs[-1]
    fraction = top.small_world_fraction
    found = E.signals(rungs, policy)
    valid = (top.valid_fractions or {}).get("d_V")
    checks = {"not_small_world": {"passes": fraction is not None and float(fraction) < MAJORITY,
                                  "small_world_fraction": fraction},
              "d_s_settled": {"passes": bool(found["d_s_settled"]), "step": found["d_s_step"],
                              "judged_by": found.get("d_s_settled_by")},
              "d_V_valid": {"passes": valid is not None and float(valid) > MAJORITY, "valid_fraction": valid}}
    return {"passes": all(check["passes"] for check in checks.values()), "checks": checks}


def promising(rungs: list, policy: E.Policy, starts_reading: dict | None = None, chains: dict | None = None) -> dict:
    rungs = sorted(rungs, key=lambda r: r.n)
    top = rungs[-1]
    below = _below(policy, int(top.n))
    if policy.every_chain:
        here, there = class_at(starts_reading, top.n), class_at(starts_reading, below)
        shaped = {"passes": here in SHAPED and there in SHAPED, "classes": {str(int(top.n)): here, str(below): there}}
        own = dict(chains or {}, empty=rungs) if chains else {"empty": rungs}
        read = {name: chain_checks(own[name], policy) for name in carriers(starts_reading, top.n)
                if own.get(name) and int(sorted(own[name], key=lambda r: r.n)[-1].n) == int(top.n)}
        passed = [name for name, reading in read.items() if reading["passes"]]
        return {"passes": bool(shaped["passes"] and passed), "at_n": int(top.n),
                "checks": {"shaped": shaped, "a_carrier_is_promising": {"passes": bool(passed)}},
                "chains": read, "passed_by": passed}
    head = rungs[:-2] if E.signals(rungs, policy).get("d_s_across") else rungs[:-1]
    before = E.signals(head, policy)["d_s_settled"] if len(head) >= 2 else False
    checks = {"shaped": {"passes": bool(before), "not_read": "a campaign decided by its chain from empty reads no five "
                                                              "starts; d_s settled at the step before instead"},
              **chain_checks(rungs, policy)["checks"]}
    return {"passes": all(check["passes"] for check in checks.values()), "at_n": int(top.n), "checks": checks}


_FAILED = {"shaped": "its starts are not shaped at both of its top two rungs",
           "a_carrier_is_promising": "no chain that carries its shape is promising on its own rungs",
           "not_small_world": "a majority of its seeds are not shown to be other than small worlds",
           "d_s_settled": "its d_s step did not settle", "d_V_valid": "d_V is not read by a majority of its seeds"}


def bar(law: str, decision: E.Decision, rungs: list, policy: E.Policy, starts_reading: dict | None = None,
        chains: dict | None = None) -> E.Decision:
    if (not getattr(policy, "promising_bar", True)
            or decision.action not in (E.RUN_NEXT, E.HOLD) or decision.next_n is None
            or int(decision.next_n) < int(policy.promising_from_n) or not rungs
            or (decision.at_n is not None and int(decision.next_n) <= int(decision.at_n))):
        return decision
    facts = decision.facts or {}
    if DIMENSION in (decision.rule, facts.get("starts_bought")):
        return E.Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason,
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(facts, promising={"passes": True, "by": "the dimension test (732)"}),
                          observations=decision.observations)
    reading = promising(rungs, policy, starts_reading, chains)
    salted = bool(decision.rule == "salted" or facts.get("salted") or (facts.get("gate") or {}).get("salted"))
    if salted and policy.let_through_rule:
        return E.Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason,
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(facts, promising=dict(reading, let_through=True)),
                          observations=decision.observations)
    if salted:
        reading = dict(reading, passes=False, salted=True)
    if reading["passes"]:
        return E.Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason,
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(facts, promising=reading), observations=decision.observations)
    why = ["salted: no salt buys a rung from here"] if salted else []
    why += [_FAILED[name] for name, check in reading["checks"].items() if not check["passes"]]
    kept = {key: value for key, value in facts.items() if key != "lane"}
    parked = E.Decision(law=law, action=E.STOP, rule=NOT_PROMISING,
                        reason=(f"N={int(decision.next_n):,} is bought only by a promising law (629): "
                                + "; ".join(why)
                                + f"; parked with everything it measured kept ({decision.rule}: {decision.reason})"),
                        at_n=decision.at_n, next_n=None, priority=None,
                        facts=dict(kept, promising=reading,
                                   refused={"action": decision.action, "rule": decision.rule,
                                            "next_n": int(decision.next_n), "priority": decision.priority}),
                        observations=decision.observations)
    if salted:
        return parked
    from graph_scale_dynamics.decisions.starts_rule import shown
    extended = shown(parked, starts_reading, policy, int(decision.next_n))
    if extended is parked and policy.let_through_rule and policy.let_through(law, NOT_PROMISING, decision.at_n):
        share = policy.salt_share(NOT_PROMISING, decision.at_n)
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=(f"{decision.reason}; {E.let_through_text(NOT_PROMISING, share, policy)}: "
                                  f"{parked.reason}"),
                          at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                          facts=dict(facts, promising=reading,
                                     salted=list(facts.get("salted") or []) + [NOT_PROMISING],
                                     salted_from={"rule": NOT_PROMISING, "reason": parked.reason}),
                          observations=decision.observations)
    if extended is parked or extended.action != E.RUN_NEXT or decision.action != E.HOLD:
        return extended
    lane = dict(facts.get("lane") or {}, tier=int(extended.facts["dimension"]["tier"]))
    return E.Decision(law=law, action=E.HOLD, rule=decision.rule, reason=f"{extended.reason}; {decision.reason}",
                      at_n=decision.at_n, next_n=decision.next_n, priority=None,
                      facts=dict(extended.facts, starts_bought=DIMENSION, lane=lane),
                      observations=decision.observations)


def bought_on_merit(rungs: list, policy: E.Policy, starts_reading: dict | None = None) -> str | None:
    rungs = sorted(rungs, key=lambda r: r.n)
    if len(rungs) < 2 or int(rungs[-1].n) <= int(policy.base_sizes[-1]):
        return None
    budgets = [int(seed.work_budget) for seed in rungs[-1].seeds if isinstance(getattr(seed, "work_budget", None), int)]
    if budgets and max(budgets) <= policy.work_budget(int(rungs[-1].n)):
        return None
    return _merit_rule(rungs, policy, starts_reading)


def _merit_rule(rungs: list, policy: E.Policy, starts_reading: dict | None) -> str | None:
    if policy.every_chain:
        return "starts_shape" if class_at(starts_reading, _below(policy, int(rungs[-1].n))) in SHAPED else None
    return "d_s_settled" if E.signals(rungs[:-1], policy)["d_s_settled"] else None


def complete_budget(law: str, decision: E.Decision, rungs: list, policy: E.Policy,
                    starts_reading: dict | None = None) -> E.Decision:
    if (decision.action != E.RUN_NEXT or decision.rule != "complete_rung"
            or bought_on_merit(rungs, policy, starts_reading) is None):
        return decision
    return E.Decision(law=law, action=decision.action, rule=decision.rule, reason=decision.reason, at_n=decision.at_n,
                      next_n=decision.next_n, priority=decision.priority,
                      facts=dict(decision.facts or {}, budget_scale=float(policy.merit_budget_scale)),
                      observations=decision.observations)


def budget_scale(decision: E.Decision, policy: E.Policy) -> float:
    if decision.action != E.RUN_NEXT or decision.next_n is None:
        return 1.0
    if decision.rule == "complete_rung":
        return float((decision.facts or {}).get("budget_scale") or 1.0)
    if decision.rule == "longer_chain":
        return float(policy.longer_chain_budget_scale)
    if (decision.rule in MERIT_RULES and decision.priority == 1
            and int(decision.next_n) > int(policy.base_sizes[-1])):
        return float(policy.merit_budget_scale)
    return 1.0


def apart_history(reading: dict, policy: E.Policy, at_n: int) -> tuple[str, str] | None:
    below = _below(policy, int(at_n))
    before = class_at(reading, below)
    groups = groups_at(reading, at_n)
    if before == "forgets":
        return "park", f"every start ended alike at N={below:,}"
    if len(groups) == 2:
        return "park", f"its starts fell in two groups at N={int(at_n):,}"
    if before == "selects":
        return "first", f"a start selected a shape at N={below:,}"
    return None


def apart_looks(reading: dict, policy: E.Policy, upto: int) -> int:
    read = {int(n): str(row[0]) for n, row in ((reading or {}).get("by_n") or {}).items()
            if row and row[0] not in (None, "not_read")}
    looks = 0
    for n in sorted((int(m) for m in policy.ladder() if int(policy.base_sizes[-1]) <= int(m) <= int(upto)),
                    reverse=True):
        label = read.get(n)
        if label is None:
            below = max((m for m in read if m < n), default=None)
            label = "unread after apart" if below is not None and read[below] == "remembers" else None
            if label is None:
                break
            looks += 1
            continue
        if label != "remembers":
            break
        looks += 1
    return looks


__all__ = ["APART_BY_HISTORY", "MERIT_RULES", "NOT_PROMISING", "apart_history", "apart_looks", "bar",
           "bought_on_merit", "budget_scale", "carriers", "chain_checks", "class_at", "complete_budget", "promising"]
