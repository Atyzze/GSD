from __future__ import annotations

from collections import Counter, defaultdict

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.structure_gate import FINITE

TREE_CONTRACT = "gsd-gate-tree-3"
STRUCTURE_GATES = frozenset({"no_finite_dimension", "no_giant_component"})
HELD, CHANGED, NOT_YET = "gate_held", "reading_changed", "no_next_rung_yet"
NEXT_RUNG_ORDER = (HELD, CHANGED, NOT_YET)
IN_PROGRESS_RULES = frozenset({"start", "complete_rung"})
SETTLED_LATER = "settled_d_s_later"
STILL_GOING = "still_going"
HELD_LATER = "held_later"
STOPPED_LATER = "stopped_later"
LADDER_COMPLETE = "ladder_complete"
STOPPED_SAME_RUNG = "stopped_at_the_same_rung"
HELD_SAME_RUNG = "held_at_the_same_rung"
WENT_ON = (SETTLED_LATER, STILL_GOING, HELD_LATER, STOPPED_LATER, LADDER_COMPLETE)
LATER_ORDER = WENT_ON + (STOPPED_SAME_RUNG, HELD_SAME_RUNG)
MISSED, CLEAN, OPEN, BOUGHT_NOTHING = "missed", "clean", "open", "bought_nothing"
UNTESTED = "ended_untested"
CHEAP, DEEP = "up to 4,096", "from 16,384"
DEEP_FROM = G.SALT_DEEP_FROM
CONFIRM_AFTER = {CHEAP: 1000, DEEP: 300}
SALT_WHILE_TESTING = {CHEAP: 0.5, DEEP: 0.1}
SALT_CONFIRMED = 0.01


def _final_by_rung(rows: list[dict]) -> dict[int, dict]:
    final: dict[int, dict] = {}
    for row in rows:
        n = row.get("at_n")
        if n is None or str(row.get("rule")) in IN_PROGRESS_RULES:
            continue
        final[int(n)] = row
    return dict(sorted(final.items()))


def _branch(row: dict) -> str:
    return {"run_next": "on", "hold": "held", "stop": "stopped", "done": "done"}.get(str(row.get("action")), "other")


def _settled(row: dict) -> bool:
    return (row.get("facts") or {}).get("d_s_settled") is True


def _later(final: dict[int, dict], n: int, latest: dict) -> str:
    here = _branch(final[n])
    if here == "stopped":
        return STOPPED_SAME_RUNG
    if here == "held":
        return HELD_SAME_RUNG
    if here == "done":
        return LADDER_COMPLETE
    if any(_settled(row) for m, row in final.items() if m > n):
        return SETTLED_LATER
    return {"stopped": STOPPED_LATER, "done": LADDER_COMPLETE, "held": HELD_LATER}.get(_branch(latest), STILL_GOING)


def _next_rung(final: dict[int, dict], n: int, gate: str) -> tuple[str, str | None]:
    later = [m for m in final if m > n]
    if not later:
        return NOT_YET, None
    row = final[min(later)]
    facts = row.get("facts") or {}
    spent = (facts.get("salt_spent") or {}).get("gate")
    held = spent == gate or str(row.get("rule")) == gate or gate in (facts.get("salted") or [])
    reading = (facts.get("gate") or {}).get("result") if gate in STRUCTURE_GATES else None
    return (HELD if held else CHANGED), (str(reading) if reading is not None else None)


def _ledger_outcome(final: dict[int, dict], n: int, latest: dict) -> str:
    tested = False
    for m, row in final.items():
        gate = (row.get("facts") or {}).get("gate") or {}
        if m > n and gate.get("result") == FINITE:
            return MISSED
        tested = tested or (m > n and gate.get("stage") == "full")
    if _branch(final[n]) == "stopped":
        return BOUGHT_NOTHING
    if _branch(latest) not in ("stopped", "done"):
        return OPEN
    return CLEAN if tested else UNTESTED


def ledger(entries: list[tuple[str, str]], cost: str) -> dict:
    ordered = sorted(entries)
    counts = Counter(end for _, end in ordered)
    last_miss = max((key for key, end in ordered if end == MISSED), default=None)
    clean_since = sum(1 for key, end in ordered if end == CLEAN and (last_miss is None or key > last_miss))
    confirmed = clean_since >= CONFIRM_AFTER[cost]
    return {"salted": len(ordered), CLEAN: counts.get(CLEAN, 0), MISSED: counts.get(MISSED, 0),
            OPEN: counts.get(OPEN, 0), BOUGHT_NOTHING: counts.get(BOUGHT_NOTHING, 0),
            UNTESTED: counts.get(UNTESTED, 0),
            "clean_since_last_miss": clean_since, "needed": CONFIRM_AFTER[cost],
            "label": "confirmed" if confirmed else "testing",
            "salt_under_554": SALT_CONFIRMED if confirmed else SALT_WHILE_TESTING[cost]}


def _settled_share(outcomes: Counter) -> float | None:
    return _share(outcomes.get(SETTLED_LATER, 0), sum(outcomes.get(key, 0) for key in WENT_ON))


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def build_gate_tree(decisions: dict[str, list[dict]], graphs: dict | None = None, *, policy=None) -> dict:
    rungs: dict[int, dict] = defaultdict(lambda: {"finished": 0, "on": Counter(), "held": Counter(),
                                                   "stopped": Counter(), "done": 0, "salted_past": Counter(),
                                                   "salt_spent": Counter(), "graphs": Counter()})
    withheld: dict[str, Counter] = defaultdict(Counter)
    through: dict[str, Counter] = defaultdict(Counter)
    after: dict[str, Counter] = defaultdict(Counter)
    unsalted: dict[int, Counter] = defaultdict(Counter)
    spent: dict[str, Counter] = defaultdict(Counter)
    next_rung: dict[str, Counter] = defaultdict(Counter)
    next_reading: dict[str, Counter] = defaultdict(Counter)
    salted_ends: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    laws = 0
    for law, rows in decisions.items():
        rows = sorted(rows or [], key=lambda r: str(r.get("decision_id") or ""))
        final = _final_by_rung(rows)
        if not final:
            continue
        laws += 1
        latest = rows[-1]
        seen_salted: set[str] = set()
        for n, row in final.items():
            entry = rungs[n]
            entry["finished"] += 1
            branch, rule = _branch(row), str(row.get("rule"))
            if graphs is not None:
                entry["graphs"][branch] += int(graphs.get((str(law), int(n))) or 0)
            if branch == "done":
                entry["done"] += 1
            elif branch in ("on", "held", "stopped"):
                entry[branch][rule] += 1
            spent_gate = ((row.get("facts") or {}).get("salt_spent") or {}).get("gate")
            below = max((m for m in final if m < n), default=None)
            salted_below = below is not None and rule in ((final[below].get("facts") or {}).get("salted") or [])
            if branch in ("held", "stopped"):
                if spent_gate == rule or salted_below:
                    spent[rule][n] += 1
                    entry["salt_spent"][rule] += 1
                else:
                    withheld[rule][n] += 1
            salted = list(dict.fromkeys(str(g) for g in (row.get("facts") or {}).get("salted") or []))
            for gate in salted:
                entry["salted_past"][gate] += 1
                if gate not in seen_salted:
                    seen_salted.add(gate)
                    through[gate][n] += 1
                    after[gate][_later(final, n, latest)] += 1
                    said, reading = _next_rung(final, n, gate)
                    next_rung[gate][said] += 1
                    salted_ends[gate][DEEP if n >= DEEP_FROM else CHEAP].append(
                        (str(row.get("decision_id") or ""), _ledger_outcome(final, n, latest)))
                    if gate in STRUCTURE_GATES and said != NOT_YET:
                        next_reading[gate][reading or "not read"] += 1
            if branch == "on" and not salted:
                unsalted[n][_later(final, n, latest)] += 1

    def matched_baseline(gate: str) -> float | None:
        expected = weight = 0.0
        for n, count in through[gate].items():
            share = _settled_share(unsalted[n])
            if share is not None:
                expected += count * share
                weight += count
        return round(expected / weight, 4) if weight else None

    known = [gate.name for gate in G.GATES]
    others = sorted((set(withheld) | set(through)) - set(known))
    gates = []
    for name in known + others:
        gate = G.BY_NAME.get(name)
        held_back, let = sum(withheld[name].values()), sum(through[name].values())
        record = {
            "gate": name, "stage": gate.stage if gate else "not in the tree", "reads": gate.reads if gate else "",
            "salted": bool(gate.salted) if gate else False,
            "withheld": held_back, "let_through": let, "share_let_through": _share(let, held_back + let),
            "by_rung": {str(n): {"withheld": withheld[name].get(n, 0), "let_through": through[name].get(n, 0)}
                        for n in sorted(set(withheld[name]) | set(through[name]))},
            "let_through_later": {key: after[name][key] for key in LATER_ORDER if after[name].get(key)},
            "went_on": sum(after[name].get(key, 0) for key in WENT_ON),
            "settled_later_share": _settled_share(after[name]),
            "unsalted_settled_later_share_at_the_same_rungs": matched_baseline(name),
            "salt_next_rung": {key: next_rung[name][key] for key in NEXT_RUNG_ORDER if next_rung[name].get(key)},
            "salt_spent": sum(spent[name].values()),
        }
        if name in STRUCTURE_GATES:
            record["salt_next_rung_reading"] = dict(next_reading[name].most_common())
        if salted_ends.get(name):
            record["salt_ledger"] = {cost: ledger(salted_ends[name][cost], cost) for cost in (CHEAP, DEEP)
                                     if salted_ends[name].get(cost)}
        if gate is not None and not gate.salted:
            record["why_not_salted"] = gate.why_not
        elif gate is not None and policy is not None:
            record["salt_share"] = {CHEAP: policy.salt_share(name, None), DEEP: policy.salt_share(name, DEEP_FROM)}
        gates.append(record)
    counted = graphs is not None
    in_progress: Counter = Counter()
    if counted:
        finished_at = {(str(law), n) for law, rows in decisions.items()
                       for n in _final_by_rung(sorted(rows or [], key=lambda r: str(r.get("decision_id") or "")))}
        for (law, n), count in graphs.items():
            if (str(law), int(n)) not in finished_at:
                in_progress[int(n)] += int(count)
    rung_rows = []
    for n in sorted(set(rungs) | set(in_progress)):
        e = rungs[n]
        row = {"n": n, "finished": e["finished"], "went_on": sum(e["on"].values()), "went_on_by": dict(e["on"]),
               "held": dict(e["held"]), "stopped": dict(e["stopped"]), "done": e["done"],
               "salted_past": dict(e["salted_past"]), "salt_spent": dict(e["salt_spent"])}
        if counted:
            row["graphs"] = sum(e["graphs"].values())
            row["graphs_by_branch"] = {key: e["graphs"][key] for key in ("on", "done", "held", "stopped")
                                       if e["graphs"].get(key)}
            row["graphs_in_progress"] = in_progress.get(n, 0)
        rung_rows.append(row)
    return {
        "contract": TREE_CONTRACT, "gates_contract": G.GATES_CONTRACT, "laws": laws,
        **({"graphs": sum(r["graphs"] + r["graphs_in_progress"] for r in rung_rows)} if counted else {}),
        "rungs": rung_rows,
        "gates": gates,
        "unsalted_later_by_rung": {str(n): {key: c[key] for key in LATER_ORDER if c.get(key)}
                                   for n, c in sorted(unsalted.items())},
        "reading": ("Each law's last decision at each rung it finished is where it went from there. A gate's "
                    "withheld and let-through laws are counted once each, at the first rung it happened; the "
                    "gate lets salt_share through (its let-through, called the salt until 600; 10% for a campaign "
                    "created before 554), so share_let_through far from it is about the let-through. Of the laws a "
                    "gate let through that went on from that rung, settled_later_share settled d_s at a later "
                    "rung; against unsalted_settled_later_share_at_the_same_rungs (the laws that went on by "
                    "their own reading from the same rungs, weighted alike) it is the gate's cost: close shares mean it "
                    "withholds laws as good as the ones that go on. Laws still going are right-censored, so both "
                    "shares grow while the campaign runs. A let-through buys one rung: salt_next_rung says "
                    "whether the gate fired again there (gate_held, and the law stopped: salt_spent) or its "
                    "reading changed; for the structure gate salt_next_rung_reading is its own reading at that "
                    "rung, which is its measure, since a law with no structure settles d_s by construction. "
                    "salt_ledger (552) follows every salted law to its end: missed if the committed rule read a "
                    "finite dimension at a later rung, clean if it ended without one, open while it goes on; its "
                    "label is 554's rule read on this campaign alone (confirmed after 1,000 clean since the last "
                    "miss for stops up to 4,096, 300 from 16,384). Since 786 nothing is carried from study to "
                    "study: a study on 784's rule learns every gate from its own decisions (gates_ledger.json)."),
    }
