from __future__ import annotations

from collections import Counter, defaultdict
import json

from dataclasses import replace

from graph_scale_dynamics.research.gate_tree import build_gate_tree
from graph_scale_dynamics.research.graph_trickle import build_graphs_by_rung, graphs_per_law_rung
from graph_scale_dynamics.research.lane_reading import build_lane_reading
from graph_scale_dynamics.research.law_ledger import build_law_ledger
from graph_scale_dynamics.research.outcome_ledger import build_outcome_ledger
from graph_scale_dynamics.reporting.every_chain_report import every_chain_section
from graph_scale_dynamics.research.record_report import build_record_sections
from graph_scale_dynamics.decisions.engine import (
    ENGINE_VERSION, RUN_NEXT, SETTLING_RULES, STOP, Policy, decide, is_engine_campaign)
from graph_scale_dynamics.decisions.rungs import rungs_from_phenotype
from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES

CONTRACT = "gsd-decision-engine-record-1"
FINAL_VERDICTS = ("empty", "disconnected", "too_dense")


def job_budgets(snapshot: dict) -> dict:
    out = {}
    for row in snapshot.get("jobs") or []:
        one_shot = (((row.get("spec") or {}).get("execution") or {}).get("one_shot") or {})
        value = one_shot.get("work_budget")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0 and row.get("job_id"):
            out[str(row["job_id"])] = int(value)
    return out


def seed_work(measurement: dict) -> dict:
    terminal = (((measurement or {}).get("metrics") or {}).get("health") or {}).get("rung_terminal") or {}
    work = terminal.get("work") if isinstance(terminal.get("work"), dict) else {}
    return {"units": work.get("units"), "budget": work.get("budget"), "reason": terminal.get("reason")}


def _seed_budgets(snapshot: dict) -> dict:
    last: dict = {}
    for row in snapshot.get("measurements") or []:
        if row.get("n") is None:
            continue
        key = (str(row["candidate_id"]), int(row["n"]), row.get("seed"))
        if key not in last or str(row.get("created_utc") or "") >= str(last[key].get("created_utc") or ""):
            last[key] = row
    out: dict = defaultdict(list)
    for (cid, n, _seed), row in sorted(last.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        out[(cid, n)].append(seed_work(row))
    return out


SEED_COLUMNS = ("law", "n", "seed", "attempts", "simulation_seconds", "cpu_seconds", "peak_memory_bytes",
                "final_edges", "final_mean_degree", "ended", "work_budget", "budget_fraction",
                "d_s_seconds", "d_V_seconds", "d_B_seconds", "d_w_seconds", "interrupted",
                "kappa_seconds", "kappa_mean",
                "moves_per_cpu_second", "cpu", "die",
                "budget_ended", "work_units", "work", "work_parts")


def _seed_table(snapshot: dict, policy: Policy, budgets: dict | None = None) -> dict:
    budgets = job_budgets(snapshot) if budgets is None else budgets
    sims: dict = {}
    counts = Counter()
    interrupted = Counter()
    for row in snapshot.get("attempts") or []:
        if row.get("kind") not in (None, "simulate") or row.get("n") is None or row.get("attempt_id") is None:
            continue
        key = (str(row["candidate_id"]), int(row["n"]), row.get("seed"))
        if row.get("error_class") in INTERRUPTED_ATTEMPT_CLASSES:
            interrupted[key] += 1
            continue
        counts[key] += 1
        if row.get("wall_seconds") is not None and (
                key not in sims or str(row.get("finished_utc") or "") >= str(sims[key].get("finished_utc") or "")):
            sims[key] = row
    probes: dict = {}
    for row in snapshot.get("measurements") or []:
        if row.get("n") is None:
            continue
        key = (str(row["candidate_id"]), int(row["n"]), row.get("seed"))
        if key not in probes or str(row.get("created_utc") or "") >= str(probes[key].get("created_utc") or ""):
            probes[key] = row
    laws: dict = {}
    rows = []
    rounded = lambda v, k=3: (round(float(v), k) if v is not None else None)
    for key in sorted(set(sims) | set(probes) | set(interrupted), key=lambda k: (k[0], k[1], str(k[2]))):
        cid, n, seed = key
        sim, probe = sims.get(key) or {}, probes.get(key) or {}
        wall = sim.get("wall_seconds")
        cpu = None
        if sim.get("user_cpu_seconds") is not None or sim.get("system_cpu_seconds") is not None:
            cpu = float(sim.get("user_cpu_seconds") or 0.0) + float(sim.get("system_cpu_seconds") or 0.0)
        memory = sim.get("peak_pss_bytes") or sim.get("peak_uss_bytes") or sim.get("peak_rss_bytes")
        work = seed_work(probe)
        budget = work["budget"] or budgets.get(str(sim.get("job_id"))) or (
            policy.work_budget(n) if policy.work_budgets else None)
        rows.append([laws.setdefault(cid, len(laws)), n, seed, counts.get(key, 0), rounded(wall), rounded(cpu),
                     memory, sim.get("final_edge_count"), rounded(sim.get("final_mean_degree"), 4),
                     _ended(sim, probe), budget,
                     rounded(work["units"] / budget, 5) if work["units"] is not None and budget else None,
                     rounded(probe.get("probe_seconds_d_s")), rounded(probe.get("probe_seconds_d_v")),
                     rounded(probe.get("probe_seconds_d_b")), rounded(probe.get("probe_seconds_d_w")),
                     interrupted.get(key, 0), *_kappa_cells(probe), *_speed_cells(sim),
                     work["reason"] == "budget" if work["reason"] is not None else None, work["units"],
                     (probe.get("metrics") or {}).get("work"), (probe.get("metrics") or {}).get("work_parts")])
    return {"columns": list(SEED_COLUMNS), "laws": list(laws), "rows": rows}


def _ended(attempt: dict, measurement: dict) -> str | None:
    terminal = (((measurement or {}).get("metrics") or {}).get("health") or {}).get("rung_terminal") or {}
    return terminal.get("reason") or (attempt or {}).get("error_class")


def _budget_ended_at(rows: list[dict]) -> list[int]:
    return sorted({int(row["at_n"]) for row in rows
                   if (row.get("facts") or {}).get("budget_ended") and row.get("at_n") is not None})


def _speed_cells(attempt: dict) -> tuple:
    raw = (attempt or {}).get("resource_json")
    if isinstance(raw, str):
        if '"cpu_speed"' not in raw:
            return (None, None, None)
        try:
            raw = json.loads(raw)
        except ValueError:
            return (None, None, None)
    speed = (raw or {}).get("cpu_speed") if isinstance(raw, dict) else None
    if not isinstance(speed, dict):
        return (None, None, None)
    return (speed.get("moves_per_cpu_second"), speed.get("cpu"), speed.get("l3"))


def _kappa_cells(measurement: dict) -> tuple:
    metrics = (measurement or {}).get("metrics") or {}
    seconds = (metrics.get("probe_seconds") or {}).get("kappa")
    from_empty = (metrics.get("curvature") or {}).get("empty") or {}
    mean = from_empty.get("mean") if from_empty.get("measured") else None
    return (round(float(seconds), 3) if isinstance(seconds, (int, float)) else None,
            round(float(mean), 5) if isinstance(mean, (int, float)) else None)


def _band(fraction) -> str:
    if fraction is None:
        return "unknown"
    return ("<1%" if fraction < 0.01 else "1-10%" if fraction < 0.1 else "10-50%" if fraction < 0.5
            else "50-100%" if fraction < 1.0 else "reached")


def _landing(decision: dict) -> str:
    if decision.get("action") == RUN_NEXT and decision.get("rule") in SETTLING_RULES:
        return "settled"
    return str(decision.get("rule")) if decision.get("action") == STOP else str(decision.get("action"))


def _salted_past_a_final_verdict(row: dict) -> bool:
    facts = row.get("facts") or {}
    return bool(set(facts.get("salted") or []) & set(FINAL_VERDICTS)) or bool(facts.get("audit_sample"))


def _audit_losses(snapshot: dict, decisions: dict, policy: Policy) -> dict:
    phenotypes = {str(row["candidate_id"]): row.get("phenotype") or {} for row in snapshot.get("phenotypes") or []}
    unaudited = replace(policy, audit_fraction=0.0, salt_shares=())
    losses = defaultdict(lambda: {"audit_laws_it_would_have_stopped": 0, "measured_past_the_stop": 0,
                                  "later_real_d_s": 0})
    audited = examined = 0
    for cid, rows in decisions.items():
        if not any(_salted_past_a_final_verdict(row) for row in rows):
            continue
        audited += 1
        rungs = rungs_from_phenotype(phenotypes.get(cid) or {})
        if not rungs:
            continue
        examined += 1
        for k in range(1, len(rungs) + 1):
            decision = decide(cid, rungs[:k], unaudited)
            if decision.action == STOP and decision.rule in FINAL_VERDICTS:
                entry = losses[decision.rule]
                entry["audit_laws_it_would_have_stopped"] += 1
                entry["measured_past_the_stop"] += int(len(rungs) > k)
                entry["later_real_d_s"] += int(any("d_s" in r.probes for r in rungs[k:]))
                break
    return {"audit_sample_laws": audited, "examined": examined,
            "not_examined_base_block_unfinished": audited - examined,
            "by_rule": {rule: dict(losses[rule]) for rule in FINAL_VERDICTS},
            "reading": ("later_real_d_s is out of measured_past_the_stop, the laws the replay could see past the "
                        "rung it would have stopped them at; a law still at that rung shows nothing either way.")}


def _chain_order(spec: dict) -> list[str]:
    from graph_scale_dynamics.decisions.every_chain import chain_names
    return chain_names(spec)[1:]


def budgets_section(spec: dict, policy: Policy, budgets: dict) -> dict:
    from graph_scale_dynamics.scheduling.limits import estimated_seconds
    given = Counter(int(units) for units in budgets.values())
    in_force = {str(n): int(policy.work_budget(n)) for n in policy.ladder()} if policy.work_budgets else {}
    return {"in_force": in_force,
            "estimated_seconds": {n: estimated_seconds(spec, int(n)) for n in in_force},
            "unit": {"weights": policy.work_weights(), "seconds_a_unit": float(policy.seconds_a_unit)},
            "seed_jobs": len(budgets), "budgets_given": {str(k): v for k, v in sorted(given.items())},
            "reading": ("in_force is each size's budget in units of work, fixed in the design; a seed's job carries "
                        "its own (twice the size's for a law bought on merit), which is the seed table's work_budget "
                        "and the denominator of its budget_fraction; estimated_seconds is the budget at the seconds a "
                        "unit took where the unit was fitted, an estimate that decides nothing")}


def build_decision_engine_report(snapshot: dict, policy: Policy | None = None) -> dict:
    spec = (snapshot.get("campaign") or {}).get("spec") or {}
    if policy is None:
        policy = Policy.from_spec(spec) if is_engine_campaign(spec) else Policy()
    budgets = job_budgets(snapshot)
    decisions = {str(cid): sorted(rows or [], key=lambda r: str(r.get("decision_id") or ""))
                 for cid, rows in (snapshot.get("engine_decisions") or {}).items()}
    spend: dict = defaultdict(dict)
    longer_spend: dict = defaultdict(dict)
    for row in snapshot.get("rung_spend") or []:
        spend[str(row["candidate_id"])][int(row["n"])] = float(row.get("core_seconds") or 0.0)
        longer_spend[str(row["candidate_id"])][int(row["n"])] = float(row.get("longer_seconds") or 0.0)
    rules = defaultdict(lambda: {"decisions": 0, "jobs_created": 0, "core_seconds_bought": 0.0})
    charged: set = set()
    bought = defaultdict(Counter)
    seeds_by_rung = _seed_budgets(snapshot)
    use = defaultdict(lambda: defaultdict(Counter))
    laws = []
    for cid, rows in decisions.items():
        for index, row in enumerate(rows):
            entry = rules[(row.get("action"), row.get("rule"))]
            entry["decisions"] += 1
            entry["jobs_created"] += int(row.get("jobs_created") or 0)
            if row.get("action") == RUN_NEXT and row.get("next_n") is not None:
                n = int(row["next_n"])
                again = (row.get("at_n") is not None and int(row["at_n"]) == n
                         and row.get("rule") != "complete_rung")
                if (cid, n, again) not in charged:
                    charged.add((cid, n, again))
                    longer = longer_spend[cid].get(n, 0.0)
                    entry["core_seconds_bought"] += longer if again else spend[cid].get(n, 0.0) - longer
            if row.get("action") == RUN_NEXT and row.get("priority") is not None:
                later = next((r for r in rows[index + 1:] if r.get("at_n") == row.get("next_n")), None)
                bought[str(row["priority"])][str(later.get("rule")) if later else "not_decided_yet"] += 1
        if not rows:
            continue
        latest = rows[-1]
        landing = _landing(latest)
        for (law, n), seeds in seeds_by_rung.items():
            if law != cid:
                continue
            for seed in seeds:
                budget = seed["budget"] or (policy.work_budget(n) if policy.work_budgets else None)
                fraction = seed["units"] / budget if seed["units"] is not None and budget else None
                use[landing][n]["reached" if seed["reason"] == "budget" else _band(fraction)] += 1
        laws.append({"candidate_id": cid, "decisions": len(rows), "action": latest.get("action"),
                     "rule": latest.get("rule"), "at_n": latest.get("at_n"), "next_n": latest.get("next_n"),
                     "priority": latest.get("priority"), "reason": latest.get("reason"),
                     "budget_ended_at": _budget_ended_at(rows)})
    seeds = _seed_table(snapshot, policy, budgets)
    outcomes = build_outcome_ledger(decisions)
    gates = build_gate_tree(decisions, graphs_per_law_rung(seeds), policy=policy)
    if outcomes["salt_by_gate"]:
        gates["salt_outcomes"] = outcomes["salt_by_gate"]
    chains = every_chain_section(snapshot)
    return {
        "contract": CONTRACT,
        "engine": ENGINE_VERSION,
        "policy": dict(policy.__dict__),
        "laws_decided": len(laws),
        "decisions": sum(len(rows) for rows in decisions.values()),
        "rules": [{"action": a, "rule": r, **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in e.items()}}
                  for (a, r), e in sorted(rules.items(), key=lambda kv: (-kv[1]["decisions"], str(kv[0])))],
        "bought_by_priority_and_what_the_next_rung_showed": {p: dict(c) for p, c in sorted(bought.items())},
        "stop_losses_on_the_audit_sample": _audit_losses(snapshot, decisions, policy),
        "gate_tree": gates,
        "outcome_ledger": outcomes,
        "graphs_by_rung": build_graphs_by_rung(seeds, snapshot.get("measurements"), decisions),
        "lanes": build_lane_reading(decisions, spend, deep_from=policy.plateau_from_n, lanes=policy.lane_rungs()),
        "the_record": build_record_sections(snapshot.get("record"), snapshot.get("measurements"),
                                            snapshot.get("phenotypes"), chain_order=_chain_order(spec)),
        "budget_use": {landing: {str(n): dict(bands) for n, bands in sorted(by_n.items())}
                       for landing, by_n in sorted(use.items())},
        "budgets": budgets_section(spec, policy, budgets),
        "laws": laws,
        "seeds": seeds,
        "law_ledger": build_law_ledger(snapshot.get("candidates") or [], seeds, laws, cap=policy.dense_cap,
                                      measurements=snapshot.get("measurements")),
        "every_chain": chains,
        "reading": ("Every row is a recorded engine decision. `core_seconds_bought` is the simulation spend on the "
                    "rungs each rule bought, each charged once: a rung's first runs to the rule that first bought it, "
                    "its longer chains to the rule that ran it again; summed over the rules it is at most the "
                    "campaign's simulation, a part of the one core-hour figure (simulation and analysis, "
                    "`the_record.compute_by_regime`). A hold is not a stop: a held law runs when nothing better "
                    "waits. A final-verdict stop's loss is measured on the audit sample, which runs past those "
                    "stops."),
    }
