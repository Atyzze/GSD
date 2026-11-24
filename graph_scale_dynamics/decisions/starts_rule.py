from __future__ import annotations

from graph_scale_dynamics.decisions import engine as E

RULE_CONTRACT = "gsd-starts-depth-1"
SHAPED = ("one_space", "grows", "converts", "selects", "holds")
SHAPE, APART = "starts_shape", "starts_apart"
ALIKE, APART_TWICE = "starts_alike", "starts_apart_twice"
APART_BY_HISTORY = "starts_apart_by_history"
SHAPE_UNREAD = "starts_shape_unread"
DIMENSION = "dimension_shows"
PARKS = (ALIKE, APART_TWICE, APART_BY_HISTORY, SHAPE_UNREAD)
KEPT_SHAPE, KEPT_SHAPE_TIER = "kept_shape", 3
APART_LOOKS = 2
D_S_DEPTH = frozenset({"d_s_settled", "second_rung", "reading_lost", "no_reading", "unsettled_twice", "no_second_rung",
                       "unsettled", "no_plateau", "deep_lane_full"})
REPLACED_FACTS = frozenset({"earned_by", "salted_from", "salt_spent", "gate", "lane", "starts_reading", "d_s"})


def _sizes(reading: dict, policy: E.Policy) -> list[tuple[int, str]]:
    base_end = int(policy.base_sizes[-1])
    return sorted((int(n), row[0]) for n, row in (reading.get("by_n") or {}).items()
                  if int(n) >= base_end and row and row[0] != "not_read")


def _park_at(reading: dict, policy: E.Policy, upto: int) -> str | None:
    read = [(n, label) for n, label in _sizes(reading, policy) if n <= upto]
    if not read:
        return None
    label = read[-1][1]
    if label == "forgets":
        return ALIKE
    if label == "remembers":
        from graph_scale_dynamics.decisions.depth import apart_looks
        return APART_TWICE if apart_looks(reading, policy, upto) >= APART_LOOKS else None
    return None


def shape_spent(reading: dict | None, policy: E.Policy, upto: int) -> int | None:
    if not reading:
        return None
    read = sorted((int(n), str(row[0])) for n, row in (reading.get("by_n") or {}).items()
                  if row and row[0] not in (None, "not_read") and int(n) <= int(upto))
    if not read or read[-1][1] not in SHAPED:
        return None
    at = read[-1][0]
    return at if int(upto) > max(at, int(policy.base_sizes[-1])) else None


def _unread_between(policy: E.Policy, low: int, high: int) -> list[int]:
    return [int(n) for n in policy.ladder() if int(low) < int(n) <= int(high)]


def _would_park(chosen: E.Decision, reading: dict | None, policy: E.Policy) -> bool:
    if (chosen.rule != "longer_chain" or not policy.every_chain or chosen.at_n is None
            or int(chosen.at_n) < int(policy.base_sizes[-1]) or not reading or not reading.get("references")
            or reading.get("class") in (None, "not_read")):
        return False
    label = reading["class"]
    if label == "forgets" or (label == "remembers" and _park_at(reading, policy, int(chosen.at_n)) is not None):
        return True
    if label == "remembers":
        from graph_scale_dynamics.decisions.depth import apart_history
        history = apart_history(reading, policy, int(reading.get("at_n") or chosen.at_n))
        return bool(history and history[0] == "park")
    return False


def applies(chosen: E.Decision, policy: E.Policy) -> bool:
    if not policy.every_chain or chosen.at_n is None or int(chosen.at_n) < int(policy.base_sizes[-1]):
        return False
    if chosen.rule == "salted":
        return ((chosen.facts or {}).get("salted_from") or {}).get("rule") in D_S_DEPTH
    return chosen.rule in D_S_DEPTH


def decide(law: str, chosen: E.Decision, reading: dict | None, policy: E.Policy, chain_rungs, *,
           gate: dict | None = None, standing: dict | None = None, deep_lane_in_flight=None) -> E.Decision:
    skipped = _would_park(chosen, reading, policy)
    if not applies(chosen, policy) and not skipped:
        return chosen
    d_s = {"action": chosen.action, "rule": chosen.rule, "reason": chosen.reason, "next_n": chosen.next_n}
    if not reading or reading.get("class") in (None, "not_read") or not reading.get("references"):
        missing = (reading or {}).get("unreferenced") or {}
        why = ("no size from 1,024 read by two chains or more" if reading and reading.get("references")
               else (f"no reference for {', '.join(missing.get('lattices') or [])} at N={int(missing['n']):,} "
                     "(649): the class there cannot tell a shape from none") if missing.get("n")
               else "the lattices' references are not this tree's" if reading else "no reading of the starts")
        return E.Decision(law=law, action=chosen.action, rule=chosen.rule, reason=chosen.reason, at_n=chosen.at_n,
                          next_n=chosen.next_n, priority=chosen.priority,
                          facts=dict(chosen.facts or {}, starts_reading={"decided": False, "why": why}),
                          observations=chosen.observations)
    top = int(chosen.at_n)
    following = next((n for n in policy.ladder() if n > top), None)
    label, at_n = reading["class"], reading.get("at_n")
    seen = {"decided": True, "class": label, "at_n": at_n, "classes": {n: row[0] for n, row in
                                                                      (reading.get("by_n") or {}).items()},
            "fates": reading.get("fates") or {}, "trend": reading.get("trend")}
    keep = {key: value for key, value in (chosen.facts or {}).items() if key not in REPLACED_FACTS}
    verdicts = [gate for gate in keep.pop("salted", None) or [] if gate not in D_S_DEPTH]
    if verdicts:
        keep["salted"] = verdicts
    facts = dict(keep, starts_reading=seen, d_s=d_s)
    if skipped:
        facts["longer_chain_skipped"] = {"why": "the starts park it (629)", "d_s_refusal": keep.get("d_s_refusal")}
    where = f"the starts at N={int(at_n):,}" if at_n else "the starts"
    if following is None:
        return E.Decision(law=law, action=E.DONE, rule="ladder_complete", reason=f"N={top} is the last declared rung",
                          at_n=top, next_n=None, facts=facts, observations=chosen.observations)
    held = [name for name, (fate, _kept) in in_start_order(reading.get("fates") or {}) if fate == "holds"]
    if label not in SHAPED and label not in ("forgets", "remembers"):
        return E.Decision(law=law, action=chosen.action, rule=chosen.rule, reason=chosen.reason, at_n=chosen.at_n,
                          next_n=chosen.next_n, priority=chosen.priority,
                          facts=dict(chosen.facts or {}, starts_reading={"decided": False,
                                                                          "why": f"a class the rule does not read: {label}"}),
                          observations=chosen.observations)
    spent = shape_spent(reading, policy, top) if label in SHAPED else None
    if label in SHAPED and spent is None:
        decision = E.Decision(law=law, action=E.RUN_NEXT, rule=SHAPE,
                              reason=(f"{where}: {_name(label)} ({', '.join(held) or 'none'} holding): the next size, "
                                      f"to see whether it holds"),
                              at_n=top, next_n=following, priority=1, facts=facts, observations=chosen.observations)
    elif label in SHAPED:
        unread = _unread_between(policy, max(spent, int(policy.base_sizes[-1])), top)
        facts["shape_unread"] = {"read_at": spent, "unread": unread}
        reason = (f"{where}: {_name(label)}, and its starts were not read at "
                  + ", ".join(f"N={n:,}" for n in unread)
                  + ": the shape's one size is spent without a reading, parked with everything it measured kept "
                  f"(631) (d_s's rule: {chosen.rule})")
        decision = _shown_or_salted(law, E.Decision(law=law, action=E.STOP, rule=SHAPE_UNREAD, reason=reason,
                                                    at_n=top, next_n=None, facts=facts,
                                                    observations=chosen.observations),
                                    reading, policy, following, deep_lane_in_flight)
    else:
        park = _park_at(reading, policy, top)
        history = None
        if park is None and label == "remembers":
            from graph_scale_dynamics.decisions.depth import apart_history
            history = apart_history(reading, policy, int(at_n or top))
            if history:
                facts["history"] = {"says": history[0], "why": history[1]}
        if park is None and label == "remembers" and not (history and history[0] == "park"):
            first = bool(history and history[0] == "first")
            decision = E.Decision(law=law, action=E.RUN_NEXT, rule=APART,
                                  reason=(f"{where}: the starts end apart, no shape held: the next size once, the "
                                          f"look before a park (k = {APART_LOOKS})"
                                          + (f"; {history[1]}, so first (629)" if first else "")),
                                  at_n=top, next_n=following, priority=1 if first else 2, facts=facts,
                                  observations=chosen.observations)
        else:
            park = park or (APART_BY_HISTORY if history else ALIKE)
            reason = (f"{where}: every start ends alike, no shape held: parked with everything it measured kept "
                      if park == ALIKE else
                      f"{where}: the starts apart with no shape held, and {history[1]}: such a history "
                      "gets no look at the next size (629): parked with everything it measured kept "
                      if park == APART_BY_HISTORY else
                      f"{where}: the starts apart with no shape held at {APART_LOOKS} sizes in a row: parked with "
                      "everything it measured kept ")
            decision = _shown_or_salted(law, E.Decision(law=law, action=E.STOP, rule=park,
                                                        reason=reason + f"(d_s's rule: {chosen.rule})", at_n=top,
                                                        next_n=None, facts=facts, observations=chosen.observations),
                                        reading, policy, following, deep_lane_in_flight)
    decision = _lane(decision, policy, deep_lane_in_flight)
    decision = _gated(law, decision, policy, chain_rungs, gate, first=held)
    return E._with_lane(decision, policy, standing)


def _gated(law: str, decision: E.Decision, policy: E.Policy, chain_rungs, gate: dict | None,
           first=()) -> E.Decision:
    chains = chain_rungs if isinstance(chain_rungs, dict) else {"empty": chain_rungs}
    order = [name for name in first if name in chains] + [name for name in chains if name not in first]
    refused = followed = None
    for name in order:
        result = E._gate(law, sorted(chains[name] or (), key=lambda r: r.n), policy, decision, gate or {})
        if result.action == E.STOP and result.rule in E.GATE_RULES:
            refused = refused or (name, result)
            continue
        if result.rule in ("gate_audit", "plateau_follow"):
            followed = followed or (name, result)
            continue
        return _read_on(result, name, len(chains))
    if followed:
        return _read_on(followed[1], followed[0], len(chains))
    return _read_on(refused[1], refused[0], len(chains)) if refused else decision


def _read_on(decision: E.Decision, name: str, chains: int) -> E.Decision:
    if chains < 2 or not isinstance((decision.facts or {}).get("gate"), dict):
        return decision
    return E.Decision(law=decision.law, action=decision.action, rule=decision.rule, reason=decision.reason,
                      at_n=decision.at_n, next_n=decision.next_n, priority=decision.priority,
                      facts=dict(decision.facts, gate=dict(decision.facts["gate"], chain=name)),
                      observations=decision.observations)


def _in_flight(policy: E.Policy, following: int, deep_lane_in_flight=None):
    return E.lane_in_flight(policy, following, deep_lane_in_flight)


def _lane(decision: E.Decision, policy: E.Policy, deep_lane_in_flight=None) -> E.Decision:
    if decision.action != E.RUN_NEXT or decision.next_n is None or int(decision.next_n) < int(policy.plateau_from_n):
        return decision
    following = int(decision.next_n)
    in_flight = _in_flight(policy, following, deep_lane_in_flight)
    if in_flight is None or in_flight < policy.deep_lane_width(following):
        return decision
    return E.Decision(law=decision.law, action=E.HOLD, rule="deep_lane_full",
                      reason=(f"{decision.reason}; N={following} has {in_flight} laws in flight, the most it takes at "
                              "once; this law waits, best law score first"),
                      at_n=decision.at_n, next_n=following, priority=None,
                      facts=dict(decision.facts, starts_bought=decision.rule), observations=decision.observations)


def _name(label: str) -> str:
    from graph_scale_dynamics.observability.starts_reading import CLASS_NAMES
    return CLASS_NAMES.get(label, label)


def in_start_order(chains: dict) -> list:
    from graph_scale_dynamics.research.dimension_rule import GROWN, LATTICES
    order = list(GROWN) + list(LATTICES)
    return sorted(chains.items(), key=lambda item: (order.index(item[0]) if item[0] in order else len(order), item[0]))


def shown(decision: E.Decision, reading: dict | None, policy: E.Policy, following: int | None) -> E.Decision:
    found = (reading or {}).get("dimension") or {}
    tier = found.get("tier")
    if (not policy.dimension_extends or not tier or following is None or decision.action != E.STOP
            or decision.rule not in PARKS + ("not_promising",)):
        return decision
    chains = found.get("chains") or {}
    read = ", ".join(f"{name} d {float(c['d']):.2f} ({c['kind'].replace('_', ' ')}"
                     + ("; a line" if c.get("line") else "; beyond what the test was checked on"
                        if c.get("beyond_checked") else "") + ")" for name, c in in_start_order(chains))
    facts = dict(decision.facts or {}, dimension=found,
                 overrode={"rule": decision.rule, "reason": decision.reason, "action": decision.action})
    if int(tier) == KEPT_SHAPE_TIER and policy.kept_shape_park:
        why = (f"the dimension test reads only lattice starts that kept their shape and their own d ({read}; 732, "
               f"tier {int(tier)})")
        if not policy.let_through(decision.law, KEPT_SHAPE, decision.at_n):
            kept = {key: value for key, value in (decision.facts or {}).items() if key != "lane"}
            return E.Decision(law=decision.law, action=E.STOP, rule=KEPT_SHAPE,
                              reason=(f"kept shape: {why}; parked with everything it measured kept, a class to "
                                      f"extend on its own ({decision.rule}: {decision.reason})"),
                              at_n=decision.at_n, next_n=None, priority=None,
                              facts=dict(kept, dimension=found, kept_shape={"tier": int(tier),
                                                                             "parked_over": decision.rule}),
                              observations=decision.observations)
        share = policy.salt_share(KEPT_SHAPE, decision.at_n)
        facts = dict(facts, salted=list(facts.get("salted") or []) + [KEPT_SHAPE],
                     salted_from={"rule": KEPT_SHAPE, "reason": why})
        return E.Decision(law=decision.law, action=E.RUN_NEXT, rule=DIMENSION,
                          reason=(f"the dimension test reads {read} (732, tier {int(tier)}); "
                                  f"{E.let_through_text(KEPT_SHAPE, share, policy)}: {why}"),
                          at_n=decision.at_n, next_n=following, priority=int(tier), facts=facts,
                          observations=decision.observations)
    return E.Decision(law=decision.law, action=E.RUN_NEXT, rule=DIMENSION,
                      reason=(f"the dimension test reads {read} (732, tier {int(tier)}): the next size, where the "
                              f"starts' rule or the depth bar parks it ({decision.rule})"),
                      at_n=decision.at_n, next_n=following, priority=int(tier), facts=facts,
                      observations=decision.observations)


def _shown_or_salted(law: str, decision: E.Decision, reading: dict, policy: E.Policy, following: int,
                     deep_lane_in_flight=None) -> E.Decision:
    extended = shown(decision, reading, policy, following)
    if extended is not decision:
        return extended
    return _salted(law, decision, reading, policy, following, deep_lane_in_flight)


def _salted(law: str, decision: E.Decision, reading: dict, policy: E.Policy, following: int,
            deep_lane_in_flight=None) -> E.Decision:
    gate = decision.rule
    share = policy.salt_share(gate, decision.at_n)
    if not policy.let_through(law, gate, decision.at_n):
        return decision
    if policy.let_through_rule:
        fired_below = False
    elif gate == SHAPE_UNREAD:
        rung_below = max((int(n) for n in policy.ladder() if int(n) < int(decision.at_n)), default=None)
        below = [rung_below] if rung_below is not None and shape_spent(reading, policy, rung_below) is not None else []
        fired_below = bool(below)
    else:
        below = [n for n, _label in _sizes(reading, policy) if n < int(decision.at_n)]
        fired_below = bool(below) and _park_at(reading, policy, below[-1]) == gate
    if fired_below:
        spent = {"gate": gate, "salted_at": int(below[-1]), "held_at": int(decision.at_n)}
        return E.Decision(law=law, action=decision.action, rule=decision.rule,
                          reason=f"{decision.reason}; {E._spent_text(spent)}", at_n=decision.at_n,
                          next_n=decision.next_n, priority=decision.priority,
                          facts=dict(decision.facts, salt_spent=spent), observations=decision.observations)
    facts = dict(decision.facts, salted=list(decision.facts.get("salted") or []) + [gate],
                 salted_from={"rule": gate, "reason": decision.reason})
    in_flight = _in_flight(policy, following, deep_lane_in_flight)
    if in_flight is not None and in_flight >= policy.deep_lane_width(following):
        return E.Decision(law=law, action=E.HOLD, rule="deep_lane_full",
                          reason=(f"salted past {gate}, and N={following} has {in_flight} laws in flight, the most it "
                                  "takes at once; this law waits, best law score first"),
                          at_n=decision.at_n, next_n=following, priority=None, facts=facts,
                          observations=decision.observations)
    return E.Decision(law=law, action=E.RUN_NEXT, rule="salted",
                      reason=((f"{E.let_through_text(gate, share, policy)}; {gate}: {decision.reason}")
                              if policy.let_through_rule else
                              (f"salted past {gate}: {share:.0%} of the laws it would park have the next size, fixed "
                               f"by identity, so what the park costs is measured; {gate}: {decision.reason}")),
                      at_n=decision.at_n, next_n=following, priority=2, facts=facts,
                      observations=decision.observations)


__all__ = ["ALIKE", "APART", "APART_BY_HISTORY", "APART_TWICE", "DIMENSION", "D_S_DEPTH", "KEPT_SHAPE", "PARKS", "SHAPE",
           "SHAPED", "SHAPE_UNREAD", "applies", "decide", "shape_spent", "shown"]
