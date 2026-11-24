from __future__ import annotations

import json


def live_work_candidate_ids(repo, campaign_id: str, *, queued_limit: int = 96) -> list[str]:
    ordered: list[str] = []
    seen: set = set()

    def take(sql: str) -> None:
        for row in repo.conn.execute(sql, (str(campaign_id),)).fetchall():
            candidate = row["candidate_id"]
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)

    take("SELECT DISTINCT candidate_id FROM jobs WHERE campaign_id=? AND status='leased'")
    take("SELECT DISTINCT candidate_id FROM analysis_queue WHERE campaign_id=? "
         "AND status='leased'")
    take("SELECT DISTINCT candidate_id FROM jobs WHERE campaign_id=? AND status='queued' "
         f"LIMIT {int(queued_limit)}")
    return ordered


def chains_per_seed(spec: dict | None) -> int:
    sampling = (spec or {}).get("sampling_contract") or {}
    starts = sampling.get("given_starts")
    if isinstance(starts, list) and starts:
        return 1 + len(starts)
    if any(sampling.get(key) for key in ("given_start", "given_start_by_law", "given_start_rule")):
        return 2
    return 1


AT_THE_FALLBACK = 0.98


def seeds_per_law(spec: dict | None) -> int | None:
    seeds = (((spec or {}).get("engine") or {}).get("policy") or {}).get("seeds")
    return int(seeds) if isinstance(seeds, int) and not isinstance(seeds, bool) and seeds > 0 else None


def rung_work_budget(spec: dict | None):
    from graph_scale_dynamics.scheduling.limits import estimated_seconds, work_budget

    def budget(n: int) -> tuple[int | None, float | None]:
        try:
            seconds = estimated_seconds(spec or {}, int(n))
            return int(work_budget(spec or {}, int(n))), (round(float(seconds), 1) if seconds else None)
        except Exception:  # noqa: BLE001
            return None, None
    return budget


def rung_fallback_reservation_bytes(spec: dict | None):
    from graph_scale_dynamics.scheduling.memory import fallback_reservation_bytes

    def fallback(n: int) -> int | None:
        try:
            return int(fallback_reservation_bytes(spec or {}, int(n), "simulation"))
        except Exception:  # noqa: BLE001
            return None
    return fallback


def rung_distribution_for(repo, campaign_id: str, duration_samples=None, spec: dict | None = None) -> list[dict]:
    by_n: dict[int, dict] = {}
    if spec is None:
        spec = (repo.campaign(str(campaign_id)) or {}).get("spec") or {}
    chains = chains_per_seed(spec)
    seeds = seeds_per_law(spec)
    budget_of = rung_work_budget(spec)
    fallback_of = rung_fallback_reservation_bytes(spec)

    def bucket(n: int) -> dict:
        return by_n.setdefault(int(n), {"n": int(n), "running": 0, "queued": 0, "measured": 0,
                                "analysing": 0, "queued_analyses": 0,
                                "running_laws": 0, "queued_laws": 0, "analysing_laws": 0,
                                "queued_analyses_laws": 0, "budget_ended_laws": 0,
                                "graphs": 0, "chains": 0, "chains_per_seed": chains, "seeds_per_law": seeds,
                                "completed": 0, "abandoned": 0,
                                "simulations": 0,
                                "interrupted": 0, "interrupted_seconds": 0.0, "budget_ended_seeds": 0,
                                "done_without_artifact": 0,
                                "stopped": 0, "stopped_by_rule": {}, "done": 0, "done_by_rule": {},
                                "left": 0, "left_by_rule": {}, "parked_by_rule": {}, "still_here": 0,
                                "probe_timed_measurements": 0, "probe_seconds_total": 0.0,
                                "d_s_median_seconds": None, "d_s_p90_seconds": None,
                                **{f"{probe}_{tag}_seconds": None for probe in ("d_s", "d_V", "d_B", "d_w")
                                   for tag in ("p05", "p95")},
                                **{f"{probe}_{tag}": 0 for probe in ("d_s", "d_V", "d_B", "d_w")
                                   for tag in ("ran", "timed")},
                                **{f"{probe}_ran_median_seconds": None for probe in ("d_s", "d_V", "d_B", "d_w")},
                                "d_V_median_seconds": None,
                                "d_B_median_seconds": None, "d_w_median_seconds": None,
                                "d_s_seconds_total": 0.0, "d_V_seconds_total": 0.0,
                                "d_B_seconds_total": 0.0, "d_w_seconds_total": 0.0,
                                "kappa_median_seconds": None, "kappa_seconds_total": 0.0,
                                "kappa_timed_measurements": 0,
                                "peak_bytes_p05": None, "peak_bytes_p95": None,
                                "peak_bytes_median": None, "peak_bytes_p90": None,
                                "peak_bytes_min": None, "peak_bytes_max": None,
                                "reserved_bytes_median": None, "reserved_over_observed": None,
                                "memory_timed_attempts": 0,
                                "geometry_median_seconds": None, "geometry_p90_seconds": None,
                                "attempts": 0, "median_seconds": None,
                                "simulation_seconds_total": 0.0,
                                "rung_seconds_total": 0.0, "compute_share": None,
                                "p05_seconds": None, "p95_seconds": None,
                                "p90_seconds": None, "max_seconds": None,
                                "min_seconds": None, "max_unfinished": False, "longest_unfinished_seconds": None,
                                "running_seconds": 0.0, "laws": 0,
                                "work_budget": budget_of(int(n))[0], "budget_seconds": budget_of(int(n))[1],
                                "fallback_reservation_bytes": fallback_of(int(n))})

    for row in repo.conn.execute(
            "SELECT n,status,COUNT(*) AS c,COUNT(DISTINCT candidate_id) AS laws FROM jobs WHERE campaign_id=? "
            "AND kind='simulate' AND status IN ('queued','leased') GROUP BY n,status", (str(campaign_id),)):
        entry = bucket(row["n"])
        kind = "queued" if str(row["status"]) == "queued" else "running"
        entry[kind] += int(row["c"])
        entry[f"{kind}_laws"] += int(row["laws"])
    from graph_scale_dynamics.observability.live_panel import age_seconds
    from graph_scale_dynamics.observability.live_panel import resume_note_of, resumed_seconds_of

    def unfinished(entry: dict, seconds: float) -> None:
        entry["longest_unfinished_seconds"] = round(max(seconds, entry["longest_unfinished_seconds"] or 0.0), 1)

    from graph_scale_dynamics.domain.model import interrupted_sql
    interrupted_runs = repo.interrupted_run_seconds(str(campaign_id))
    for row in repo.conn.execute(
            "SELECT j.n,j.job_id,a.started_utc FROM jobs j JOIN attempts a ON a.job_id=j.job_id "
            "WHERE j.campaign_id=? AND j.kind='simulate' AND j.status='leased' "
            "AND a.finished_utc IS NULL", (str(campaign_id),)):
        entry, age = bucket(row["n"]), age_seconds(row["started_utc"])
        entry["running_seconds"] = round(entry["running_seconds"] + age, 1)
        unfinished(entry, age + max(float(resumed_seconds_of(row["job_id"], row["started_utc"]) or 0.0),
                                    interrupted_runs.get(str(row["job_id"]), 0.0)))
    for row in repo.conn.execute(
            "SELECT j.n,j.job_id FROM jobs j WHERE j.campaign_id=? AND j.kind='simulate' AND j.status='queued' "
            f"AND EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.job_id AND {interrupted_sql('a')})",
            (str(campaign_id),)):
        saved = max(float((resume_note_of(row["job_id"]) or {}).get("seconds_spent") or 0.0),
                    interrupted_runs.get(str(row["job_id"]), 0.0))
        if saved > 0.0:
            unfinished(bucket(row["n"]), saved)
    for row in repo.conn.execute(
            "SELECT n,COUNT(DISTINCT candidate_id) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' "
            "GROUP BY n", (str(campaign_id),)):
        bucket(row["n"])["laws"] = int(row["c"])
    for row in repo.conn.execute(
            "SELECT n,status,COUNT(*) AS c,COUNT(DISTINCT candidate_id) AS laws FROM analysis_queue WHERE campaign_id=? "
            "AND status IN ('queued','leased') GROUP BY n,status", (str(campaign_id),)):
        entry = bucket(row["n"])
        kind = "queued_analyses" if str(row["status"]) == "queued" else "analysing"
        entry[kind] += int(row["c"])
        entry[f"{kind}_laws"] += int(row["laws"])
    for row in repo.conn.execute(
            "SELECT n,COUNT(*) AS c FROM rung_summaries WHERE campaign_id=? GROUP BY n",
            (str(campaign_id),)):
        bucket(row["n"])["measured"] = int(row["c"])

    for row in repo.conn.execute(
            "SELECT n,COUNT(*) AS graphs,SUM(jobs) AS simulations,"
            "COUNT(*) FILTER (WHERE done) AS completed,"
            "COUNT(*) FILTER (WHERE bare AND NOT done) AS done_without_artifact,"
            "COUNT(*) FILTER (WHERE abandoned) AS abandoned "
            "FROM (SELECT n,candidate_id,seed,COUNT(*) AS jobs,"
            "bool_or(status='done' AND result_artifact IS NOT NULL) AS done,"
            "bool_or(status='done' AND result_artifact IS NULL) AS bare,"
            "bool_and(status IN ('cancelled','failed','lost')) AS abandoned "
            "FROM jobs WHERE campaign_id=? AND kind='simulate' GROUP BY n,candidate_id,seed) AS graph "
            "GROUP BY n", (str(campaign_id),)):
        entry = bucket(row["n"])
        entry["graphs"] = int(row["graphs"] or 0)
        entry["chains"] = entry["graphs"] * chains
        entry["simulations"] = int(row["simulations"] or 0)
        entry["completed"] = int(row["completed"] or 0)
        entry["done_without_artifact"] = int(row["done_without_artifact"] or 0)
        entry["abandoned"] = int(row["abandoned"] or 0)

    for row in repo.conn.execute(
            "SELECT j.n,COUNT(*) AS c,COALESCE(SUM(a.wall_seconds),0) AS s FROM attempts a "
            "JOIN jobs j ON j.job_id=a.job_id "
            f"WHERE j.campaign_id=? AND j.kind='simulate' AND {interrupted_sql('a')} GROUP BY j.n",
            (str(campaign_id),)):
        entry = bucket(row["n"])
        entry["interrupted"] = int(row["c"] or 0)
        entry["interrupted_seconds"] = round(float(row["s"] or 0.0), 1)

    cut: dict[int, set] = {}
    for row in repo.conn.execute(
            "SELECT candidate_id,facts_json::jsonb#>'{budget_ended}' AS cut FROM engine_decisions "
            "WHERE campaign_id=? AND left(facts_json,1)='{' AND facts_json LIKE ?",
            (str(campaign_id), '%"budget_ended"%')):
        mark = row["cut"]
        if isinstance(mark, str):
            try:
                mark = json.loads(mark)
            except ValueError:
                mark = None
        if isinstance(mark, dict) and mark.get("at_n") is not None:
            cut.setdefault(int(mark["at_n"]), set()).update(
                (str(row["candidate_id"]), int(seed)) for seed in mark.get("seeds") or [])
    for n, seeds in cut.items():
        bucket(n)["budget_ended_seeds"] = len(seeds)
        bucket(n)["budget_ended_laws"] = len({law for law, _seed in seeds})
    for row in repo.conn.execute(
            "SELECT top.n,d.rule,d.action,COUNT(*) AS c,COUNT(*) FILTER (WHERE c.state='PARKED') AS parked "
            "FROM (SELECT candidate_id,MAX(n) AS n FROM jobs WHERE campaign_id=? AND kind='simulate' "
            "GROUP BY candidate_id) AS top "
            "JOIN engine_decisions_latest d ON d.campaign_id=? AND d.candidate_id=top.candidate_id "
            "LEFT JOIN campaign_candidates c ON c.campaign_id=d.campaign_id AND c.candidate_id=d.candidate_id "
            "WHERE d.action IN ('stop','done') GROUP BY top.n,d.rule,d.action",
            (str(campaign_id), str(campaign_id))):
        entry, rule, laws = bucket(row["n"]), str(row["rule"]), int(row["c"])
        entry["left"] += laws
        entry["left_by_rule"][rule] = entry["left_by_rule"].get(rule, 0) + laws
        if str(row["action"]) == "stop":
            entry["stopped"] += laws
            entry["stopped_by_rule"][rule] = laws
        else:
            entry["done"] += laws
            entry["done_by_rule"][rule] = entry["done_by_rule"].get(rule, 0) + laws
        if int(row["parked"] or 0):
            entry["parked_by_rule"][rule] = int(row["parked"])
    for row in repo.conn.execute(
            "SELECT top.n,COUNT(*) AS c FROM (SELECT candidate_id,MAX(n) AS n FROM jobs "
            "WHERE campaign_id=? AND kind='simulate' GROUP BY candidate_id) AS top "
            "LEFT JOIN engine_decisions_latest d ON d.campaign_id=? AND d.candidate_id=top.candidate_id "
            "WHERE d.candidate_id IS NULL OR d.action NOT IN ('stop','done') GROUP BY top.n",
            (str(campaign_id), str(campaign_id))):
        bucket(row["n"])["still_here"] = int(row["c"])

    for row in repo.conn.execute(
            "SELECT n,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY probe_seconds_d_s) med_ds,"
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY probe_seconds_d_s) p90_ds,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY probe_seconds_d_v) med_dv,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY probe_seconds_d_b) med_db,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY probe_seconds_d_w) med_dw,"
            + "".join(f"percentile_cont({q}) WITHIN GROUP (ORDER BY probe_seconds_{c}) {tag}_{c},"
                      for c in ("d_s", "d_v", "d_b", "d_w") for q, tag in ((0.05, "p05"), (0.95, "p95")))
            + "".join(f"percentile_cont(0.5) WITHIN GROUP (ORDER BY probe_seconds_{c}) "
                      f"FILTER (WHERE probe_seconds_{c}>0) ran_med_{c},"
                      f"COUNT(*) FILTER (WHERE probe_seconds_{c}>0) ran_{c},"
                      f"COUNT(probe_seconds_{c}) timed_{c},"
                      for c in ("d_s", "d_v", "d_b", "d_w")) +
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY (COALESCE(probe_seconds_d_b,0)"
            "+COALESCE(probe_seconds_d_w,0))) FILTER (WHERE probe_seconds_d_b IS NOT NULL "
            "OR probe_seconds_d_w IS NOT NULL) med_geo,"
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY (COALESCE(probe_seconds_d_b,0)"
            "+COALESCE(probe_seconds_d_w,0))) FILTER (WHERE probe_seconds_d_b IS NOT NULL "
            "OR probe_seconds_d_w IS NOT NULL) p90_geo,"
            "SUM(COALESCE(probe_seconds_d_s,0)) sum_ds,"
            "SUM(COALESCE(probe_seconds_d_v,0)) sum_dv,"
            "SUM(COALESCE(probe_seconds_d_b,0)) sum_db,"
            "SUM(COALESCE(probe_seconds_d_w,0)) sum_dw,"
            "COUNT(probe_seconds_d_s) timed,"
            "SUM(COALESCE(probe_seconds_d_s,0)+COALESCE(probe_seconds_d_v,0)"
            "+COALESCE(probe_seconds_d_b,0)+COALESCE(probe_seconds_d_w,0)) total "
            "FROM measurements WHERE campaign_id=? GROUP BY n", (str(campaign_id),)):
        entry = bucket(row["n"])
        entry["probe_timed_measurements"] = int(row["timed"] or 0)
        entry["probe_seconds_total"] = round(float(row["total"] or 0.0), 1)
        for key, column in (("d_s_seconds_total", "sum_ds"), ("d_V_seconds_total", "sum_dv"),
                            ("d_B_seconds_total", "sum_db"), ("d_w_seconds_total", "sum_dw")):
            entry[key] = round(float(row[column] or 0.0), 1)
        for probe, c in (("d_s", "d_s"), ("d_V", "d_v"), ("d_B", "d_b"), ("d_w", "d_w")):
            for tag in ("p05", "p95"):
                value = row[f"{tag}_{c}"]
                entry[f"{probe}_{tag}_seconds"] = round(float(value), 3) if value is not None else None
            entry[f"{probe}_ran"] = int(row[f"ran_{c}"] or 0)
            entry[f"{probe}_timed"] = int(row[f"timed_{c}"] or 0)
            ran = row[f"ran_med_{c}"]
            entry[f"{probe}_ran_median_seconds"] = round(float(ran), 3) if ran is not None else None
        for key, column in (("d_s_median_seconds", "med_ds"), ("d_s_p90_seconds", "p90_ds"),
                            ("d_V_median_seconds", "med_dv"),
                            ("d_B_median_seconds", "med_db"),
                            ("d_w_median_seconds", "med_dw"),
                            ("geometry_median_seconds", "med_geo"),
                            ("geometry_p90_seconds", "p90_geo")):
            entry[key] = (round(float(row[column]), 3) if row[column] is not None else None)

    for row in repo.conn.execute(
            "SELECT j.n AS n,"
            "percentile_cont(0.05) WITHIN GROUP (ORDER BY COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) p05_peak,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) med_peak,"
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) p90_peak,"
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) p95_peak,"
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY a.memory_reservation_bytes) med_res,"
            "MIN(COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) min_peak,"
            "MAX(COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) max_peak,"
            "COUNT(COALESCE(a.peak_pss_bytes,a.peak_rss_bytes)) timed "
            "FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=? AND COALESCE(a.peak_pss_bytes,a.peak_rss_bytes) IS NOT NULL "
            f"AND NOT {interrupted_sql('a')} GROUP BY j.n", (str(campaign_id),)):
        entry = bucket(row["n"])
        entry["memory_timed_attempts"] = int(row["timed"] or 0)
        peak = row["med_peak"]
        reserved = row["med_res"]
        entry["peak_bytes_median"] = int(peak) if peak is not None else None
        entry["peak_bytes_p90"] = int(row["p90_peak"]) if row["p90_peak"] is not None else None
        entry["peak_bytes_p05"] = int(row["p05_peak"]) if row["p05_peak"] is not None else None
        entry["peak_bytes_p95"] = int(row["p95_peak"]) if row["p95_peak"] is not None else None
        entry["peak_bytes_min"] = int(row["min_peak"]) if row["min_peak"] is not None else None
        entry["peak_bytes_max"] = int(row["max_peak"]) if row["max_peak"] is not None else None
        entry["reserved_bytes_median"] = int(reserved) if reserved is not None else None
        entry["reserved_over_observed"] = (
            round(float(reserved) / float(peak), 3)
            if peak and reserved and float(peak) > 0 else None)
    for n, entry in by_n.items():
        price = entry.get("fallback_reservation_bytes")
        if not entry.get("memory_timed_attempts") or not price:
            continue
        found = repo.conn.execute(
            "SELECT COUNT(*) AS c FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
            "WHERE j.campaign_id=? AND j.n=? AND COALESCE(a.peak_pss_bytes,a.peak_rss_bytes) IS NOT NULL "
            f"AND NOT {interrupted_sql('a')} AND a.memory_reservation_bytes>=?",
            (str(campaign_id), int(n), int(AT_THE_FALLBACK * float(price)))).fetchone()
        entry["reserved_at_fallback"] = int((found or {})["c"] or 0) if found else 0

    walls, runs = attempt_walls_and_runs(repo, campaign_id, duration_samples, interrupted_runs)
    for n, values in walls.items():
        entry = bucket(n)
        entry["attempts"] = len(values)
        entry["simulation_seconds_total"] = round(sum(values), 1)
    for n, values in runs.items():
        values.sort()
        entry = bucket(n)
        entry["min_seconds"] = round(values[0], 1)
        entry["p05_seconds"] = round(_quantile(values, 0.05), 1)
        entry["median_seconds"] = round(_quantile(values, 0.50), 1)
        entry["p90_seconds"] = round(_quantile(values, 0.90), 1)
        entry["p95_seconds"] = round(_quantile(values, 0.95), 1)
        entry["max_seconds"] = round(values[-1], 1)
    for entry in by_n.values():
        longest = entry["longest_unfinished_seconds"]
        if longest is not None and (entry["max_seconds"] is None or longest > float(entry["max_seconds"])):
            entry["max_seconds"], entry["max_unfinished"] = longest, True

    from graph_scale_dynamics.observability.kappa_seconds import ladder_cells
    try:
        kappa = ladder_cells(repo, campaign_id)
    except Exception:  # noqa: BLE001
        kappa = {}
    for n, cells in kappa.items():
        if n not in by_n:
            continue
        entry = by_n[n]
        entry.update(cells)
        entry["probe_seconds_total"] = round(float(entry["probe_seconds_total"]) + cells["kappa_seconds_total"], 1)
    rows = [by_n[n] for n in sorted(by_n)]
    for entry in rows:
        entry["rung_seconds_total"] = round(
            float(entry["simulation_seconds_total"]) + float(entry["probe_seconds_total"]), 1)
    campaign_total = sum(float(e["rung_seconds_total"]) for e in rows)
    for entry in rows:
        entry["compute_share"] = (round(float(entry["rung_seconds_total"]) / campaign_total, 4)
                                  if campaign_total > 0 else None)
    return rows


def attempt_walls_and_runs(repo, campaign_id: str, duration_samples,
                           interrupted: dict | None = None) -> tuple[dict, dict]:
    walls: dict[int, list[float]] = {}
    last: dict[str, tuple[int, int, int]] = {}
    for key, rows in (duration_samples or {}).items():
        n = int(key[0] if isinstance(key, tuple) else key)
        for row in rows:
            value = row.get("wall_seconds") if isinstance(row, dict) else None
            if value is None:
                continue
            walls.setdefault(n, []).append(float(value))
            job = row.get("job_id")
            if job is not None:
                number = int(row.get("number") or 0)
                if str(job) not in last or number >= last[str(job)][2]:
                    last[str(job)] = (n, len(walls[n]) - 1, number)
    runs = {n: list(values) for n, values in walls.items()}
    if last:
        for job, seconds in repo.resumed_run_seconds(str(campaign_id)).items():
            if job in last:
                n, index, _number = last[job]
                runs[n][index] = max(seconds, runs[n][index])
        stopped = repo.interrupted_run_seconds(str(campaign_id)) if interrupted is None else interrupted
        for job, seconds in stopped.items():
            if job in last:
                n, index, _number = last[job]
                runs[n][index] = max(runs[n][index], walls[n][index] + seconds)
    return walls, runs


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1,
                       int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]
