from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np

GATE_SECTION_CONTRACT = "gsd-structure-gate-report-1"

_FIELDS = ("stage", "result", "refused", "early", "audit", "pattern", "underlying", "one_more_rung", "twice",
           "salted", "follow")


def collect_gate(conn, campaign_id: str) -> dict:
    extracted = ", ".join(f"facts_json::jsonb#>>'{{gate,{name}}}' AS {name}" for name in _FIELDS)
    rows = [dict(r) for r in conn.execute(
        f"SELECT candidate_id, decision_id, at_n, next_n, action, rule, {extracted} FROM engine_decisions "
        "WHERE campaign_id=? AND left(facts_json,1)='{' AND facts_json LIKE ? ORDER BY decision_id",
        (str(campaign_id), '%"gate"%')).fetchall()]
    for row in rows:
        for name in _FIELDS:
            value = row.get(name)
            if isinstance(value, str) and value[:1] in "{[":
                try:
                    row[name] = json.loads(value)
                except ValueError:
                    pass
    audited = sorted({r["candidate_id"] for r in rows if r["rule"] in ("gate_audit", "plateau_follow")
                      or (r["one_more_rung"] not in (None, "")) or _true(r.get("salted"))})
    after = []
    if audited:
        marks = ",".join("?" for _ in audited)
        after = [dict(r) for r in conn.execute(
            f"SELECT candidate_id, decision_id, at_n, action, rule, facts_json::jsonb#>>'{{gate,result}}' AS result "
            f"FROM engine_decisions WHERE campaign_id=? AND candidate_id IN ({marks}) AND left(facts_json,1)='{{' "
            "ORDER BY decision_id", (str(campaign_id), *audited)).fetchall()]
    return {"decisions": rows, "after": after}


def _true(value) -> bool:
    return value is True or str(value).lower() == "true"


def _latest_per_law(rows: list[dict]) -> dict:
    latest = {}
    for row in rows:
        latest[row["candidate_id"]] = row
    return latest


def _next_decision(after: dict, law: str, at_n, decision_id: str) -> dict | None:
    return next((r for r in after.get(law, []) if r["at_n"] == at_n and str(r["decision_id"]) > str(decision_id)), None)


def _rung_cost(costs: list[dict], seeds: int = 3) -> dict:
    by_n = defaultdict(list)
    for row in costs or []:
        child = (row.get("cost") or {}).get("child") or {}
        if child.get("cpu_seconds") is not None:
            by_n[int(row["n"])].append(float(child["cpu_seconds"]))
    return {n: seeds * float(np.median(v)) for n, v in by_n.items() if v}


def gate_section(gate: dict | None, costs: list[dict] | None = None) -> dict:
    rows = list((gate or {}).get("decisions") or [])
    if (gate or {}).get("error"):
        return {"error": gate["error"]}
    if not rows:
        return {"laws_read": 0, "why": "no decision carries a gate reading yet (rule 8; it reads from "
                                       "N=16,384)"}
    after = defaultdict(list)
    for row in (gate or {}).get("after") or []:
        after[row["candidate_id"]].append(row)
    laws = {r["candidate_id"] for r in rows}
    full = [r for r in rows if r.get("stage") == "full"]
    early = [r for r in rows if r.get("stage") == "early"]

    results = Counter(str(r.get("result")) for r in _latest_per_law(full).values())

    stops = _latest_per_law([r for r in rows if r["action"] == "stop" and _true(r.get("refused"))])
    refusals = Counter()
    saved_rungs = Counter()
    held_anyway = 0
    for row in stops.values():
        kind = row["rule"]
        if row.get("twice"):
            results_twice = (row["twice"] or {}).get("results") or []
            kind += (": chains disagree on structure, twice" if results_twice and set(results_twice) == {"chains disagree on structure"}
                     else ": undecidable twice")
        refusals[f"{kind} ({row.get('stage')})"] += 1
        underlying = row.get("underlying") or {}
        if underlying.get("action") == "run_next" and underlying.get("next_n") is not None:
            saved_rungs[int(underlying["next_n"])] += 1
        else:
            held_anyway += 1
    prices = _rung_cost(costs or [])
    saved = {str(n): {"rungs_refused": count,
                      "core_hours_estimated": (round(count * prices[n] / 3600.0, 2) if n in prices else None)}
             for n, count in sorted(saved_rungs.items())}
    priced = [v["core_hours_estimated"] for v in saved.values() if v["core_hours_estimated"] is not None]

    shadow = {"would_refuse_at_16384": len({r["candidate_id"] for r in early if r.get("result") == "would refuse"}),
              "refused_at_16384": len({r["candidate_id"] for r in early
                                       if r["action"] == "stop" and _true(r.get("refused"))})}
    compared = {}
    for row in full:
        e = row.get("early") or {}
        if isinstance(e, dict) and _true(e.get("would_refuse")):
            compared[row["candidate_id"]] = ("agrees" if _true(e.get("agrees"))
                                             else "disagrees: the full rule read finite" if _true(e.get("disagrees"))
                                             else "the full rule could not decide")
    shadow["read_again_at_65536"] = dict(Counter(compared.values()))

    audits = [r for r in rows if r["rule"] == "gate_audit"]
    outcome = Counter()
    for row in audits:
        later = _next_decision(after, row["candidate_id"], row["next_n"], row["decision_id"])
        if later is None:
            outcome["not decided yet"] += 1
        else:
            outcome[f"{later['rule']}" + (f" ({later['result']})" if later.get("result") else "")] += 1
    reasons = Counter()
    for row in audits:
        a = row.get("audit") or {}
        reasons["the deep control" if (_true(a.get("deep_control")) and not _true(a.get("inside_the_windows")))
                else "the salted share" if _true(a.get("sampled")) else "near a threshold"] += 1

    def showed_next(chosen: list[dict]) -> dict:
        seen = Counter()
        for row in chosen:
            later = _next_decision(after, row["candidate_id"], row["next_n"], row["decision_id"])
            seen["not decided yet" if later is None else (str(later["rule"]) + (
                f" ({later['result']})" if later.get("result") else ""))] += 1
        return dict(seen)
    salted_rows = [r for r in rows if _true(r.get("refused")) and _true(r.get("salted"))]
    follows = [r for r in rows if r["rule"] == "plateau_follow"]

    extra = [r for r in rows if r.get("one_more_rung") not in (None, "")]
    showed = Counter()
    for row in extra:
        later = _next_decision(after, row["candidate_id"], row["next_n"], row["decision_id"])
        showed["not decided yet" if later is None else str(later.get("result") or later["rule"])] += 1

    return {
        "contract": GATE_SECTION_CONTRACT,
        "laws_read": len(laws),
        "full_rule_reads": dict(results),
        "refused_laws": dict(refusals),
        "refused_total": len(stops),
        "saved": {"by_rung": saved, "core_hours_estimated": (round(sum(priced), 2) if priced else None),
                  "held_anyway": held_anyway,
                  "how": ("a refused rung priced at the seeds a rung runs times this campaign's median finished "
                          "simulation attempt at that N (child CPU seconds); a law the other rules held saved no "
                          "rung now, and a rung with no measured attempt yet is not priced")},
        "early_stage": shadow,
        "audit": {"decisions": len(audits), "why": dict(reasons), "next_rung_showed": dict(outcome)},
        "salted": {"decisions": len(salted_rows), "laws": len({r["candidate_id"] for r in salted_rows}),
                   "next_rung_showed": showed_next(salted_rows)},
        "plateau_follow": {"decisions": len(follows), "laws": len({r["candidate_id"] for r in follows}),
                           "next_rung_showed": showed_next(follows)},
        "one_more_rung": {"laws": len({r["candidate_id"] for r in extra}), "next_rung_showed": dict(showed)},
        "reading": ("Every count is over the gate's own record (`facts.gate` on each decision), one law each. A "
                    "refusal of a rung the other rules bought is the saving; the audit's next rung is what it "
                    "cost, and a finite reading there is a law the gate would have lost."),
    }


def folder_status(repo, campaign_id: str | None = None) -> dict:
    from graph_scale_dynamics.db.decision_store import (
        EARLY_STAGE_FLAG, early_stage_counts)
    from graph_scale_dynamics.decisions.engine import GATE_RULES, Policy

    policy = Policy()
    conn = repo.conn
    counts = early_stage_counts(conn, policy.gate_at_n)
    out = {"contract": GATE_SECTION_CONTRACT,
           "early_stage": {"switch": repo.get_flag(EARLY_STAGE_FLAG, "") == "on",
                           "agreements_needed": int(policy.early_gate_agreements), **counts},
           "rule": {"gap_exponent_at_most": policy.gap_exponent_at_most,
                    "diameter_exponent_at_least": policy.diameter_exponent_at_least,
                    "gap_window": list(policy.gap_window), "diameter_window": list(policy.diameter_window),
                    "early_gate_at_n": policy.early_gate_at_n, "gate_at_n": policy.gate_at_n,
                    "audit_in_flight_at_most": policy.gate_audit_in_flight}}
    if campaign_id:
        marks = ",".join("?" for _ in GATE_RULES)
        by_rule = {str(r["rule"]): int(r["c"]) for r in conn.execute(
            "SELECT rule, COUNT(*) AS c FROM engine_decisions_latest WHERE campaign_id=? "
            f"AND rule IN ({marks}) GROUP BY rule", (str(campaign_id), *sorted(GATE_RULES))).fetchall()}
        out["campaign"] = {"campaign_id": str(campaign_id), "laws_by_latest_rule": by_rule,
                           "audits_in_flight": by_rule.get("gate_audit", 0)}
    return out
