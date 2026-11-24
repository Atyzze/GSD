from __future__ import annotations

import re
from collections import Counter, defaultdict

CONTRACT = "gsd-starts-decided-1"
KINDS = ("climbs", "let_through", "holds", "parks", "stops", "ends", "not_recorded")
_PARK_NAMED = re.compile(r"^salted past (starts_alike|starts_apart_twice)")
_D_S_NAMED = re.compile(r"\(d_s's rule: ([a-z_]+)\)")
_BOUGHT = (("to see whether it holds", "starts_shape"), ("the look before a park", "starts_apart"))
_D_S_HOLDS = frozenset({"unsettled", "no_plateau", "deep_lane_full"})


def kind(action, rule, facts: dict | None = None) -> str:
    from graph_scale_dynamics.decisions.engine import DONE, HOLD, PARKING_RULES, STOP
    if not action and not rule:
        return "not_recorded"
    if rule in PARKING_RULES:
        return "parks"
    if action == STOP:
        return "stops"
    if action == DONE:
        return "ends"
    if rule in ("salted", "gate_audit") or ((facts or {}).get("salted_from") or {}).get("rule") in PARKING_RULES:
        return "let_through"
    if action == HOLD and rule != "deep_lane_full":
        return "holds"
    return "climbs"


def _d_s_action(rule: str) -> str:
    from graph_scale_dynamics.decisions.engine import HOLD, PARKING_RULES, RUN_NEXT, STOP
    return STOP if rule in PARKING_RULES else HOLD if rule in _D_S_HOLDS else RUN_NEXT


def facts_of(row: dict, from_rules: bool = False) -> dict:
    facts = row.get("facts")
    if not from_rules:
        return facts if isinstance(facts, dict) else {}
    from graph_scale_dynamics.decisions import starts_rule as FS
    rule, reason = str(row.get("rule") or ""), str(row.get("reason") or "")
    park = _PARK_NAMED.search(reason)
    if not (rule in (FS.SHAPE, FS.APART, *FS.PARKS) or reason.startswith("the starts") or park):
        return {}
    out: dict = {"starts_reading": {"decided": True, "class": None}}
    if park:
        out["salted_from"] = {"rule": park.group(1)}
    named = _D_S_NAMED.search(reason)
    if named:
        out["d_s"] = {"action": _d_s_action(named.group(1)), "rule": named.group(1)}
    bought = next((name for text, name in _BOUGHT if text in reason), None)
    if bought and rule != bought:
        out["starts_bought"] = bought
    return out


def _reading(facts: dict) -> dict | None:
    five = facts.get("starts_reading")
    return five if isinstance(five, dict) and "decided" in five else None


def _order(row: dict) -> str:
    return str(row.get("decision_id") or row.get("created_utc") or "")


def _a_size_later(later) -> str:
    from graph_scale_dynamics.decisions import starts_rule as FS
    if later is None:
        return "not yet"
    row, facts = later
    five = _reading(facts)
    if not five or not five.get("decided"):
        return "decided otherwise"
    bought = facts.get("starts_bought") or ((facts.get("gate") or {}).get("underlying") or {}).get("rule")
    if five.get("class") in FS.SHAPED or FS.SHAPE in (row.get("rule"), bought):
        return "a shape"
    mine = kind(row.get("action"), row.get("rule"), facts)
    if mine == "parks":
        return "parked again"
    if five.get("class") == "remembers" or FS.APART in (row.get("rule"), bought):
        return "apart: one more look"
    if mine == "let_through":
        return "let through again"
    return "decided otherwise"


def decided(decisions: dict | None, *, from_rules: bool = False) -> dict:
    from graph_scale_dynamics.decisions import starts_rule as FS
    from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT
    laws = {str(law): [(row, facts_of(row, from_rules)) for row in sorted(rows or [], key=_order)]
            for law, rows in (decisions or {}).items()}
    taken_at = [(_order(row), str(row.get("created_utc") or "")) for rows in laws.values() for row, facts in rows
                if _reading(facts) is not None]
    switch_at = min(taken_at)[0] if taken_at else None
    pairs, pair_laws, by_rules, not_taken = Counter(), defaultdict(set), Counter(), Counter()
    switch, switch_rules, unparked, parked = Counter(), Counter(), [], []
    let = {park: Counter() for park in FS.PARKS}
    otherwise = {park: Counter() for park in FS.PARKS}
    cost: dict = {park: [] for park in FS.PARKS}
    seen = set()
    for law, rows in laws.items():
        first = True
        for index, (row, facts) in enumerate(rows):
            five = _reading(facts)
            if five is None:
                continue
            if first:
                first = False
                before = rows[index - 1] if index else None
                if (before is not None and _reading(before[1]) is None and before[0].get("at_n") == row.get("at_n")
                        and _order(before[0]) < switch_at):
                    was = kind(before[0].get("action"), before[0].get("rule"), before[1])
                    now = kind(row.get("action"), row.get("rule"), facts)
                    switch[(was, now)] += 1
                    switch_rules[(str(before[0].get("rule")), str(row.get("rule")))] += 1
                    if was == "parks" and now != "parks":
                        unparked.append(law)
                    elif was != "parks" and now == "parks":
                        parked.append(law)
            if not five.get("decided"):
                not_taken[str(five.get("why") or "not said")] += 1
                continue
            d_s = facts.get("d_s") if isinstance(facts.get("d_s"), dict) else {}
            pair = (kind(row.get("action"), row.get("rule"), facts), kind(d_s.get("action"), d_s.get("rule")))
            pairs[pair] += 1
            pair_laws[pair].add(law)
            by_rules[(str(row.get("rule")), str(d_s.get("rule") or "not recorded"))] += 1
            park = (facts.get("salted_from") or {}).get("rule")
            key = (law, park, row.get("at_n"))
            if park not in FS.PARKS or key in seen:
                continue
            seen.add(key)
            if row.get("action") not in (RUN_NEXT, HOLD):
                let[park]["refused by the structure gate"] += 1
                continue
            at = int(row.get("at_n") or 0)
            later = next((r for r in rows[index + 1:] if int(r[0].get("at_n") or 0) > at), None)
            outcome = _a_size_later(later)
            let[park][outcome] += 1
            if outcome == "a shape":
                cost[park].append(law)
            elif outcome == "decided otherwise":
                otherwise[park][str(later[0].get("rule"))] += 1
    whens = sorted(when for _key, when in taken_at if when)
    parked_over = set().union(*(pair_laws[("parks", other)] for other in ("climbs", "holds")))
    return _shaped(
        "report 10's rules and reasons" if from_rules else "the decisions' facts", whens, not_taken, pairs,
        Counter({pair: len(laws_of) for pair, laws_of in pair_laws.items() if laws_of}),
        len(set().union(*pair_laws.values())) if pair_laws else 0, sorted(parked_over),
        sorted(pair_laws[("climbs", "parks")]), by_rules, switch, switch_rules, sorted(unparked), sorted(parked),
        let, otherwise, cost)


def combined(sections: list[dict]) -> dict:
    from graph_scale_dynamics.decisions import starts_rule as FS
    parts = [part for part in sections or [] if isinstance(part, dict) and part.get("contract") == CONTRACT]
    pairs, pair_laws, by_rules, not_taken = Counter(), Counter(), Counter(), Counter()
    switch, switch_rules, lists = Counter(), Counter(), {}
    let = {park: Counter() for park in FS.PARKS}
    otherwise = {park: Counter() for park in FS.PARKS}
    cost: dict = {park: [] for park in FS.PARKS}
    for part in parts:
        for row in part.get("against_d_s") or []:
            pairs[(row["starts_reading"], row["d_s"])] += int(row["decisions"])
            pair_laws[(row["starts_reading"], row["d_s"])] += int(row["laws"])
        by_rules.update({(row["rule"], row["d_s"]): int(row["decisions"]) for row in part.get("by_rules") or []})
        not_taken.update(part.get("not_taken") or {})
        at = part.get("at_the_switch") or {}
        switch.update({(row["was"], row["now"]): int(row["laws"]) for row in at.get("kinds") or []})
        switch_rules.update({(row["was"], row["now"]): int(row["laws"]) for row in at.get("rules") or []})
        for key, values in (("parked_where_d_s_climbed", part.get("parked_where_d_s_climbed")),
                            ("climbed_where_d_s_parked", part.get("climbed_where_d_s_parked")),
                            ("unparked", at.get("unparked")), ("parked", at.get("parked"))):
            lists.setdefault(key, []).extend(values or [])
        for park in FS.PARKS:
            own = (part.get("let_through") or {}).get(park) or {}
            let[park].update(own.get("a_size_later") or {})
            otherwise[park].update(own.get("decided_otherwise") or {})
            cost[park].extend(own.get("a_shape") or [])
    whens = sorted(part[key] for part in parts for key in ("first_utc", "last_utc") if part.get(key))
    out = _shaped("; ".join(sorted({str(part.get("from")) for part in parts})), whens, not_taken, pairs, pair_laws,
                  sum(int(part.get("laws") or 0) for part in parts),
                  *(sorted(lists.get(key) or []) for key in ("parked_where_d_s_climbed", "climbed_where_d_s_parked")),
                  by_rules, switch, switch_rules, *(sorted(lists.get(key) or []) for key in ("unparked", "parked")),
                  let, otherwise, {park: sorted(laws) for park, laws in cost.items()})
    return dict(out, campaigns=len(parts))


def _shaped(source, whens, not_taken, pairs, pair_laws, laws, parked_over, climbed_over, by_rules, switch,
            switch_rules, unparked, parked, let, otherwise, cost) -> dict:
    from graph_scale_dynamics.decisions import starts_rule as FS
    rank = {name: index for index, name in enumerate(KINDS)}

    def by_kinds(counts):
        return sorted(counts.items(), key=lambda kv: (rank[kv[0][0]], rank[kv[0][1]]))

    return {
        "contract": CONTRACT, "from": source, "decisions": sum(pairs.values()), "laws": laws,
        "first_utc": whens[0] if whens else None, "last_utc": whens[-1] if whens else None,
        "not_taken": dict(not_taken.most_common()),
        "against_d_s": [{"starts_reading": mine, "d_s": theirs, "decisions": count, "laws": pair_laws[(mine, theirs)]}
                        for (mine, theirs), count in by_kinds(pairs)],
        "parked_where_d_s_climbed": parked_over, "climbed_where_d_s_parked": climbed_over,
        "by_rules": [{"rule": rule, "d_s": theirs, "decisions": count}
                     for (rule, theirs), count in sorted(by_rules.items(), key=lambda kv: (-kv[1], kv[0]))],
        "at_the_switch": {
            "laws": sum(switch.values()),
            "kinds": [{"was": was, "now": now, "laws": count} for (was, now), count in by_kinds(switch)],
            "rules": [{"was": was, "now": now, "laws": count}
                      for (was, now), count in sorted(switch_rules.items(), key=lambda kv: (-kv[1], kv[0]))],
            "unparked": unparked, "parked": parked},
        "let_through": {park: {"laws": sum(let[park].values()), "a_size_later": dict(let[park].most_common()),
                               "decided_otherwise": dict(otherwise[park].most_common()), "a_shape": sorted(cost[park])}
                        for park in FS.PARKS},
        "reading": ("every decision the starts took (facts.starts_reading.decided) against what d_s's rule would "
                    "have decided (facts.d_s), by kind (climbs: a size bought, run or waiting for its lane; "
                    "let_through: a park's or the structure gate's share that runs the next size anyway; holds: d_s's "
                    "holds; parks; stops: the structure gate's refusal or a verdict; ends: the ladder's end) and by "
                    "rule; not_taken: where they had the word and did not take it, by why; at_the_switch: each law "
                    "whose first decision by the starts was at the size of its decision before, which was taken "
                    "before they took any in this campaign (a hold or a park decided again when the rules changed); "
                    "let_through: each park's let-through laws by what their next decision at a larger size read "
                    "(a shape there is what the park would have cost)")}
