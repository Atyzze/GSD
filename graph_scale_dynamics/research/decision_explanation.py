from __future__ import annotations

from collections import Counter

from graph_scale_dynamics.decisions.engine import SETTLING_RULES
from graph_scale_dynamics.research.landscape_audit import snapshot_landscape_rows

DECISION_EXPLANATION_VERSION = "decision-explanation-2"

PLATEAU_CLASSES = frozenset({"JOINT_PLATEAU_LIKE", "DS_ONLY_PLATEAU_LIKE", "DH_ONLY_PLATEAU_LIKE"})


def candidate_decision_trails(snapshot: dict) -> dict:
    landscape = {row["candidate_id"]: row for row in snapshot_landscape_rows(snapshot)}
    trails = []
    rule_counts: Counter = Counter()
    plateau_not_bought: Counter = Counter()
    for cid, decisions in (snapshot.get("engine_decisions") or {}).items():
        ordered = sorted(decisions or [], key=lambda row: str(row.get("decision_id") or ""))
        if not ordered:
            continue
        steps = [{"created_utc": d.get("created_utc"), "at_n": d.get("at_n"), "action": d.get("action"),
                  "rule": d.get("rule"), "reason": d.get("reason"), "priority": d.get("priority")}
                 for d in ordered]
        rule_counts.update(str(step["rule"]) for step in steps)
        current = landscape.get(str(cid)) or {}
        dimensional_class = current.get("dimensional_class")
        latest = steps[-1]
        not_bought = bool(dimensional_class in PLATEAU_CLASSES and latest["rule"] not in SETTLING_RULES)
        if not_bought:
            plateau_not_bought[str(latest["rule"])] += 1
        trails.append({
            "candidate_id": str(cid), "dimensional_class": dimensional_class,
            "connectivity_class": (current.get("connectivity") or {}).get("classification"),
            "latest_action": latest["action"], "latest_rule": latest["rule"],
            "plateau_like_but_not_bought_for_settling": not_bought,
            "steps": steps,
        })
    trails.sort(key=lambda row: (not row["plateau_like_but_not_bought_for_settling"], row["candidate_id"]))
    return {
        "version": DECISION_EXPLANATION_VERSION,
        "rule_counts": dict(rule_counts),
        "plateau_like_not_bought_for_settling_by_rule": dict(plateau_not_bought),
        "trails": trails,
        "interpretation": "each step is an engine decision as recorded; its rule and reason are the engine's own",
    }
