from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np

RECORD_CONTRACT = "gsd-record-report-1"
REPLAY_SAMPLE = 2000
COST_ATTEMPTS = 20000


def _section(conn, name: str, read) -> dict:
    guarded = bool(getattr(conn, "in_transaction", False))
    if guarded:
        conn.execute(f"SAVEPOINT gsd_record_{name}")
    try:
        out = read()
    except Exception as exc:  # noqa: BLE001
        if guarded:
            conn.execute(f"ROLLBACK TO SAVEPOINT gsd_record_{name}")
        return {"error": f"{type(exc).__name__}: {exc}"}
    if guarded:
        conn.execute(f"RELEASE SAVEPOINT gsd_record_{name}")
    return out


def collect_record(repo, campaign_id: str) -> dict:
    conn = repo.conn
    draws = {str(r["outcome"]): int(r["c"]) for r in conn.execute(
        "SELECT outcome, COUNT(*) c FROM proposal_draws WHERE campaign_id=? GROUP BY outcome",
        (str(campaign_id),)).fetchall()}
    total = int(conn.execute("SELECT COUNT(*) c FROM engine_decisions WHERE campaign_id=?",
                             (str(campaign_id),)).fetchone()["c"] or 0)
    step = max(1, total // REPLAY_SAMPLE)
    sample = conn.execute(
        "SELECT * FROM (SELECT candidate_id, decision_id, at_n, next_n, action, rule, reason, priority, facts_json, "
        "inputs_json, row_number() OVER (ORDER BY decision_id) AS k FROM engine_decisions WHERE campaign_id=?) s "
        "WHERE s.k % ? = 0 OR s.rule IN ('depth_audit','salted') ORDER BY s.decision_id",
        (str(campaign_id), step)).fetchall()
    audited = [dict(r) for r in conn.execute(
        "SELECT candidate_id, at_n, next_n, decision_id FROM engine_decisions WHERE campaign_id=? "
        "AND rule IN ('depth_audit','salted')", (str(campaign_id),)).fetchall()]
    after = []
    if audited:
        laws = sorted({a["candidate_id"] for a in audited})
        marks = ",".join("?" for _ in laws)
        after = [dict(r) for r in conn.execute(
            f"SELECT candidate_id, at_n, action, rule, decision_id FROM engine_decisions WHERE campaign_id=? "
            f"AND candidate_id IN ({marks}) ORDER BY decision_id", (str(campaign_id), *laws)).fetchall()]
    bought = Counter()
    for r in conn.execute(
            "SELECT d2.rule AS rule FROM engine_decisions d1 JOIN engine_decisions d2 ON d2.campaign_id=d1.campaign_id "
            "AND d2.candidate_id=d1.candidate_id AND d2.at_n=d1.next_n AND d2.decision_id>d1.decision_id "
            "WHERE d1.campaign_id=? AND d1.rule='d_s_settled' AND d1.next_n<?",
            (str(campaign_id), 262144)).fetchall():
        bought[str(r["rule"])] += 1
    costs = []
    for r in conn.execute(
            "SELECT j.n AS n, a.resource_json AS resource FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=? AND j.kind='simulate' AND a.exit_code=0 AND a.resource_json LIKE ? "
            "ORDER BY a.finished_utc DESC LIMIT ?", (str(campaign_id), '%"cost"%', COST_ATTEMPTS)).fetchall():
        try:
            cost = (json.loads(r["resource"]) or {}).get("cost") or {}
        except (TypeError, ValueError):
            continue
        costs.append({"n": int(r["n"]), "cost": cost})
    from graph_scale_dynamics.research.gate_report import collect_gate
    from graph_scale_dynamics.reporting.reset_rules_report import collect_reset
    gate = _section(conn, "gate", lambda: collect_gate(conn, campaign_id))
    reset = _section(conn, "reset", lambda: collect_reset(conn, campaign_id))
    return {"draws": draws, "decisions_total": total, "replay_sample": [dict(r) for r in sample],
            "audited": audited, "after_audit": after, "bought_then": dict(bought), "costs": costs, "gate": gate,
            "reset": reset}


def collect_record_safely(repo, campaign_id: str) -> dict:
    conn = repo.conn
    guarded = bool(getattr(conn, "in_transaction", False))
    if guarded:
        conn.execute("SAVEPOINT gsd_record_report")
    try:
        out = collect_record(repo, campaign_id)
    except Exception as exc:  # noqa: BLE001
        if guarded:
            conn.execute("ROLLBACK TO SAVEPOINT gsd_record_report")
        return {"error": f"{type(exc).__name__}: {exc}"}
    if guarded:
        conn.execute("RELEASE SAVEPOINT gsd_record_report")
    return out


def _draws(draws: dict) -> dict:
    total = sum(draws.values())
    if not total:
        return {"draws": 0, "why": "no draws recorded (the ledger starts at 521)"}
    refused = {k: v for k, v in draws.items() if k != "admitted"}
    return {"draws": total, "admitted": draws.get("admitted", 0),
            "admitted_share": round(draws.get("admitted", 0) / total, 4),
            "refused_by_reason": {k: {"draws": v, "share": round(v / total, 4)}
                                  for k, v in sorted(refused.items(), key=lambda kv: -kv[1])}}


def _depth_audit(record: dict) -> dict:
    audited = record.get("audited") or []
    if not audited:
        return {"audited_decisions": 0, "why": ("no law has been let through past a park or hold yet (rule 7: the "
                                                "depth audit, each gate's own tenth)")}
    by_law = defaultdict(list)
    for row in record.get("after_audit") or []:
        by_law[row["candidate_id"]].append(row)
    outcome = Counter()
    for a in audited:
        later = next((r for r in by_law.get(a["candidate_id"], [])
                      if r["at_n"] == a["next_n"] and str(r["decision_id"]) > str(a["decision_id"])), None)
        outcome[str(later["rule"]) if later else "not decided yet"] += 1
    decided = sum(v for k, v in outcome.items() if k != "not decided yet")
    settled = outcome.get("d_s_settled", 0)
    bought = record.get("bought_then") or {}
    bought_total = sum(bought.values())
    return {"audited_decisions": len(audited), "next_rung_showed": dict(outcome),
            "audited_settled_share": (round(settled / decided, 4) if decided else None),
            "bought_settled_share": (round(bought.get("d_s_settled", 0) / bought_total, 4) if bought_total else None),
            "reading": ("the audited laws settle at the withheld rung about as often as the bought ones: the holds "
                        "cost depth" if decided and bought_total
                        and settled / decided >= 0.5 * bought.get("d_s_settled", 0) / bought_total
                        else "the audited laws seldom settle where a hold would have stopped them" if decided
                        else "no audited law has reported its next rung yet")}


def _replay(record: dict, order=None) -> dict:
    from graph_scale_dynamics.decisions.replay import replay_matches
    counts = Counter()
    mismatches = []
    for row in record.get("replay_sample") or []:
        row = dict(row, inputs=row.get("inputs_json"))
        try:
            verdict = replay_matches(row, order)
        except Exception as exc:  # noqa: BLE001
            verdict = {"matches": False, "differences": [f"{type(exc).__name__}: {exc}"], "same_rules": None}
        key = "no inputs" if verdict["matches"] is None else ("replays" if verdict["matches"] else "differs")
        counts[key] += 1
        if verdict["matches"] is False and len(mismatches) < 50:
            mismatches.append({"candidate_id": row["candidate_id"], "decision_id": row["decision_id"],
                               "rule": row["rule"], "same_rules": verdict["same_rules"],
                               "differences": verdict["differences"]})
    checked = counts["replays"] + counts["differs"]
    return {"decisions": record.get("decisions_total", 0), "sampled": sum(counts.values()),
            "counts": dict(counts), "replay_share": (round(counts["replays"] / checked, 4) if checked else None),
            "mismatches": mismatches}


def _costs(record: dict) -> dict:
    by_contract = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in record.get("costs") or []:
        cost = row["cost"]
        contract = str(cost.get("contract") or "attempt-cost-1")
        child, book = cost.get("child") or {}, cost.get("bookkeeping") or {}
        for side, part in (("child", child), ("bookkeeping", book)):
            if part.get("cpu_seconds") is not None:
                by_contract[contract][row["n"]][f"{side}_cpu_seconds"].append(float(part["cpu_seconds"]))
            io = part.get("io") or {}
            if io.get("write_bytes") is not None:
                by_contract[contract][row["n"]][f"{side}_write_bytes"].append(float(io["write_bytes"]))
    if not by_contract:
        return {"attempts": 0, "why": "no attempt carries a cost record"}
    out = {}
    for contract, by_n in sorted(by_contract.items()):
        rungs = {}
        for n in sorted(by_n):
            cols = by_n[n]
            rungs[str(n)] = {k: {"median": float(np.median(v)), "p95": float(np.percentile(v, 95)), "attempts": len(v)}
                             for k, v in sorted(cols.items())}
        out[contract] = {"attempts": sum(max((len(v) for v in cols.values()), default=0) for cols in by_n.values()),
                         "by_rung": rungs}
    newest = sorted(out)[-1]
    return {"attempts": len(record.get("costs") or []), "by_contract": out, "contract_read": newest,
            "by_rung": out[newest]["by_rung"],
            "note": "by_rung is the newest contract's; attempt-cost-2 is the first whose bookkeeping "
                    "excludes the child. PostgreSQL's own writes for an attempt are in its backends and not "
                    "split per attempt; tools/collect_disk_writes.py attributes them"}


CHAIN_EXTRAS = ("half_volume_radius", "kappa")


def _chain_extras(metrics: dict, chain: str) -> dict:
    from graph_scale_dynamics.domain.chain_list import of_chain, probes_of
    curvature = of_chain(metrics.get("curvature"), "given" if chain == "given" else "empty") or {}
    radius = ((probes_of(metrics, "given") or {}) if chain == "given" else metrics).get("half_volume_radius")
    return {"half_volume_radius": radius if isinstance(radius, (int, float)) else None,
            "kappa": curvature.get("mean") if curvature.get("measured") else None}


def _probe_table(per_n: dict, seeds: dict) -> dict:
    return {str(n): {probe: ({"mean": round(sum(v) / len(v), 4), "valid": len(v), "seeds": seeds[n]}
                             if (v := per_n[n].get(probe)) else {"mean": None, "valid": 0, "seeds": seeds[n]})
                     for probe in ("d_s", "d_V", "d_B", "d_w", *CHAIN_EXTRAS)}
            for n in sorted(seeds)}


def _given_probes_by_law(by_law: dict) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    out: dict = {}
    for law, rows in by_law.items():
        per_n: dict = defaultdict(lambda: defaultdict(list))
        seeds: dict = defaultdict(int)
        kept = [r for r in rows if not ((((r.get("metrics") or {}).get("health") or {}).get("sampler") or {})
                                        .get("sampler_audit"))]
        for row in select_best_runs(kept):
            from graph_scale_dynamics.domain.chain_list import probes_of
            probes = probes_of(row.get("metrics"), "given")
            if not isinstance(probes, dict):
                continue
            n = int(row["n"])
            seeds[n] += 1
            for probe in ("d_s", "d_V", "d_B", "d_w"):
                block = probes.get(probe) or {}
                if block.get("valid") and isinstance(block.get("value"), (int, float)):
                    per_n[n][probe].append(float(block["value"]))
            for name, value in _chain_extras(row.get("metrics") or {}, "given").items():
                if value is not None:
                    per_n[n][name].append(float(value))
        if seeds:
            out[law] = _probe_table(per_n, seeds)
    return out


def _from_empty_probes_by_law(by_law: dict) -> dict:
    from graph_scale_dynamics.measurements.analysis import select_best_runs
    from graph_scale_dynamics.scaleflow.one_shot import PROBE_VALUE
    out: dict = {}
    for law, rows in by_law.items():
        per_n: dict = defaultdict(lambda: defaultdict(list))
        seeds: dict = defaultdict(int)
        kept = [r for r in rows if not ((((r.get("metrics") or {}).get("health") or {}).get("sampler") or {})
                                        .get("sampler_audit"))]
        for row in select_best_runs(kept):
            metrics = row.get("metrics") or {}
            n = int(row["n"])
            seeds[n] += 1
            for probe, key in PROBE_VALUE.items():
                block = metrics.get(probe) or {}
                if block.get("valid") and isinstance(block.get(key), (int, float)):
                    per_n[n][probe].append(float(block[key]))
            for name, value in _chain_extras(metrics, "empty").items():
                if value is not None:
                    per_n[n][name].append(float(value))
        if seeds:
            out[law] = _probe_table(per_n, seeds)
    return out


def _structure(measurements: list[dict]) -> dict:
    from graph_scale_dynamics.research.structure_reading import law_structure
    by_law = defaultdict(list)
    for row in measurements or []:
        by_law[str(row.get("candidate_id"))].append(row)
    verdicts = Counter()
    agreement = Counter()
    finite, why = [], Counter()
    three = Counter()
    three_agree = []
    chains, given_only = [], []
    for law, rows in by_law.items():
        if max(int(r["n"]) for r in rows) < 16384:
            continue
        reading = law_structure(rows)
        given = law_structure(rows, chain="given")
        state = {True: "finite dimension", False: "no finite dimension", None: "not decidable yet"}[reading["finite_dimension"]]
        verdicts[state] += 1
        readings = reading.get("three_readings") or {}
        if reading["finite_dimension"]:
            three["finite by the rule"] += 1
            three["the bulk agrees"] += int(readings.get("bulk_finite") is True)
            three["the local d_s agrees"] += int(readings.get("local_agrees_with_gap") is True)
            three["all three agree"] += int(readings.get("agree") is True)
            if readings.get("agree") is True:
                three_agree.append({"candidate_id": law, **readings})
        from_empty_says, given_says = reading["finite_dimension"], given["finite_dimension"]
        words = {True: "finite dimension", False: "no finite dimension", None: "not decidable yet"}
        chains.append({"candidate_id": law, "top_n": max(int(r["n"]) for r in rows),
                       "empty": state, "given": words[given_says],
                       "from_empty_implied_d_s": reading.get("implied_spectral_dimension"),
                       "given_implied_d_s": given.get("implied_spectral_dimension")})
        if given_says and not from_empty_says:
            given_only.append({"candidate_id": law, "given_why": given.get("why"), "from_empty_why": reading.get("why"),
                              "given_implied_d_s": given.get("implied_spectral_dimension")})
        if from_empty_says is None or given_says is None:
            agreement["a chain not decidable yet"] += 1
        elif from_empty_says and given_says:
            agreement["both chains finite"] += 1
        elif not from_empty_says and not given_says:
            agreement["neither chain finite"] += 1
        else:
            agreement["chains disagree on structure"] += 1
        if reading["finite_dimension"]:
            finite.append({"candidate_id": law, "why": reading["why"],
                           "implied_spectral_dimension": reading.get("implied_spectral_dimension"),
                           "given_finite_dimension": given_says, "given_why": given.get("why"),
                           "given_exponents": given.get("exponents"), "three_readings": readings})
        elif reading["finite_dimension"] is None:
            why[reading["why"]] += 1
    return {"laws_read": sum(verdicts.values()), "verdicts": dict(verdicts), "finite": finite[:50],
            "given_probes_by_law": (given_chains := _given_probes_by_law(by_law)),
            "from_empty_probes_by_law": _from_empty_probes_by_law({law: by_law[law] for law in given_chains}),
            "chains_agreement": dict(agreement),
            "not_decidable_because": dict(why.most_common(5)),
            "chains_by_law": chains[:2000], "given_only_finite": given_only[:200],
            "three_readings": {"counts": {k: three[k] for k in ("finite by the rule", "the bulk agrees",
                                                               "the local d_s agrees", "all three agree")},
                               "all_three_agree": three_agree[:50],
                               "rule": "research/structure_reading.three_readings"},
            "rule": "research/structure_reading.py, its thresholds committed in resources/calibration/structure_thresholds.json: "
                    "the rule the structure gate decides with (rule 8), on both chains; what it "
                    "decided is `structure_gate`"}


def build_record_sections(record: dict | None, measurements: list[dict] | None = None,
                          phenotypes: list[dict] | None = None, chain_order=None) -> dict:
    from graph_scale_dynamics.research.gate_report import gate_section
    record = record or {}
    return {"contract": RECORD_CONTRACT, "draw_ledger": _draws(record.get("draws") or {}),
            "depth_audit": _depth_audit(record), "decision_record": _replay(record, chain_order),
            "cost_per_attempt": _costs(record), "structure_by_the_committed_rule": _structure(measurements),
            "structure_gate": gate_section(record.get("gate"), record.get("costs")),
            "plateau_then_break": _plateau_then_break(phenotypes, measurements),
            "d_s_shape": _d_s_shape(measurements), "chains_meeting": _chains_meeting(measurements),
            **_reset_sections(record.get("reset"), measurements)}


def _chains_meeting(measurements: list[dict] | None) -> dict:
    try:
        from graph_scale_dynamics.reporting.chains_meeting_report import chains_meeting
        return chains_meeting(measurements or [])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _d_s_shape(measurements: list[dict] | None) -> dict:
    try:
        from graph_scale_dynamics.research.d_s_shape_reading import record_section
        return record_section(measurements or [])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _plateau_then_break(phenotypes: list[dict] | None, measurements: list[dict] | None) -> dict:
    try:
        from graph_scale_dynamics.research.plateau_break import record_section
        return record_section(phenotypes or [], measurements or [])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _reset_sections(reset: dict | None, measurements: list[dict] | None) -> dict:
    try:
        from graph_scale_dynamics.reporting.reset_rules_report import reset_sections
        return reset_sections(reset, measurements)
    except Exception as exc:  # noqa: BLE001
        error = {"error": f"{type(exc).__name__}: {exc}"}
        return {"reset_rules": error, "spectral_windows": error, "compute_by_regime": error}
