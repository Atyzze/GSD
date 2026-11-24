from __future__ import annotations

from graph_scale_dynamics.decisions.engine import (
    AUDIT_RULES, DONE, FINAL_VERDICTS, HOLD, RUN_NEXT, STOP, Decision, Rung, decide, is_audit_traffic)

EMPTY = "empty"
LADDER_COMPLETE = "ladder_complete"
PROBE_VALUE = {"d_s": "d_s", "d_V": "d_V_window", "d_B": "d_B", "d_w": "d_w"}


def chain_names(spec: dict) -> list[str]:
    starts = ((spec or {}).get("sampling_contract") or {}).get("given_starts") or []
    return [EMPTY] + [str(start.get("name")) for start in starts if isinstance(start, dict) and start.get("name")]


def given_sources(metrics: dict, index: int, name: str) -> tuple[dict | None, dict | None]:
    from graph_scale_dynamics.domain import chain_list as CL
    chain = CL.GIVEN if index == 0 else name
    return CL.probes_of(metrics, chain), CL.of_chain((metrics or {}).get("census"), chain)


def chain_metrics(metrics: dict, index: int, name: str) -> dict:
    probes, census = given_sources(metrics, index, name)
    out: dict = {"health": {"n": ((metrics or {}).get("health") or {}).get("n")}}
    if census and census.get("n"):
        n = int(census["n"])
        out["health"]["mean_degree"] = 2.0 * float(census.get("edges") or 0) / max(1, n)
        out["health"]["connected_fraction"] = float((census.get("largest_component") or {}).get("size") or 0) / max(1, n)
        if isinstance((census.get("largest_component") or {}).get("edges"), int):
            out["health"]["largest_component_edges"] = int(census["largest_component"]["edges"])
    for probe, key in PROBE_VALUE.items():
        block = (probes or {}).get(probe)
        if not isinstance(block, dict):
            continue
        value = block.get("value")
        out[probe] = {"valid": bool(block.get("valid")) and isinstance(value, (int, float)), key: value,
                      "se": block.get("se"), **({"refusal": block["refusal"]} if block.get("refusal") else {}),
                      **({"measured_se": block["measured_se"]} if block.get("measured_se") is not None else {})}
    if isinstance((probes or {}).get("half_volume_radius"), (int, float)):
        out["half_volume_radius"] = probes["half_volume_radius"]
    if isinstance((probes or {}).get("small_world"), bool):
        out["small_world"] = {"flag": probes["small_world"]}
    return out


def chain_cells(spec: dict, rows_by_n: dict, states: dict) -> dict:
    from graph_scale_dynamics.decisions.evidence import _rung_cell
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    out: dict = {}
    for index, name in enumerate(chain_names(spec)[1:]):
        cells = {}
        for n in sorted(rows_by_n):
            if n not in states:
                continue
            metrics = [chain_metrics(m, index, name) for m in rows_by_n[n]]
            if not any("mean_degree" in (m.get("health") or {}) for m in metrics):
                continue
            cells[int(n)] = _rung_cell(spec, int(n), rung_summary(metrics), states[n])
        out[name] = cells
    return out


def chain_structure(structure: dict | None, index: int, name: str) -> dict:
    out = {}
    for n, rung in (structure or {}).items():
        if index < 0:
            own = rung.get("empty")
        elif index == 0:
            own = rung.get("given")
        else:
            own = (rung.get("more_given") or {}).get(name)
        if not own:
            continue
        out[int(n)] = {"empty": own, "given": own, **({"log_diameter": rung["log_diameter"]}
                                                          if index < 0 and rung.get("log_diameter") else {})}
    return out


STRONGER_FIRST_FROM = 602


def _rank(decision: Decision, order: int, stronger_first: bool = True, every_chain_alike: bool = False) -> tuple:
    if decision.action == RUN_NEXT:
        audit = is_audit_traffic(decision.rule, decision.facts) or decision.rule in AUDIT_RULES
        strength = (9 if decision.priority is None else int(decision.priority)) if stronger_first else 0
        return (1 if audit else 0, -int(decision.next_n or 0), strength, order)
    if decision.action == HOLD:
        return (2, -int(decision.next_n or 0), order)
    if decision.action == DONE and decision.rule == LADDER_COMPLETE and every_chain_alike:
        return (3, 0, order)
    return (4 if every_chain_alike else 3, 0, order)


def _top(rungs) -> int | None:
    return max((int(rung.n) for rung in rungs), default=None)


def _no_rung_below(rungs, policy) -> bool:
    return len(rungs) == 1 and int(rungs[0].n) >= int(policy.base_sizes[-1])


def decide_every_chain(law: str, chains: dict, policy, *, starts_reading: dict | None = None,
                       stronger_first: bool = True, last_rung_completes: bool = True, **context) -> Decision:
    from graph_scale_dynamics.decisions import nothing_read
    from graph_scale_dynamics.decisions import known_result
    from graph_scale_dynamics.decisions import steady_chain
    decided = _decide_every_chain(law, chains, policy, starts_reading=starts_reading, stronger_first=stronger_first,
                                  last_rung_completes=last_rung_completes, **context)
    from graph_scale_dynamics.decisions import depth
    from graph_scale_dynamics.decisions.engine import budget_gate
    read = steady_chain.gate(law, nothing_read.gate(law, decided, chains, policy), starts_reading, policy)
    seen = known_result.gate(law, read, chains, starts_reading, policy)
    from_empty = list(chains[next(iter(chains))] or [])
    from graph_scale_dynamics.decisions import cut
    seen = cut.gate(law, seen, from_empty, policy)
    return budget_gate(law, seen, from_empty, policy, depth.budget_scale(seen, policy))


def _decide_every_chain(law: str, chains: dict, policy, *, starts_reading: dict | None = None,
                        stronger_first: bool = True, last_rung_completes: bool = True, **context) -> Decision:
    names = list(chains)
    from_empty = chains[names[0]]
    own = {}
    for name in names:
        rungs = list(chains[name] or [])
        if name != names[0] and (not rungs or _top(rungs) != _top(from_empty) or _no_rung_below(rungs, policy)):
            continue
        own[name] = decide(law, rungs, policy, **context, whole_law=False)
    order = {name: index for index, name in enumerate(names)}
    alike = bool(getattr(policy, "let_through_rule", ""))
    chosen_name = min(own, key=lambda name: _rank(own[name], order[name], stronger_first, alike))
    chosen = own[chosen_name]
    if chosen.action not in (RUN_NEXT, HOLD) and names[0] in own and not (alike and chosen.action == DONE):
        chosen_name, chosen = names[0], own[names[0]]
    over = (_shape_over_verdict(chosen, names, own, starts_reading, policy, last_rung_completes)
            if chosen_name == names[0] else None)
    if over is not None:
        chosen_name, chosen = over, own[over]
    record = {name: {"action": d.action, "rule": d.rule, "next_n": d.next_n} for name, d in own.items()}
    facts = dict(chosen.facts or {}, chains=record,
                 **({"earned_by": chosen_name} if chosen_name != names[0] else {}),
                 **({"shape_over_verdict": {"empty": {"rule": own[names[0]].rule, "reason": own[names[0]].reason},
                                            "chain": over}} if over is not None else {}))
    reason = chosen.reason if chosen_name == names[0] else f"the chain from {chosen_name}: {chosen.reason}"
    decision = Decision(law=law, action=chosen.action, rule=chosen.rule, reason=reason, at_n=chosen.at_n,
                        next_n=chosen.next_n, priority=chosen.priority, facts=facts, observations=chosen.observations)
    from graph_scale_dynamics.decisions import depth
    decision = depth.complete_budget(law, decision, from_empty, policy, starts_reading)
    taking_part = {name: chains[name] for name in names if name in own}
    if starts_reading is None:
        return _barred(law, decision, taking_part, policy, starts_reading)
    from graph_scale_dynamics.decisions import starts_rule as FS
    decided = FS.decide(law, decision, starts_reading, policy, taking_part, gate=context.get("gate"),
                        standing=context.get("standing"), deep_lane_in_flight=context.get("deep_lane_in_flight"))
    if decided is decision or decided.rule not in (FS.SHAPE,) or decided.action != RUN_NEXT:
        return _barred(law, decided, taking_part, policy, starts_reading)
    fates = starts_reading.get("fates") or {}
    held = [name for name in names if (fates.get(name) or [None])[0] == "holds"]
    if held and record.get(names[0], {}).get("action") not in (RUN_NEXT, HOLD):
        decided = Decision(law=law, action=decided.action, rule=decided.rule, reason=decided.reason,
                           at_n=decided.at_n, next_n=decided.next_n, priority=decided.priority,
                           facts=dict(decided.facts, earned_by=held[0]), observations=decided.observations)
    return _barred(law, decided, taking_part, policy, starts_reading)


def _barred(law: str, decision: Decision, chains: dict, policy, starts_reading) -> Decision:
    from graph_scale_dynamics.decisions import depth
    from_empty = list(next(iter(chains.values())) if chains else [])
    return depth.bar(law, decision, from_empty, policy, starts_reading, chains=chains)


_VERDICTS = frozenset(name for name, _ in FINAL_VERDICTS)


def _shape_over_verdict(chosen: Decision, names: list, own: dict, starts_reading: dict | None, policy,
                        completes: bool = True) -> str | None:
    if (not starts_reading or chosen.action != STOP or chosen.rule not in _VERDICTS):
        return None
    from graph_scale_dynamics.decisions import starts_rule as FS
    if starts_reading.get("class") not in FS.SHAPED:
        return None
    fates = starts_reading.get("fates") or {}
    held = [name for name in names[1:] if (fates.get(name) or [None])[0] == "holds"]
    for name in held + [name for name in names[1:] if name not in held]:
        if name in own and (FS.applies(own[name], policy) or (
                completes and own[name].action == DONE and own[name].rule == LADDER_COMPLETE)):
            return name
    return None


def rungs_of(rows: list) -> list:
    from graph_scale_dynamics.decisions.replay import rungs_from_inputs
    return rungs_from_inputs(rows)


__all__ = ["EMPTY", "Rung", "chain_cells", "chain_metrics", "chain_names", "chain_structure", "decide_every_chain",
           "rungs_of", "given_sources"]
