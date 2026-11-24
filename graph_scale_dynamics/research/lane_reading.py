from __future__ import annotations

from collections import Counter, defaultdict

OWN = "its own reading"
SALT_STRUCTURE = "salt past the structure gate"
SALT_OTHER = "salt past another gate"
FOLLOW = "plateau follow"
AUDIT = "gate audit"
ROUTES = (OWN, SALT_STRUCTURE, SALT_OTHER, FOLLOW, AUDIT)
QUEUES = ("bought on its own reading", "audit traffic", "a calibration family")
LANE_READING_CONTRACT = "gsd-lanes-1"


def route(row: dict) -> str:
    rule, facts, reason = str(row.get("rule") or ""), row.get("facts") or {}, str(row.get("reason") or "")
    gate = facts.get("gate") or {}
    if rule == "plateau_follow" or gate.get("follow"):
        return FOLLOW
    if rule == "gate_audit":
        return AUDIT
    if gate.get("salted") or "salted past the structure gate" in reason:
        return SALT_STRUCTURE
    if rule == "salted" or facts.get("salted"):
        return SALT_OTHER
    return OWN


def queue_of(row: dict) -> str:
    lane = (row.get("facts") or {}).get("lane") or {}
    if lane.get("queue") in QUEUES:
        return str(lane["queue"])
    return QUEUES[0] if route(row) == OWN else QUEUES[1]


def build_lane_reading(decisions: dict, spend: dict, *, deep_from: int, lanes) -> dict:
    lanes = sorted(int(n) for n in lanes)
    entries: dict[int, Counter] = defaultdict(Counter)
    hours: Counter = Counter()
    families: dict[int, Counter] = defaultdict(Counter)
    in_lane: dict[int, Counter] = defaultdict(Counter)
    waiting: dict[int, Counter] = defaultdict(Counter)
    gave_up: Counter = Counter()
    resumed: Counter = Counter()
    for law, rows in (decisions or {}).items():
        rows = list(rows or [])
        first: dict[int, str] = {}
        for row in rows:
            n = row.get("next_n")
            if n is None or int(n) < int(deep_from):
                continue
            n = int(n)
            if row.get("action") == "run_next":
                if row.get("rule") == "lane_resumed":
                    resumed[n] += 1
                    continue
                if n not in first:
                    first[n] = route(row)
                    family = ((row.get("facts") or {}).get("lane") or {}).get("family")
                    if family:
                        families[n][str(family)] += 1
            elif row.get("action") == "hold" and (row.get("facts") or {}).get("yielded"):
                gave_up[n] += 1
        for n, how in first.items():
            entries[n][how] += 1
            hours[how] += float((spend.get(str(law)) or spend.get(law) or {}).get(n, 0.0)) / 3600.0
        if not rows:
            continue
        latest = rows[-1]
        n = latest.get("next_n")
        if n is not None and int(n) in lanes:
            if latest.get("action") == "run_next":
                in_lane[int(n)][first.get(int(n), route(latest))] += 1
            elif latest.get("action") == "hold" and latest.get("rule") == "deep_lane_full":
                waiting[int(n)][queue_of(latest)] += 1
    total = sum(hours.values())
    return {
        "contract": LANE_READING_CONTRACT, "deep_from": int(deep_from),
        "entries_by_route": {str(n): {r: c[r] for r in ROUTES if c.get(r)} for n, c in sorted(entries.items())},
        "core_hours_by_route": {r: round(hours[r], 3) for r in ROUTES if hours.get(r)},
        "audit_share_of_core_hours": (round(sum(v for r, v in hours.items() if r != OWN) / total, 4)
                                      if total else None),
        "lanes": {str(n): {"in_lane_now": {r: in_lane[n][r] for r in ROUTES if in_lane[n].get(r)},
                           "waiting_now": {q: waiting[n][q] for q in QUEUES if waiting[n].get(q)},
                           "gave_up": gave_up.get(n, 0), "resumed": resumed.get(n, 0),
                           "families_entered": dict(families[n].most_common())}
                  for n in lanes},
        "reading": ("A law's route into a rung is the decision that first bought it there: its own reading, or a "
                    "gate's let-through, the structure gate's audit or the plateau follow (audit traffic). Core hours are "
                    "the law's at that rung. A lane serves laws bought on their own reading first, then "
                    "audit traffic, then calibration families, and an audit law gives a full lane to a law of the "
                    "first kind (gave_up) and takes it back later (resumed)."),
    }
