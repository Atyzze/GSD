from __future__ import annotations

import math
from collections import Counter, defaultdict

CONTRACT = "gsd-every-chain-report-1"


def _first_given_name(rows: list[dict]) -> str | None:
    for row in rows:
        given_chains = ((((row.get("metrics") or {}).get("health") or {}).get("rung_terminal") or {}).get("given_chains")) or []
        if given_chains and isinstance(given_chains[0], dict) and given_chains[0].get("name"):
            return str(given_chains[0]["name"])
    return None


VALUE_COLUMNS = ("n", "d_s", "d_V", "d_B", "d_w", "reach", "mean_degree", "giant_fraction", "triangles_per_node",
                 "squares_per_node", "kappa", "moved")
MEDIANS = ("moved",)


def _short4(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None
    return float(f"{float(value):.4g}")


def chain_values(chains: dict) -> dict:
    out: dict = {}
    for rung in sorted((chains or {}).get("rungs") or [], key=lambda r: int(r.get("n") or 0)):
        sides = {"empty": rung.get("empty"), "given": rung.get("given"), **dict(rung.get("more_given") or {})}
        for name, side in sides.items():
            if not isinstance(side, dict):
                continue
            row = [int(rung["n"])] + [_short4((side.get(key) or {}).get("median" if key in MEDIANS else "mean"))
                                      for key in VALUE_COLUMNS[1:]]
            out.setdefault(name, []).append(row)
    return out


def law_scores(measurements: list[dict], specs: dict | None = None, campaign_spec: dict | None = None) -> dict:
    from graph_scale_dynamics.observability import starts_reading, law_score
    from graph_scale_dynamics.observability.space_score import FROM_N, space_score
    from graph_scale_dynamics.observability.two_chains import chains_per_rung
    by_law: dict = defaultdict(list)
    for row in measurements or []:
        if row.get("n") is not None and isinstance(row.get("metrics"), dict):
            by_law[str(row.get("candidate_id"))].append(row)
    out = {}
    starts = ((campaign_spec or {}).get("sampling_contract") or {}).get("given_starts")
    for law, rows in by_law.items():
        top = max(int(r["n"]) for r in rows)
        if top < FROM_N:
            continue
        chains = chains_per_rung(rows, starts)
        score = space_score(chains, (specs or {}).get(law))
        scored = {}
        for name, reading in (score.get("chains") or {}).items():
            scored[name] = {"d": reading.get("d"), "space": bool(reading.get("space")), "worst": reading.get("worst"),
                            "rungs": [[r["n"], r.get("distance"), r.get("worst")] for r in reading.get("rungs") or []]}
        given = _first_given_name(rows)
        named = dict(chains, given_name=given)
        structure = starts_reading.hold_structure(campaign_spec)
        reading = starts_reading.law_reading(named, starts, structure=structure)
        family = law_score.given_family(campaign_spec, str(law), (specs or {}).get(str(law)))
        out[law] = {"top_n": top, "stage": score.get("stage"), "spaces": list(score.get("spaces") or []),
                    "given": given, "given_family": family,
                    "chains": scored, "full": bool((score.get("full") or {}).get("passed")),
                    "starts_reading": starts_reading.compact(reading), "values": chain_values(chains),
                    "score": law_score.compact(law_score.score(named, reading, starts=starts, first_given=family,
                                                               structure=structure))}
    return out


TOP_SCORES = 25


def score_summary(scores: dict) -> dict:
    from graph_scale_dynamics.observability import law_score
    scored = {law: entry["score"] for law, entry in scores.items() if isinstance(entry.get("score"), dict)}
    above = {law: s for law, s in scored.items() if s["score"] > 0}
    top = sorted(above.items(), key=lambda kv: (-kv[1]["score"], -(kv[1]["to_n"] or 0), kv[0]))[:TOP_SCORES]
    return {"contract": law_score.CONTRACT, "laws": len(scored), "above_zero": len(above),
            "by": dict(Counter(s["by"] for s in above.values())),
            "top": [dict(s, law=law) for law, s in top], "ladder": list(law_score.LADDER),
            "weights": dict(law_score.WEIGHTS)}


def decided_law(own: dict | None) -> bool:
    from graph_scale_dynamics.decisions.engine import DONE, HOLD, PARKING_RULES, STOP
    own = own or {}
    if own.get("rule") == "failed":
        return False
    return own.get("action") in (STOP, DONE) or (own.get("action") == HOLD and own.get("rule") in PARKING_RULES)


def _stopped_or_parked(own: dict | None) -> bool:
    from graph_scale_dynamics.decisions.engine import HOLD, PARKING_RULES, STOP
    own = own or {}
    return own.get("action") == STOP or (own.get("action") == HOLD and own.get("rule") in PARKING_RULES)


def earned(decisions: dict | None) -> dict:
    by_chain: Counter = Counter()
    laws: dict = defaultdict(set)
    over_the_chain_from_empty: set = set()
    chain_by_chain = 0
    for law, rows in (decisions or {}).items():
        for row in rows or []:
            facts = row.get("facts") or {}
            if not isinstance(facts, dict) or "chains" not in facts:
                continue
            chain_by_chain += 1
            who = facts.get("earned_by")
            if who:
                by_chain[(str(who), str(row.get("rule")))] += 1
                laws[str(who)].add(str(law))
                if _stopped_or_parked((facts.get("chains") or {}).get("empty")):
                    over_the_chain_from_empty.add(str(law))
    return {"decisions_chain_by_chain": chain_by_chain,
            "earned_by": [{"chain": chain, "rule": rule, "decisions": count, "laws": len(laws[chain])}
                          for (chain, rule), count in sorted(by_chain.items(), key=lambda kv: (-kv[1], kv[0]))],
            "laws_earned": sorted({law for values in laws.values() for law in values}),
            "laws_earned_over_the_chain_from_empty": sorted(over_the_chain_from_empty)}


def starts_reading_classes(scores: dict, specs: dict | None = None) -> dict:
    from graph_scale_dynamics.observability import starts_reading
    every, by_temperature = Counter(), {"zero": Counter(), "finite": Counter(), "not known": Counter()}
    for law, score in scores.items():
        label = (score.get("starts_reading") or {}).get("class") or "not_read"
        every[label] += 1
        spec = (specs or {}).get(law)
        zero = bool((spec.get("dynamics") or {}).get("zero_temperature", False)) if isinstance(spec, dict) else None
        by_temperature["zero" if zero is True else "finite" if zero is False else "not known"][label] += 1
    order = [key for key, _name in starts_reading.CLASSES]
    def ordered(counts):
        return {key: counts[key] for key in order if counts.get(key)}
    return {"contract": starts_reading.CONTRACT, "classes": ordered(every),
            "by_temperature": {k: ordered(v) for k, v in by_temperature.items() if v},
            "names": dict(starts_reading.CLASSES), "references": bool(starts_reading.table_references())}


def _decided(decisions) -> dict:
    from graph_scale_dynamics.reporting import starts_decided
    try:
        return starts_decided.decided(decisions)
    except Exception as exc:  # noqa: BLE001
        return {"contract": starts_decided.CONTRACT, "error": f"{type(exc).__name__}: {exc}"}


def every_chain_section(snapshot: dict) -> dict:
    try:
        from graph_scale_dynamics.observability.space_score import FROM_N
        specs = {str(c.get("candidate_id")): c.get("spec") for c in snapshot.get("candidates") or []
                 if isinstance(c.get("spec"), dict)}
        scores = law_scores(snapshot.get("measurements") or [], specs,
                            (snapshot.get("campaign") or {}).get("spec") if isinstance(snapshot.get("campaign"), dict) else None)
        spaces = Counter(name for score in scores.values() for name in score["spaces"])
        return {"contract": CONTRACT, "from_n": FROM_N, "laws_scored": len(scores),
                "spaces_at_the_top": dict(spaces), "starts_reading": starts_reading_classes(scores, specs),
                "scores": score_summary(scores),
                "laws": scores, "value_columns": list(VALUE_COLUMNS), **earned(snapshot.get("engine_decisions")),
                "starts_decided": _decided(snapshot.get("engine_decisions")),
                "reading": ("each law that reached a rung from from_n, scored chain by chain by "
                            "observability/space_score.py; d: the integer its probes sit nearest; space: a space at "
                            "every size judged; rungs: [n, distance, worst property]; given: the first given start. "
                            "starts_reading: every chain read against the others by observability/starts_reading.py, the "
                            "law's class at its largest size two chains read (at_n; top_dense where its top was read "
                            "by fewer), by_n: [class, groups] at each size from from_n, fates: each lattice's [fate, "
                            "kept] at at_n, trend: merging, splitting or steady; the section's starts_reading counts the "
                            "classes. earned_by: the decisions a given chain took for its law where every chain is decided "
                            "alike (decisions/every_chain.py), and the lattice that held where the "
                            "starts bought a size the chain from empty would not have (decisions/starts_rule.py). "
                            "starts_decided: what the starts decided against what d_s's rule would "
                            "have, as its own reading says. score: each law's score, observability/law_score.py: "
                            "100 times weight times depth, the weight 1 for the chain from empty, 0.6 for the random "
                            "start, 0.3 for a lattice start, the depth the largest size it was a geometry at on the "
                            "ladder 1,024 to 4,194,304, a seventh a size; by: who built it; scores: the section's "
                            "count and the laws that score most. values: each chain's means at each size, "
                            "in value_columns' order, for readings of other rules made from a bundle.")}
    except Exception as exc:  # noqa: BLE001
        return {"contract": CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
