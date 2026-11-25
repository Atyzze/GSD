from __future__ import annotations

import json

from graph_scale_dynamics.decisions.by_word import run_on
from graph_scale_dynamics.decisions.engine import (
    Decision, Policy, Rung, Seed, decide, in_today_s_fields, policy_fingerprint,
)
from graph_scale_dynamics.decisions.gates import in_today_s_words


def _frozen(value):
    return tuple(_frozen(item) for item in value) if isinstance(value, list) else value


def rungs_from_inputs(rows: list) -> list:
    rungs = []
    for row in rows or []:
        probes = {probe: (tuple(entry) if isinstance(entry, list) else entry)
                  for probe, entry in (row.get("probes") or {}).items()}
        seeds = tuple(Seed(**seed) for seed in row.get("seeds") or [])
        rungs.append(Rung(n=int(row["n"]), mean_degree=row.get("mean_degree"),
                          connected_fraction=row.get("connected_fraction"), probes=probes,
                          chains_disagreed=bool(row.get("chains_disagreed")),
                          seeds_measured=int(row.get("seeds_measured", 3)), seeds=seeds,
                          structure=dict(row.get("structure") or {}),
                          d_s_refusal=row.get("d_s_refusal"), longer_chain=bool(row.get("longer_chain")),
                          measured_se=dict(row.get("measured_se") or {}),
                          small_world_fraction=row.get("small_world_fraction"),
                          valid_fractions=dict(row.get("valid_fractions") or {}),
                          giant_mean_degree=row.get("giant_mean_degree")))
    return rungs


def policy_from_inputs(policy: dict) -> Policy:
    return Policy(**{key: _frozen(value) for key, value in in_today_s_fields(policy).items()})


def replay(inputs: dict, order=None) -> Decision:
    policy = policy_from_inputs(inputs["policy"])
    lanes = inputs.get("deep_lane_in_flight")
    if isinstance(lanes, dict):
        lanes = {int(n): count for n, count in lanes.items()}
    context = dict(failed_seeds={int(k): v for k, v in (inputs.get("failed_seeds") or {}).items()},
                   failed_analyses={int(k): v for k, v in (inputs.get("failed_analyses") or {}).items()},
                   standing=inputs.get("standing"), deep_lane_in_flight=lanes, gate=inputs.get("gate"),
                   **({"evidence_failed": inputs["evidence_failed"]} if inputs.get("evidence_failed") else {}),
                   **({"graphs_to_n": int(inputs["graphs_to_n"])} if inputs.get("graphs_to_n") else {}))
    rungs = rungs_from_inputs(inputs.get("rungs"))
    if "chains" in inputs:
        from graph_scale_dynamics.decisions.every_chain import EMPTY, decide_every_chain
        recorded = {str(name): rows for name, rows in inputs["chains"].items()}
        given = [str(name) for name in (inputs.get("chain_order") or order or [])]
        names = [name for name in given if name in recorded] + sorted(set(recorded) - set(given))
        chains = {EMPTY: rungs, **{name: rungs_from_inputs(recorded[name]) for name in names}}
        from graph_scale_dynamics.decisions.every_chain import STRONGER_FIRST_FROM
        stronger_first = int(inputs.get("rules_revision") or 0) >= STRONGER_FIRST_FROM
        return run_on(decide_every_chain(str(inputs["law"]), chains, policy,
                                         starts_reading=inputs.get("starts_reading"), stronger_first=stronger_first,
                                         last_rung_completes=bool(inputs.get("last_rung_completes")), **context),
                      inputs.get("run_on"), policy)
    return run_on(decide(str(inputs["law"]), rungs, policy, **context), inputs.get("run_on"), policy)


FACTS_SHOWN = 4
FACT_CHARS = 160


def _normal(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _fact_paths(recorded, replayed, path: str = "") -> list[tuple[str, object, object]]:
    if isinstance(recorded, dict) and isinstance(replayed, dict):
        out = []
        for key in sorted(set(recorded) | set(replayed), key=str):
            out += _fact_paths(recorded.get(key), replayed.get(key), f"{path}.{key}" if path else str(key))
        return out
    return [] if recorded == replayed else [(path or "facts", recorded, replayed)]


def _fact_text(value) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= FACT_CHARS else text[:FACT_CHARS] + "..."


def facts_differ(recorded: dict, replayed: dict) -> str:
    paths = _fact_paths(_normal(recorded), _normal(replayed))
    shown = "; ".join(f"{path} recorded {_fact_text(a)}, replayed {_fact_text(b)}" for path, a, b in paths[:FACTS_SHOWN])
    more = len(paths) - FACTS_SHOWN
    return f"facts differ: {shown}" + (f"; and {more} more" if more > 0 else "")


def reason_in_today_s_words(row: dict, facts) -> str | None:
    from graph_scale_dynamics.decisions.engine import OVER_BUDGET, over_budget_reason
    reason = in_today_s_words(row.get("reason"))
    if row.get("rule") != OVER_BUDGET or not isinstance(facts, dict):
        return reason
    refused, chunk = facts.get("refused") or {}, facts.get("first_chunk")
    if refused.get("rule") != "longer_chain" or not isinstance(chunk, dict) or refused.get("next_n") is None:
        return reason
    try:
        former = over_budget_reason(int(refused["next_n"]), chunk, "longer_chain", former=True)
        today = over_budget_reason(int(refused["next_n"]), chunk, "longer_chain")
    except (KeyError, TypeError, ValueError):
        return reason
    return today if reason == former else reason


def replay_matches(row: dict, order=None) -> dict:
    inputs = row.get("inputs")
    if isinstance(inputs, str):
        inputs = json.loads(inputs)
    if not inputs:
        return {"matches": None, "differences": ["no inputs recorded (a released hold, or before 521)"],
                "same_rules": None}
    again = replay(inputs, order)
    stored_facts = row.get("facts")
    if stored_facts is None and row.get("facts_json") is not None:
        stored_facts = json.loads(row["facts_json"])
    stored_facts = in_today_s_words(stored_facts)
    differences = []
    for key in ("action", "rule", "reason", "next_n", "at_n", "priority"):
        recorded = reason_in_today_s_words(row, stored_facts) if key == "reason" else in_today_s_words(row.get(key))
        if getattr(again, key) != recorded:
            differences.append(f"{key}: recorded {row.get(key)!r}, replayed {getattr(again, key)!r}")
    if stored_facts is not None and _normal(again.facts) != _normal(stored_facts):
        differences.append(facts_differ(stored_facts, again.facts))
    same_rules = inputs.get("policy_fingerprint") == policy_fingerprint(policy_from_inputs(inputs["policy"]))
    return {"matches": not differences, "differences": differences, "same_rules": same_rules}
