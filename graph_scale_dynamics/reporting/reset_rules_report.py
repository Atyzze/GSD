from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict

RESET_REPORT_CONTRACT = "gsd-reset-rules-report-1"
CALIBRATED_EXPONENTIAL_AT_OR_BELOW = -2.0
CALIBRATED_POWER_LAW_AT_OR_ABOVE = 38.0
DIMENSION_NEEDS = 2.0
_RULES = ("unsettled", "unsettled_twice", "d_s_settled", "reading_lost", "depth_audit", "no_plateau",
          "second_rung", "no_reading", "no_second_rung", "salted")


def collect_reset(conn, campaign_id: str) -> dict:
    from graph_scale_dynamics.research.compute_by_regime import BY_RUNG_SQL, LAWS_SQL
    cid = str(campaign_id)
    marks = ",".join("?" for _ in _RULES)
    counts = [dict(r) for r in conn.execute(
        f"SELECT rule, at_n, COUNT(*) AS c FROM engine_decisions WHERE campaign_id=? AND rule IN ({marks}) "
        "GROUP BY rule, at_n", (cid, *_RULES)).fetchall()]
    across = [dict(r) for r in conn.execute(
        "SELECT candidate_id, decision_id, at_n, next_n, facts_json::jsonb->>'d_s_across' AS across "
        "FROM engine_decisions WHERE campaign_id=? AND rule='d_s_settled' AND left(facts_json,1)='{' "
        "AND facts_json LIKE ?", (cid, '%"d_s_across"%')).fetchall()]
    across = [r for r in across if r.get("across") not in (None, "", "null")]
    park_audits = [dict(r) for r in conn.execute(
        "SELECT candidate_id, decision_id, at_n, next_n FROM engine_decisions WHERE campaign_id=? "
        "AND left(facts_json,1)='{' AND ((rule='depth_audit' "
        "AND facts_json::jsonb#>>'{depth_audit,held_rule}'='unsettled_twice') OR (rule='salted' "
        "AND facts_json::jsonb#>>'{salted_from,rule}'='unsettled_twice'))", (cid,)).fetchall()]
    second = [dict(r) for r in conn.execute(
        "SELECT candidate_id, decision_id, at_n, next_n FROM engine_decisions WHERE campaign_id=? "
        "AND rule='second_rung'", (cid,)).fetchall()]
    followed = sorted({r["candidate_id"] for r in across + park_audits + second})
    after = []
    if followed:
        law_marks = ",".join("?" for _ in followed)
        after = [dict(r) for r in conn.execute(
            f"SELECT candidate_id, at_n, rule, decision_id FROM engine_decisions WHERE campaign_id=? "
            f"AND candidate_id IN ({law_marks}) ORDER BY decision_id", (cid, *followed)).fetchall()]
    regime_by_rung = [dict(r) for r in conn.execute(BY_RUNG_SQL, (cid, cid)).fetchall()]
    regime_laws = [dict(r) for r in conn.execute(LAWS_SQL, (cid, cid)).fetchall()]
    return {"counts": counts, "across": across, "park_audits": park_audits, "second": second, "after": after,
            "regime_by_rung": regime_by_rung, "regime_laws": regime_laws}


def _next_rung(rows: list[dict], after: list[dict]) -> Counter:
    by_law = defaultdict(list)
    for row in after:
        by_law[row["candidate_id"]].append(row)
    out = Counter()
    for row in rows:
        later = next((r for r in by_law.get(row["candidate_id"], [])
                      if r["at_n"] == row["next_n"] and str(r["decision_id"]) > str(row["decision_id"])), None)
        out[str(later["rule"]) if later else "not decided yet"] += 1
    return out


def _rules(record: dict) -> dict:
    counts = record.get("counts") or []
    by_rule: dict[str, dict] = defaultdict(dict)
    for row in counts:
        by_rule[str(row["rule"])][str(row["at_n"])] = int(row["c"])
    parks = sum(by_rule.get("unsettled_twice", {}).values())
    holds = sum(by_rule.get("unsettled", {}).values())
    across = record.get("across") or []
    across_by_n = Counter(str(r["at_n"]) for r in across)
    settled = sum(by_rule.get("d_s_settled", {}).values())
    return {
        "parks": {"laws_parked": parks, "by_rung": by_rule.get("unsettled_twice", {}),
                  "unsettled_holds": holds, "unsettled_holds_by_rung": by_rule.get("unsettled", {}),
                  "audited": len(record.get("park_audits") or []),
                  "audit_next_rung_showed": dict(_next_rung(record.get("park_audits") or [],
                                                            record.get("after") or [])),
                  "reading": "a park the audit then reads settled is a law rule 3 lost"},
        "settled_across_a_refused_rung": {
            "decisions": len(across), "of_all_d_s_settled": settled,
            "share": round(len(across) / settled, 4) if settled else None, "by_rung": dict(across_by_n),
            "next_rung_showed": dict(_next_rung(across, record.get("after") or []))},
        "second_look": {
            "decisions": len(record.get("second") or []),
            "by_rung": dict(Counter(str(r["at_n"]) for r in record.get("second") or [])),
            "next_rung_showed": dict(_next_rung(record.get("second") or [], record.get("after") or [])),
            "parked_unread": by_rule.get("no_reading", {}),
            "parked_at_the_plateau_rung": by_rule.get("no_second_rung", {}),
            "reading": "532's B: an unsettled law's rung before the park (second_rung) and what it "
                       "showed; laws with no reading at their top two rungs park (no_reading), and a look that "
                       "would be the plateau rung parks (no_second_rung)"},
        "decisions_by_rule_and_rung": {rule: dict(v) for rule, v in sorted(by_rule.items())},
    }


def _metrics(row: dict) -> dict:
    metrics = row.get("metrics")
    if metrics is None and isinstance(row.get("metrics_json"), str):
        try:
            metrics = json.loads(row["metrics_json"])
        except ValueError:
            metrics = None
    return metrics if isinstance(metrics, dict) else {}


def _zero_temperature(measurements: list[dict]) -> dict:
    rungs: dict[str, Counter] = defaultdict(Counter)
    given_chains = Counter()
    shares, multipliers = [], []
    for row in measurements:
        terminal = ((_metrics(row).get("health") or {}).get("rung_terminal")) or {}
        rest = terminal.get("at_rest")
        if not isinstance(rest, dict):
            continue
        rungs[str(row.get("n"))][str(terminal.get("classification"))] += 1
        for pair in (rest.get("pairs") or {}).values():
            if (pair or {}).get("reading"):
                given_chains[str(pair["reading"])] += 1
        for chain in (rest.get("chains") or {}).values():
            if isinstance(chain.get("late_descent_share"), (int, float)):
                shares.append(float(chain["late_descent_share"]))
        if isinstance(terminal.get("final_multiplier"), (int, float)):
            multipliers.append(int(terminal["final_multiplier"]))
    seeds = sum(sum(c.values()) for c in rungs.values())
    if not seeds:
        return {"seeds": 0, "why": "no zero-temperature seed in this campaign's measurements"}
    return {"seeds": seeds, "by_rung": {n: dict(c) for n, c in sorted(rungs.items(), key=lambda kv: int(kv[0]))},
            "given_at_rest": dict(given_chains),
            "late_descent_share_median": round(statistics.median(shares), 6) if shares else None,
            "final_multiplier_median": statistics.median(multipliers) if multipliers else None}


def _structural(measurements: list[dict]) -> dict:
    basis: dict[str, dict[str, dict[str, Counter]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    failed: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    seeds: Counter = Counter()
    for row in measurements:
        health = _metrics(row).get("health") or {}
        checkpoints = health.get("sampling_checkpoints") or []
        if not checkpoints:
            continue
        certificate = (checkpoints[-1] or {}).get("certificate") or {}
        thresholds = certificate.get("structural_thresholds") or {}
        split = certificate.get("structural_split") or {}
        rest = certificate.get("at_rest") or (health.get("rung_terminal") or {}).get("at_rest")
        regime = "zero_temperature" if isinstance(rest, dict) else "finite_temperature"
        if thresholds:
            seeds[regime] += 1
        for key, judged in thresholds.items():
            if not isinstance(judged, dict):
                continue
            basis[regime][key][str(row.get("n"))][str(judged.get("basis"))] += 1
            value = split.get(key)
            if isinstance(value, (int, float)) and isinstance(judged.get("threshold"), (int, float)) \
                    and float(value) > float(judged["threshold"]):
                failed[regime][key][str(judged.get("basis"))] += 1
    if not seeds:
        return {"seeds": 0, "why": "no seed records what set its thresholds"}

    def table(regime: str) -> dict:
        return {"seeds": seeds[regime],
                "judged_by": {key: {n: dict(c) for n, c in sorted(by_n.items(), key=lambda kv: int(kv[0]))}
                              for key, by_n in sorted(basis[regime].items())},
                "failed_on_the_last_chunk": {key: dict(c) for key, c in sorted(failed[regime].items())}}

    finite = table("finite_temperature")
    return {**finite,
            "zero_temperature": dict(table("zero_temperature"),
                                     reading="recorded and not compared: at zero temperature the certificate "
                                             "reads the chains at rest, not these gaps"),
            "reading": "finite-temperature seeds, where the thresholds decide. spread: 3 times the observable's own "
                       "spread set it; floor: the floor did; absolute: no spread could be read, so the limit before "
                       "529 did"}


def _wiring(measurements: list[dict]) -> dict:
    readings = Counter()
    wiring = Counter()
    only_wiring = 0
    for row in measurements:
        given = _metrics(row).get("meeting_reading") or {}
        if not given.get("reading"):
            continue
        readings[str(given["reading"])] += 1
        observables = given.get("observables") or {}
        triangles = observables.get("triangles_per_node")
        if not isinstance(triangles, dict):
            continue
        wiring["agree" if triangles.get("agree") else "disagree"] += 1
        others = [o for k, o in observables.items() if k != "triangles_per_node" and isinstance(o, dict)]
        if not triangles.get("agree") and others and all(o.get("agree") for o in others):
            only_wiring += 1
    return {"seed_readings": dict(readings), "triangles_per_node": dict(wiring),
            "disagree_on_wiring_alone": only_wiring,
            "reading": "disagree_on_wiring_alone counts seeds whose energy and mean degree agree and whose "
                       "wiring does not"}


def band(delta) -> str:
    if not isinstance(delta, (int, float)):
        return "no comparison"
    if delta > CALIBRATED_POWER_LAW_AT_OR_ABOVE:
        return "calibrated power law (lattice-like)"
    if delta > DIMENSION_NEEDS:
        return "reported as a dimension"
    if delta > 0:
        return "power law ahead, refused for not winning by enough"
    if delta > CALIBRATED_EXPONENTIAL_AT_OR_BELOW:
        return "exponential ahead, inside the uncalibrated band"
    return "calibrated exponential (Erdos-Renyi-like)"


def _spectral(measurements: list[dict]) -> dict:
    from graph_scale_dynamics.calibration import committed_d_s_margin_bands
    from graph_scale_dynamics.calibration import place_d_s_margin as place
    table = committed_d_s_margin_bands()
    status: dict[str, Counter] = defaultdict(Counter)
    bands: dict[str, Counter] = defaultdict(Counter)
    measured: dict[str, Counter] = defaultdict(Counter)
    whole: dict[str, Counter] = defaultdict(Counter)
    for row in measurements:
        metrics = _metrics(row)
        probe = metrics.get("d_s") or {}
        if not probe:
            continue
        n = str(row.get("n"))
        valid = bool(probe.get("valid"))
        withheld = not valid and isinstance(probe.get("would_have_reported"), (int, float))
        status[n]["reported" if valid else "withheld" if withheld else "refused before a value"] += 1
        evidence = probe.get("diffusive_window_evidence") or (probe.get("window") or {}).get(
            "diffusive_window_evidence") or {}
        delta = evidence.get("delta_aicc")
        bands[n][band(delta)] += 1
        measured[n][place(delta, int(row.get("n") or 0), table)] += 1
        wr = metrics.get("d_s_whole_range") or {}
        if wr.get("whole_range_comparable") and isinstance(delta, (int, float)):
            plateau = float(delta) > DIMENSION_NEEDS
            full = bool(wr.get("whole_range_is_power_law"))
            whole[n]["stays reported" if plateau and full else "reported now, refused on the whole range"
                     if plateau else "refused now, reported on the whole range" if full else "stays refused"] += 1
    order = lambda d: {n: dict(c) for n, c in sorted(d.items(), key=lambda kv: int(kv[0]))}  # noqa: E731
    totals = Counter()
    for c in whole.values():
        totals.update(c)
    return {"d_s_by_rung": order(status), "margin_bands_by_rung": order(bands),
            "against_the_measured_bands": {
                "by_rung": order(measured),
                "table": (None if table is None else {"computed_utc": table.get("computed_utc"),
                                                      "max_n": table.get("max_n"), "seeds": table.get("seeds")}),
                "reading": ("each reported d_s's plateau margin against the range the calibration's geometry "
                            "families and its families with no finite dimension score at the nearest survey "
                            "rung (resources/calibration/d_s_margin_bands.json, tools/calibrate_margins.py)")},
            "whole_range_test": {"judged": sum(totals.values()), "totals": dict(totals), "by_rung": order(whole),
                                 "why": (None if totals else "no analysis records the whole-range comparison yet")},
            "reading": "margins are AICc(gap decay) - AICc(power law); a dimension needs more than 2. The +38 and -2 "
                       "lines of margin_bands_by_rung are the estimator's comment, which the calibration families "
                       "do not bear out (532): against_the_measured_bands reads the same margins against theirs"}


def reset_sections(record: dict | None, measurements: list[dict] | None) -> dict:
    from graph_scale_dynamics.research.compute_by_regime import summarise
    record = record or {}
    measurements = measurements or []
    if record.get("error"):
        rules = {"error": record["error"]}
        regime = {"error": record["error"]}
    else:
        rules = _rules(record)
        regime = summarise(record.get("regime_by_rung") or [], record.get("regime_laws") or [])
    return {
        "reset_rules": {"contract": RESET_REPORT_CONTRACT, **rules,
                        "zero_temperature": _zero_temperature(measurements),
                        "given_structural_thresholds": _structural(measurements),
                        "given_wiring": _wiring(measurements)},
        "spectral_windows": _spectral(measurements),
        "compute_by_regime": regime,
    }
