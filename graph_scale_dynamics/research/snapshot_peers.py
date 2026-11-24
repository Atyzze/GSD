from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime
import math

from graph_scale_dynamics.decisions.engine import SETTLING_RULES
from graph_scale_dynamics.domain.model import utc_now


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None


def _parse_utc(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _replication_timing_summary(repo, campaign_id: str, campaign: dict, phenotypes: list[dict],
                                exposures: list[dict], decisions: dict, analysis_version: str,
                                *, observation_end_utc: str | None = None) -> tuple[list[dict], dict]:
    campaign_id = str(campaign_id)
    created_utc = str(campaign.get("created_utc") or "") or None
    observation_end_utc = str(observation_end_utc or utc_now())

    simulation_rows = repo.conn.execute(
        "SELECT a.finished_utc,COALESCE(a.wall_seconds,0) seconds,j.n "
        "FROM attempts a JOIN jobs j ON j.job_id=a.job_id "
        "WHERE j.campaign_id=? AND a.finished_utc IS NOT NULL ORDER BY a.finished_utc,a.attempt_id",
        (campaign_id,),
    ).fetchall()
    analysis_rows = repo.conn.execute(
        "SELECT aa.finished_utc,COALESCE(aa.wall_seconds,0) seconds,aq.n "
        "FROM analysis_attempts aa JOIN analysis_queue aq "
        "ON aq.campaign_id=aa.campaign_id AND aq.input_artifact=aa.input_artifact "
        "AND aq.analysis_version=aa.analysis_version "
        "WHERE aa.campaign_id=? AND aa.analysis_version=? AND aa.finished_utc IS NOT NULL "
        "ORDER BY aa.finished_utc,aa.analysis_attempt_id",
        (campaign_id, analysis_version),
    ).fetchall()

    events = []
    for kind, rows in (("simulation", simulation_rows), ("analysis", analysis_rows)):
        for raw in rows:
            row = dict(raw)
            stamp = _parse_utc(row.get("finished_utc"))
            seconds = _num(row.get("seconds"))
            if stamp is None or seconds is None or seconds < 0:
                continue
            events.append({
                "dt": stamp, "utc": str(row.get("finished_utc")), "kind": kind,
                "seconds": float(seconds), "n": int(row.get("n") or 0),
            })
    events.sort(key=lambda row: (row["dt"], row["kind"], row["n"]))

    selected_exposures = [row for row in exposures or [] if row.get("selected")]
    exposure_times = sorted(
        _parse_utc(row.get("created_utc")) for row in selected_exposures
        if _parse_utc(row.get("created_utc")) is not None
    )
    phenotype_order = sorted(phenotypes or [], key=lambda row: (
        _parse_utc(row.get("created_utc")) or datetime.min.replace(tzinfo=_parse_utc("1970-01-01T00:00:00Z").tzinfo),
        int(row.get("completion_sequence") or 0), str(row.get("candidate_id") or ""),
    ))
    phenotype_times = [(_parse_utc(row.get("created_utc")), row) for row in phenotype_order]
    phenotype_times = [(stamp, row) for stamp, row in phenotype_times if stamp is not None]

    event_index = 0
    cumulative = {"simulation": 0.0, "analysis": 0.0}
    by_n: dict[int, float] = defaultdict(float)

    def advance(to_dt):
        nonlocal event_index
        while event_index < len(events) and events[event_index]["dt"] <= to_dt:
            event = events[event_index]
            cumulative[event["kind"]] += event["seconds"]
            if event["n"] > 0:
                by_n[event["n"]] += event["seconds"]
            event_index += 1

    campaign_created_dt = _parse_utc(created_utc)
    timed_phenotypes = []
    completed_seen = 0
    for row in phenotype_order:
        stamp = _parse_utc(row.get("created_utc"))
        completed_seen += 1
        enriched = dict(row)
        if stamp is not None:
            advance(stamp)
            proposals_seen = bisect.bisect_right(exposure_times, stamp)
            elapsed = None if campaign_created_dt is None else max(0.0, (stamp - campaign_created_dt).total_seconds())
            enriched["completion_timing"] = {
                "completed_candidate_rank": int(row.get("completion_sequence") or completed_seen),
                "wall_seconds_since_campaign_creation": elapsed,
                "proposal_exposures_at_event": proposals_seen if exposure_times else None,
                "simulation_worker_seconds_at_event": cumulative["simulation"],
                "analysis_worker_seconds_at_event": cumulative["analysis"],
                "scientific_worker_seconds_at_event": cumulative["simulation"] + cumulative["analysis"],
            }
        timed_phenotypes.append(enriched)

    event_times = [row["dt"] for row in events]
    prefix_sim, prefix_analysis = [0.0], [0.0]
    prefix_by_n: list[dict[int, float]] = [defaultdict(float)]
    for event in events:
        prefix_sim.append(prefix_sim[-1] + (event["seconds"] if event["kind"] == "simulation" else 0.0))
        prefix_analysis.append(prefix_analysis[-1] + (event["seconds"] if event["kind"] == "analysis" else 0.0))
        next_map = defaultdict(float, prefix_by_n[-1])
        if event["n"] > 0:
            next_map[event["n"]] += event["seconds"]
        prefix_by_n.append(next_map)

    def clocks_at(stamp):
        if stamp is None:
            return {"simulation": None, "analysis": None, "total": None, "by_n": {}}
        index = bisect.bisect_right(event_times, stamp)
        return {
            "simulation": prefix_sim[index], "analysis": prefix_analysis[index],
            "total": prefix_sim[index] + prefix_analysis[index],
            "by_n": {str(n): seconds for n, seconds in sorted(prefix_by_n[index].items())},
        }

    phenotype_stamps = [stamp for stamp, _ in phenotype_times]
    exposure_stamps = exposure_times
    exposure_by_candidate = {
        str(row.get("candidate_id")): row for row in selected_exposures if row.get("candidate_id")
    }
    stabilizer_events = []
    for candidate_id, rows in (decisions or {}).items():
        first = next((row for row in rows or [] if row.get("rule") in SETTLING_RULES), None)
        stamp = _parse_utc(first.get("created_utc")) if first else None
        if stamp is None:
            continue
        compute = clocks_at(stamp)
        exposure = exposure_by_candidate.get(str(candidate_id)) or {}
        coords = exposure.get("coordinates") or {}
        completed_rank = bisect.bisect_right(phenotype_stamps, stamp)
        proposal_rank = bisect.bisect_right(exposure_stamps, stamp) if exposure_stamps else None
        elapsed = None if campaign_created_dt is None else max(0.0, (stamp - campaign_created_dt).total_seconds())
        stabilizer_events.append({
            "candidate_id": str(candidate_id), "decision_id": first.get("decision_id"),
            "event_utc": first.get("created_utc"), "rule": first.get("rule"), "at_n": first.get("at_n"),
            "mean_degree_settled": (first.get("facts") or {}).get("mean_degree_settled"),
            "wall_seconds_since_campaign_creation": elapsed,
            "completed_candidates_at_event": completed_rank,
            "proposal_exposures_at_event": proposal_rank,
            "simulation_worker_seconds_at_event": compute["simulation"],
            "analysis_worker_seconds_at_event": compute["analysis"],
            "scientific_worker_seconds_at_event": compute["total"],
            "scientific_worker_seconds_by_n_at_event": compute["by_n"],
            "dependence_family": str(coords.get("family_id") or exposure.get("dependence_unit_id") or "unknown"),
        })
    stabilizer_events.sort(key=lambda row: (row.get("event_utc") or "", row["candidate_id"]))

    end_dt = _parse_utc(observation_end_utc)
    end_compute = clocks_at(end_dt)
    current_elapsed = None if campaign_created_dt is None or end_dt is None else max(0.0, (end_dt - campaign_created_dt).total_seconds())
    current = {
        "observation_end_utc": observation_end_utc,
        "wall_seconds_since_campaign_creation": current_elapsed,
        "completed_candidates": len(phenotypes or []),
        "proposal_exposures": len(selected_exposures),
        "simulation_worker_seconds": end_compute["simulation"],
        "analysis_worker_seconds": end_compute["analysis"],
        "scientific_worker_seconds": end_compute["total"],
        "scientific_worker_seconds_by_n": end_compute["by_n"],
    }
    return timed_phenotypes, {
        "contract": "cross-campaign-event-clocks-1",
        "campaign_created_utc": created_utc,
        "current": current,
        "stabilizer_events": stabilizer_events,
        "clock_notes": {
            "wall_time": "UTC elapsed time from immutable campaign creation to the recorded event",
            "completed_candidate_rank": "four-rung phenotype completions observed by the event time",
            "proposal_exposure": "selected proposal exposures with recorded creation timestamps observed by the event time",
            "scientific_worker_seconds": "finished simulation + analysis child wall seconds; one configured executor slot per child, excluding reporting/telemetry/auxiliary services",
            "right_censoring": "an unreached event remains censored at the snapshot observation end rather than being treated as absence",
            "stabilizer_event": "the first engine decision bought for settling (SETTLING_RULES)",
        },
    }
