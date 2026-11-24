from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict

from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES
from graph_scale_dynamics.research.numeric import finite as _finite

HANG_AUTOPSY_CONTRACT = "gsd-hang-autopsy-1"


def _health_by_candidate_rung(snapshot: dict) -> dict[tuple[str, int], list[dict]]:
    out: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in snapshot.get("measurements") or []:
        health = ((row.get("metrics") or {}).get("health") or {})
        if health:
            out[(str(row.get("candidate_id")), int(row.get("n")))].append(health)
    return out


def _trajectory_shape(health: dict) -> dict:
    checkpoints = health.get("sampling_checkpoints") or []
    degrees = [_finite(c.get("mean_degree")) for c in checkpoints]
    degrees = [d for d in degrees if d is not None]
    eff = [_finite(c.get("effective_samples")) for c in checkpoints]
    eff = [e for e in eff if e is not None]
    fails = Counter()
    for c in checkpoints:
        for f in c.get("failures") or []:
            if isinstance(f, dict) and f.get("code"):
                fails[str(f["code"])] += 1
    return {
        "chunks": len(checkpoints),
        "final_multiplier": (checkpoints[-1].get("multiplier") if checkpoints else None),
        "mean_degree_first": degrees[0] if degrees else None,
        "mean_degree_last": degrees[-1] if degrees else None,
        "mean_degree_peak": max(degrees) if degrees else None,
        "effective_samples_last": eff[-1] if eff else None,
        "certificate_failures": dict(fails.most_common()),
        "wall_seconds": (checkpoints[-1].get("wall_seconds_so_far") if checkpoints else None),
    }


GIVEN_TIME_SHARE = 0.9


def _seed_chain_profile(metrics: dict) -> dict | None:
    health = metrics.get("health") or {}
    mixing = metrics.get("chain_mixing") or {}
    seconds = mixing.get("chain_seconds") or {}
    from_empty = _finite(seconds.get("empty_chain_seconds"))
    given = _finite(seconds.get("given_chain_seconds"))
    if from_empty is None or given is None or from_empty + given <= 0:
        return None
    halves = (((mixing.get("given") or {}).get("mean_degree")) or {}).get("halves") or []
    return {
        "from_empty_frozen": _finite((health.get("activity") or {}).get("accepted_topology_changes_per_node_cumulative")) == 0.0,
        "given_share": given / (from_empty + given),
        "given_late_mean_degree": _finite(halves[-1].get("mean")) if halves else None,
        "given_seconds": given,
    }


def frozen_from_empty_busy_given(snapshot: dict, spend: dict, interrupted: dict) -> dict:
    by_rung: dict = defaultdict(list)
    for row in snapshot.get("measurements") or []:
        profile = _seed_chain_profile(row.get("metrics") or {})
        if profile is not None:
            by_rung[(str(row.get("candidate_id")), int(row.get("n")))].append(profile)
    flagged: dict = defaultdict(list)
    for (cid, n), seeds in by_rung.items():
        if seeds and all(s["from_empty_frozen"] and s["given_share"] >= GIVEN_TIME_SHARE for s in seeds):
            degrees = [s["given_late_mean_degree"] for s in seeds if s["given_late_mean_degree"] is not None]
            flagged[cid].append({"n": n, "seeds": len(seeds),
                                 "given_time_share": round(sum(s["given_share"] for s in seeds) / len(seeds), 4),
                                 "given_late_mean_degree_max": round(max(degrees), 3) if degrees else None,
                                 "rung_core_seconds": round(spend.get((cid, n), 0.0), 1)})
    candidates = {str(c.get("candidate_id")): c for c in snapshot.get("candidates") or []}

    def signature(cid: str) -> list[str]:
        terms = ((candidates.get(cid) or {}).get("spec") or {}).get("terms") or []
        return sorted({f"{t.get('op')}:{'-' if float((t.get('coeff') or {}).get('c0') or 0) < 0 else '+'}" for t in terms})

    def beta(cid: str):
        return (((candidates.get(cid) or {}).get("spec") or {}).get("dynamics") or {}).get("beta")

    all_laws = sorted({cid for cid, _ in spend})
    laws = []
    for cid in sorted(flagged, key=lambda c: -sum(v for (k, _), v in spend.items() if k == c)):
        laws.append({"candidate_id": cid, "rungs": sorted(flagged[cid], key=lambda r: r["n"]),
                     "law_core_seconds": round(sum(v for (k, _), v in spend.items() if k == cid), 1),
                     "law_interrupted_seconds": round(sum(v for (k, _), v in interrupted.items() if k == cid), 1),
                     "terms": signature(cid), "beta": beta(cid)})
    in_corner, everywhere = Counter(), Counter()
    for cid in all_laws:
        everywhere.update(signature(cid))
    for law in laws:
        in_corner.update(law["terms"])
    total = sum(spend.values()) or 1.0
    corner_seconds = sum(law["law_core_seconds"] for law in laws)
    return {
        "rule": (f"every measured seed of the rung: the chain from empty accepted no topology change, the given chain took at least "
                 f"{GIVEN_TIME_SHARE:.0%} of the chain time"),
        "rungs": sum(len(v) for v in flagged.values()),
        "rungs_by_n": dict(sorted(Counter(r["n"] for v in flagged.values() for r in v).items())),
        "laws": len(laws),
        "laws_in_campaign": len(all_laws),
        "law_core_seconds": round(corner_seconds, 1),
        "share_of_campaign_core_seconds": round(corner_seconds / total, 4),
        "interrupted_core_seconds": round(sum(law["law_interrupted_seconds"] for law in laws), 1),
        "term_signatures": [{"term": term, "laws": count, "share_of_these_laws": round(count / len(laws), 3),
                             "share_of_all_laws": round(everywhere[term] / len(all_laws), 3)}
                            for term, count in in_corner.most_common()],
        "betas": {"these_laws": dict(Counter(str(law["beta"]) for law in laws).most_common()),
                  "all_laws": dict(Counter(str(beta(cid)) for cid in all_laws).most_common())},
        "law_list": laws[:100],
    }


def build_hang_autopsy(snapshot: dict, *, top: int = 100) -> dict:
    spend: dict[tuple[str, int], float] = {}
    for row in snapshot.get("rung_spend") or []:
        spend[(str(row["candidate_id"]), int(row["n"]))] = float(row.get("core_seconds") or 0.0)
    health = _health_by_candidate_rung(snapshot)
    spec = (snapshot.get("campaign") or {}).get("spec") or {}
    limits = spec.get("limits") or {}
    from graph_scale_dynamics.decisions.engine import Policy, is_engine_campaign
    policy = Policy.from_spec(spec) if is_engine_campaign(spec) else None
    budget = ({str(n): policy.work_budget(n) for n in policy.ladder()} if policy is not None and policy.work_budgets
              else None)
    cap = _finite((limits.get("mean_degree_window") or {}).get("max"))

    law_rows: dict[str, dict] = {}
    reasons = Counter()
    reasons_by_n = defaultdict(Counter)
    interrupted = {(str(row["candidate_id"]), int(row["n"])): float(row.get("interrupted_seconds") or 0.0)
                   for row in snapshot.get("rung_spend") or []}
    for (cid, n), seconds in spend.items():
        entry = law_rows.setdefault(cid, {"candidate_id": cid, "core_seconds": 0.0,
                                          "interrupted_core_seconds": 0.0, "rungs": []})
        entry["core_seconds"] += seconds
        entry["interrupted_core_seconds"] += interrupted.get((cid, n), 0.0)
        healths = health.get((cid, n)) or []
        terminals = [h.get("rung_terminal") or {} for h in healths if h.get("rung_terminal")]
        reason_counts = Counter(str(t.get("reason") or "unknown") for t in terminals)
        worst = None
        for h in healths:
            t = h.get("rung_terminal") or {}
            rank = {"mean_degree_cap": 0, "budget": 1, "ceiling": 2, "completed": 3}.get(str(t.get("reason")), 2)
            if worst is None or rank < worst[0]:
                worst = (rank, h)
        shape = _trajectory_shape(worst[1]) if worst else {}
        worst_reason = str((worst[1].get("rung_terminal") or {}).get("reason") or "none") if worst else "none"
        reasons[worst_reason] += 1
        reasons_by_n[int(n)][worst_reason] += 1
        entry["rungs"].append({
            "n": int(n), "core_seconds": round(seconds, 1),
            "seed_reasons": dict(reason_counts),
            "worst_reason": worst_reason,
            "classification": str((worst[1].get("rung_terminal") or {}).get("classification") or "") if worst else None,
            "shape": shape,
        })
    for entry in law_rows.values():
        entry["rungs"].sort(key=lambda r: r["n"])
        entry["core_seconds"] = round(entry["core_seconds"], 1)
        entry["interrupted_core_seconds"] = round(entry["interrupted_core_seconds"], 1)
        entry["limit_hits"] = [r["n"] for r in entry["rungs"] if r["worst_reason"] in ("mean_degree_cap", "budget")]
        entry["ceiling_hits"] = [r["n"] for r in entry["rungs"] if r["worst_reason"] == "ceiling"]
    ranked = sorted(law_rows.values(), key=lambda e: (-e["core_seconds"], e["candidate_id"]))
    specs = {str(c.get("candidate_id")): c.get("spec") for c in snapshot.get("candidates") or []}
    for entry in ranked[:top]:
        terms = (specs.get(entry["candidate_id"]) or {}).get("terms") or []
        entry["terms"] = [{"op": t.get("op"), "params": t.get("params") or {},
                           "scale": (t.get("coeff") or {}).get("scale"), "c0": (t.get("coeff") or {}).get("c0")}
                          for t in terms]
    total = sum(e["core_seconds"] for e in law_rows.values()) or 1.0
    top_ten = sum(e["core_seconds"] for e in ranked[:max(1, len(ranked) // 10)])
    walls = sorted(e["core_seconds"] for e in law_rows.values())
    return {
        "contract": HANG_AUTOPSY_CONTRACT,
        "limits_in_force": {"work_budget": budget, "mean_degree_cap": cap},
        "laws": len(law_rows),
        "core_seconds_total": round(total, 1),
        "interrupted_core_seconds_total": round(sum(interrupted.values()), 1),
        "top_decile_wall_fraction": round(top_ten / total, 4),
        "law_wall_quantiles": {
            "median": walls[len(walls) // 2] if walls else None,
            "p90": walls[int(0.9 * (len(walls) - 1))] if walls else None,
            "max": walls[-1] if walls else None,
        },
        "worst_reason_counts_by_rung": {str(n): dict(c) for n, c in sorted(reasons_by_n.items())},
        "worst_reason_counts": dict(reasons.most_common()),
        "ranked": ranked[:top],
        "frozen_from_empty_busy_given": frozen_from_empty_busy_given(snapshot, spend, interrupted),
        "reading": (
            "Laws ranked by simulation core-seconds. Each rung names what stopped its worst seed "
            "(mean_degree_cap: left the window; budget: spent the hour; ceiling: hit the multiplier "
            "cap without passing the certificate twice; completed: passed) and the shape of its "
            "sampling history (chunks, mean degree first/peak/last, effective samples, which "
            "certificate codes kept failing). A law that is expensive AND completed is slow "
            "mixing; a law that is expensive AND capped is dense mass that took a while to get "
            "there. Both are what a lower rung should learn to predict."
        ),
    }


FLEET_AND_HOST_CONTRACT = "gsd-fleet-and-host-1"


def _hour_bucket(utc: str | None) -> str | None:
    return str(utc)[:13] if utc else None


LADDER_TREND_FIELDS = ("n", "laws", "attempts", "running", "queued", "analysing", "queued_analyses",
                       "stopped_by_rule", "interrupted", "interrupted_seconds",
                       "simulation_seconds_total", "probe_seconds_total", "median_seconds",
                       "memory_timed_attempts", "peak_bytes_p05", "peak_bytes_median", "peak_bytes_p95",
                       "reserved_bytes_median", "reserved_over_observed", "fallback_reservation_bytes",
                       "reserved_at_fallback")


def _ladder_by_hour(history: dict) -> dict:
    return {"snapshots_recorded": int(history.get("snapshots") or 0),
            "hours": [{"hour": row.get("hour"), "snapshot_utc": row.get("snapshot_utc"),
                       "candidates_by_state": row.get("candidates_by_state") or {},
                       "rungs": [{k: r[k] for k in LADDER_TREND_FIELDS if k in r} for r in row.get("rows") or []]}
                      for row in history.get("hours") or []]}


def build_fleet_and_host(snapshot: dict) -> dict:
    home = str(snapshot.get("campaign_id") or "")
    by_campaign: dict[str, dict] = {}
    for row in snapshot.get("host_jobs_by_campaign") or []:
        cid = str(row.get("campaign_id"))
        entry = by_campaign.setdefault(cid, {"campaign_id": cid, "is_home": cid == home,
                                             "leased": 0, "queued": 0, "leased_by_n": {}, "queued_by_n": {}})
        status = str(row.get("status"))
        count = int(row.get("c") or 0)
        entry[status] = entry.get(status, 0) + count
        entry[f"{status}_by_n"][str(int(row.get("n") or 0))] = count
    total_leased = sum(e["leased"] for e in by_campaign.values()) or 0
    for e in by_campaign.values():
        e["leased_share"] = round(e["leased"] / total_leased, 4) if total_leased else None

    hours: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "waits": [], "walls": [], "failed": Counter()})
    for row in snapshot.get("attempts") or []:
        h = _hour_bucket(row.get("started_utc"))
        if not h:
            continue
        bucket = hours[h]
        bucket["attempts"] += 1
        wall = _finite(row.get("wall_seconds"))
        if wall is not None and row.get("error_class") not in INTERRUPTED_ATTEMPT_CLASSES:
            bucket["walls"].append(wall)
        created, started = row.get("job_created_utc"), row.get("started_utc")
        if created and started:
            try:
                from graph_scale_dynamics.research.report_pipeline import _seconds_between
                w = _seconds_between(created, started)
                if w is not None:
                    bucket["waits"].append(float(w))
            except Exception:
                pass
        if row.get("exit_code") not in (None, 0):
            bucket["failed"][str(row.get("error_class") or "unknown")] += 1
    trend = []
    for h in sorted(hours):
        b = hours[h]
        trend.append({
            "hour": h, "attempts": b["attempts"],
            "wall_median": round(statistics.median(b["walls"]), 2) if b["walls"] else None,
            "wall_p90": round(sorted(b["walls"])[min(len(b["walls"]) - 1, math.ceil(0.9 * (len(b["walls"]) - 1)))], 2) if b["walls"] else None,
            "queue_wait_median": round(statistics.median(b["waits"]), 1) if b["waits"] else None,
            "failed_by_class": dict(b["failed"]),
        })
    telemetry_trend = [
        {"hour": str(r.get("hour_bucket") or r.get("hour")), "samples": int(r.get("c") or 0),
         "cpu": None if r.get("avg_cpu") is None else round(float(r["avg_cpu"]), 1),
         "gsd_cpu": None if r.get("avg_gsd_cpu") is None else round(float(r["avg_gsd_cpu"]), 1),
         "max_temp": None if r.get("max_temp") is None else round(float(r["max_temp"]), 1)}
        for r in snapshot.get("telemetry_trend") or []
    ]
    status = Counter(str(row.get("status")) for row in snapshot.get("jobs") or [])
    return {
        "contract": FLEET_AND_HOST_CONTRACT,
        "home_campaign_id": home,
        "live_compute_by_campaign": sorted(by_campaign.values(), key=lambda e: (-e["leased"], e["campaign_id"])),
        "campaigns_sharing_the_fleet": len(by_campaign),
        "home_leased_share": next((e["leased_share"] for e in by_campaign.values() if e["is_home"]), None),
        "home_job_status": dict(status),
        "attempt_trend_by_hour": trend,
        "telemetry_trend_by_hour": telemetry_trend,
        "fleet_ladder_by_hour": _ladder_by_hour(snapshot.get("fleet_ladder_hourly") or {}),
        "telemetry_summary": snapshot.get("telemetry") or {},
        "reading": (
            "live_compute_by_campaign is host-wide: if the home campaign's leased share is well below "
            "1.0 while it has queued work, another campaign owns the fleet. The hourly trends are how a "
            "fix or a slow leak shows up: queue wait rising with flat wall is admission, wall rising is "
            "the laws, failures by class is the retry rule doing its job."
        ),
    }
