from __future__ import annotations

from datetime import datetime, timedelta, timezone

from graph_scale_dynamics.domain.model import interrupted_sql

WORK_LEFT_CONTRACT = "gsd-work-left-1"
RECENT_ATTEMPTS = 200
PACE_WINDOW_SECONDS = 3600.0

_DURATIONS = (
    "SELECT campaign_id,n,wall_seconds,exit_code FROM (SELECT j.campaign_id,j.n,a.wall_seconds,a.exit_code,"
    "ROW_NUMBER() OVER (PARTITION BY j.campaign_id,j.n ORDER BY a.finished_utc DESC) AS r FROM attempts a "
    "JOIN jobs j ON j.job_id=a.job_id WHERE j.kind='simulate' AND a.finished_utc IS NOT NULL "
    f"AND NOT {interrupted_sql('a')}) recent WHERE r<=?")
_OVERLAP = ("GREATEST(0,EXTRACT(EPOCH FROM (LEAST(COALESCE({a}.finished_utc,?)::timestamptz,?::timestamptz)"
            "-GREATEST({a}.started_utc::timestamptz,?::timestamptz))))")
_SIMULATION_PACE = (
    f"SELECT j.campaign_id,SUM({_OVERLAP.format(a='a')}) AS s FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
    "WHERE (a.finished_utc>=? OR (a.finished_utc IS NULL AND j.status='leased')) GROUP BY j.campaign_id")
_ANALYSIS_PACE = (
    f"SELECT a.campaign_id,SUM({_OVERLAP.format(a='a')}) AS s FROM analysis_attempts a WHERE a.finished_utc>=? "
    "OR (a.finished_utc IS NULL AND EXISTS (SELECT 1 FROM analysis_queue q WHERE q.campaign_id=a.campaign_id "
    "AND q.input_artifact=a.input_artifact AND q.analysis_version=a.analysis_version AND q.status='leased')) "
    "GROUP BY a.campaign_id")
_ANALYSIS_SECONDS = "SELECT campaign_id,COALESCE(SUM(wall_seconds),0) AS s FROM analysis_attempts GROUP BY campaign_id"


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def scan(repo, *, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    end, start = _utc(moment), _utc(moment - timedelta(seconds=PACE_WINDOW_SECONDS))
    durations: dict = {}
    for row in repo.conn.execute(_DURATIONS, (RECENT_ATTEMPTS,)).fetchall():
        durations.setdefault(str(row["campaign_id"]), {}).setdefault(int(row["n"]), []).append(
            {"wall_seconds": row["wall_seconds"], "exit_code": row["exit_code"]})
    pace: dict = {}
    for sql in (_SIMULATION_PACE, _ANALYSIS_PACE):
        for row in repo.conn.execute(sql, (end, end, start, start)).fetchall():
            pace[str(row["campaign_id"])] = pace.get(str(row["campaign_id"]), 0.0) + float(row["s"] or 0.0)
    analysis = {str(row["campaign_id"]): float(row["s"] or 0.0)
                for row in repo.conn.execute(_ANALYSIS_SECONDS).fetchall()}
    return {"durations": durations, "pace_core_seconds": pace, "analysis_core_seconds": analysis,
            "window": [start, end]}


def seed_seconds(spec: dict, n: int, rows: list[dict]) -> tuple[float | None, bool]:
    from graph_scale_dynamics.scheduling.rung_eta import _ceiling, rung_duration
    ceiling = _ceiling(spec, n)
    estimate = rung_duration(rows, spec=spec, ceiling=ceiling)
    if estimate.get("median_seconds") is not None:
        return float(estimate["median_seconds"]), False
    if estimate.get("exceeds_seconds") is not None:
        return float(estimate["exceeds_seconds"]), True
    return None, True


def _sizes_declared(spec: dict) -> list[int]:
    policy = ((spec.get("engine") or {}).get("policy") or {})
    budgeted = [row[0] for row in policy.get("work_budgets") or [] if isinstance(row, (list, tuple)) and row]
    return sorted({int(n) for n in [*(spec.get("ladder") or []), *budgeted] if int(n) > 0})


def sizes_to_come(*, climbing_by_n: dict | None, measured_by_n: dict | None, bought_by_n: dict | None,
                  durations_by_n: dict | None, seeds: int | None, ladder: list | None = None) -> dict:
    climbing = {int(n): int(c) for n, c in (climbing_by_n or {}).items() if int(c) > 0}
    measured = {int(n): int(c) for n, c in (measured_by_n or {}).items()}
    bought = {int(n): int(c) for n, c in (bought_by_n or {}).items()}
    sizes = sorted(set(climbing) | set(measured) | set(bought) | {int(n) for n in ladder or [] if int(n) > 0})
    from graph_scale_dynamics.scheduling.rung_eta import MIN_SAMPLES
    mean = {}
    for n in sizes:
        walls = [float(row["wall_seconds"]) for row in (durations_by_n or {}).get(n) or []
                 if row.get("wall_seconds") is not None]
        if len(walls) >= MIN_SAMPLES:
            mean[n] = sum(walls) / len(walls)
    seconds, unpriced = 0.0, set()
    for n, laws in sorted(climbing.items()):
        share, below = 1.0, n
        for size in (s for s in sizes if s > n):
            if not measured.get(below) or size not in mean:
                unpriced.add(size)
                break
            share *= min(1.0, bought.get(size, 0) / measured[below])
            seconds += laws * share * max(1, int(seeds or 1)) * mean[size]
            below = size
    return {"seconds": seconds, "unpriced": sorted(unpriced), "mean_seed_seconds": mean}


def estimate(*, spec: dict, queued_by_n: dict, durations_by_n: dict, laws_total: int, law_budget: int | None,
             simulation_core_seconds: float, analysis_core_seconds: float, pace_core_seconds: float,
             share_cores: float | None, laws_climbing: int = 0, to_come: dict | None = None) -> dict:
    queued = {int(n): int(c) for n, c in (queued_by_n or {}).items() if int(c) > 0}
    means = {int(n): float(mean) for n, mean in ((to_come or {}).get("mean_seed_seconds") or {}).items()}
    simulation, at_the_mean, unpriced, floors = 0.0, 0.0, [], []
    for n, count in sorted(queued.items()):
        seconds, floor = seed_seconds(spec, n, (durations_by_n or {}).get(n) or [])
        if seconds is None:
            unpriced.append(n)
            continue
        simulation += count * seconds
        at_the_mean += count * max(seconds, means.get(n, 0.0))
        if floor:
            floors.append(n)
    laws_left = max(0, int(law_budget) - int(laws_total)) if law_budget else 0
    per_law = float(simulation_core_seconds) / int(laws_total) if laws_total else 0.0
    laws_seconds = laws_left * per_law
    ratio = float(analysis_core_seconds) / float(simulation_core_seconds) if simulation_core_seconds else 0.0
    total = (simulation + laws_seconds) * (1.0 + ratio)
    pace = float(pace_core_seconds or 0.0)
    expected = (at_the_mean + float((to_come or {}).get("seconds") or 0.0) + laws_seconds) * (1.0 + ratio)
    return {"contract": WORK_LEFT_CONTRACT, "graphs_queued": sum(queued.values()),
            "queued_by_n": {str(n): c for n, c in sorted(queued.items())},
            "queued_core_hours": round(simulation / 3600.0, 2), "laws_to_budget": laws_left,
            "core_hours_a_law": round(per_law / 3600.0, 4), "laws_core_hours": round(laws_seconds / 3600.0, 2),
            "analysis_ratio": round(ratio, 4), "core_hours_left": round(total / 3600.0, 2),
            "cores_last_hour": round(pace / PACE_WINDOW_SECONDS, 2),
            "hours_at_last_hours_pace": round(total / pace, 1) if pace > 0 and total > 0 else (0.0 if not total else None),
            "share_cores": None if not share_cores else round(float(share_cores), 2),
            "hours_at_fair_share": (round(total / 3600.0 / float(share_cores), 1) if share_cores and total > 0
                                    else (0.0 if not total else None)),
            "unpriced_rungs": unpriced, "rungs_priced_at_a_floor": floors, "at_least": True,
            "laws_climbing": int(laws_climbing or 0),
            "queued_core_hours_at_the_mean": round(at_the_mean / 3600.0, 2),
            "sizes_to_come_core_hours": round(float((to_come or {}).get("seconds") or 0.0) / 3600.0, 2),
            "sizes_to_come_unpriced": list((to_come or {}).get("unpriced") or []),
            "core_hours_expected": round(expected / 3600.0, 2),
            "hours_expected_at_last_hours_pace": (round(expected / pace, 1) if pace > 0 and expected > 0
                                                  else (0.0 if not expected else None))}


def _share_cores(rows: list[dict], pool: int) -> dict:
    running = [r for r in rows if r.get("status") == "active" and r.get("worker_share") != 0
               and r.get("state") not in ("done", "paused", "pausing")]
    declared = {str(r["campaign_id"]): int(r["worker_share"]) for r in running
                if isinstance(r.get("worker_share"), int)}
    undeclared = [str(r["campaign_id"]) for r in running if str(r["campaign_id"]) not in declared]
    rest = max(0.0, float(pool) - float(sum(declared.values())))
    equal = rest / len(undeclared) if undeclared else 0.0
    return {**declared, **{campaign: equal for campaign in undeclared}}


def attach(rows: list[dict], scan_result: dict, queued: dict, compute: dict, pool: int, specs: dict, *,
           climbing: dict | None = None, by_size: dict | None = None) -> dict:
    from graph_scale_dynamics.observability.rung_distribution import seeds_per_law
    work = scan_result or {}
    shares = _share_cores(rows, pool)
    total_hours = total_pace = expected_hours = 0.0
    for row in rows:
        campaign = str(row["campaign_id"])
        budget = (row.get("law_budget") or {}).get("law_budget")
        row["work_left"] = estimate(
            spec=specs.get(campaign) or {}, queued_by_n=queued.get(campaign) or {},
            durations_by_n=(work.get("durations") or {}).get(campaign) or {}, laws_total=int(row.get("laws_total") or 0),
            law_budget=budget, simulation_core_seconds=float((compute.get(campaign) or {}).get(
                "simulation_core_seconds", 0.0)),
            analysis_core_seconds=float((work.get("analysis_core_seconds") or {}).get(campaign, 0.0)),
            pace_core_seconds=float((work.get("pace_core_seconds") or {}).get(campaign, 0.0)),
            share_cores=shares.get(campaign), laws_climbing=int((climbing or {}).get(campaign, 0)),
            to_come=sizes_to_come(
                climbing_by_n=((by_size or {}).get("climbing") or {}).get(campaign),
                measured_by_n=((by_size or {}).get("measured") or {}).get(campaign),
                bought_by_n=((by_size or {}).get("laws") or {}).get(campaign),
                durations_by_n=(work.get("durations") or {}).get(campaign) or {},
                seeds=seeds_per_law(specs.get(campaign) or {}), ladder=_sizes_declared(specs.get(campaign) or {})))
        if campaign in shares:
            total_hours += row["work_left"]["core_hours_left"]
            expected_hours += row["work_left"]["core_hours_expected"]
            total_pace += float((work.get("pace_core_seconds") or {}).get(campaign, 0.0))
    return {"contract": WORK_LEFT_CONTRACT, "campaigns": len(shares), "core_hours_left": round(total_hours, 2),
            "core_hours_expected": round(expected_hours, 2),
            "hours_expected_at_last_hours_pace": (round(expected_hours * 3600.0 / total_pace, 1)
                                                  if total_pace else None),
            "cores_last_hour": round(total_pace / PACE_WINDOW_SECONDS, 2),
            "hours_at_last_hours_pace": round(total_hours * 3600.0 / total_pace, 1) if total_pace else None,
            "hours_at_the_whole_pool": round(total_hours / float(pool), 1) if pool else None,
            "pool": pool, "at_least": True, "window": work.get("window")}
