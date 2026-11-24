from __future__ import annotations

from collections import Counter, defaultdict

from graph_scale_dynamics.research import gate_tree as T

CONTRACT = "gsd-outcome-ledger-1"
SHAPED = frozenset({"one_space", "grows", "converts", "selects", "holds"})
STARTS_PARKS = ("starts_alike", "starts_apart_twice", "starts_apart_by_history",
                    "starts_shape_unread")
HELD, NOT_HELD, NOT_READ, OPEN = "held", "not_held", "not_read", "open"
CLAIMS = {"starts_shape": "still shaped", "starts_apart": "found a shape", "salted": "found a shape",
          "d_s_settled": "settled again", "second_rung": "settled again", "gate_audit": "a finite dimension",
          "plateau_follow": "settled again"}
IN_PROGRESS = frozenset({"start", "complete_rung", "longer_chain", "lane_resumed"})


def _facts(row: dict) -> dict:
    facts = row.get("facts")
    return facts if isinstance(facts, dict) else {}


def class_at(row: dict, n: int) -> str | None:
    seen = _facts(row).get("starts_reading") or {}
    classes = seen.get("classes") or {}
    label = classes.get(str(int(n))) if isinstance(classes, dict) else None
    if label is None and isinstance(classes, dict):
        label = classes.get(int(n))
    return str(label) if label not in (None, "not_read") else None


def _settled(row: dict):
    value = _facts(row).get("d_s_settled")
    return value if isinstance(value, bool) else None


def _outcome(rule: str, buy: dict, final: dict | None) -> str:
    if final is None:
        return OPEN
    n = int(buy["next_n"])
    shape = class_at(final, n)
    if rule in ("starts_shape", "starts_apart") or (rule == "salted" and (_facts(final).get("starts_reading")
                                                                                 or {}).get("decided")):
        return NOT_READ if shape is None else (HELD if shape in SHAPED else NOT_HELD)
    if rule == "gate_audit":
        result = (_facts(final).get("gate") or {}).get("result")
        return NOT_READ if result is None else (HELD if result == T.FINITE else NOT_HELD)
    settled = _settled(final)
    return NOT_READ if settled is None else (HELD if settled else NOT_HELD)


def _final_at(rows: list[dict], start: int, n: int) -> dict | None:
    final = None
    for row in rows[start + 1:]:
        if row.get("at_n") is not None and int(row["at_n"]) == int(n) and str(row.get("rule")) not in IN_PROGRESS:
            final = row
    return final


def build_outcome_ledger(decisions: dict[str, list[dict]]) -> dict:
    counts: dict = defaultdict(Counter)
    salt_ends: dict = defaultdict(lambda: defaultdict(list))
    for _law, rows in decisions.items():
        for index, row in enumerate(rows or []):
            rule = str(row.get("rule"))
            if (row.get("action") != "run_next" or rule not in CLAIMS or row.get("next_n") is None
                    or row.get("at_n") is None or int(row["next_n"]) <= int(row["at_n"])):
                continue
            final = _final_at(rows, index, int(row["next_n"]))
            end = _outcome(rule, row, final)
            counts[(rule, int(row["at_n"]), int(row["next_n"]))][end] += 1
            gate = str((_facts(row).get("salted_from") or {}).get("rule") or "")
            if rule == "salted" and gate in STARTS_PARKS:
                cost = T.DEEP if int(row["at_n"]) >= T.DEEP_FROM else T.CHEAP
                ledger_end = {HELD: T.MISSED, NOT_HELD: T.CLEAN, OPEN: T.OPEN, NOT_READ: T.UNTESTED}[end]
                if final is not None and str(final.get("action")) == "stop" and end == NOT_READ:
                    ledger_end = T.BOUGHT_NOTHING if int(final["at_n"]) == int(row["at_n"]) else T.UNTESTED
                salt_ends[gate][cost].append((str(row.get("decision_id") or ""), ledger_end))
    rules = []
    for (rule, at_n, next_n), c in sorted(counts.items()):
        read = c[HELD] + c[NOT_HELD]
        rules.append({"rule": rule, "claim": CLAIMS[rule], "from_n": at_n, "to_n": next_n,
                      "bought": sum(c.values()), "decided": sum(c.values()) - c[OPEN], "read": read,
                      "held": c[HELD], "not_held": c[NOT_HELD], "not_read": c[NOT_READ], "open": c[OPEN],
                      "hit_rate": round(c[HELD] / read, 4) if read else None})
    return {"contract": CONTRACT, "rules": rules,
            "salt_by_gate": {gate: {cost: T.ledger(ends, cost) for cost, ends in by_cost.items()}
                             for gate, by_cost in sorted(salt_ends.items())},
            "reading": ("Every rung bought above the one a law stood on, against the law's last decision at that rung: "
                        "held when the reason it was bought for held there (a shape still shaped, an apart look or "
                        "a salt that found a shape, d_s settled again, the structure gate's audit reading a finite "
                        "dimension), not read when it was decided there without that reading, open while it is not "
                        "decided there yet. The hit rate is the held among those read. The starts' parks' "
                        "salts are written as their salt ledgers (a salted law that found a shape is the park's "
                        "miss), which set the next new study's shares for those parks; none is tuned within a "
                        "study.")}


__all__ = ["CONTRACT", "STARTS_PARKS", "build_outcome_ledger", "class_at"]
