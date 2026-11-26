from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from graph_scale_dynamics.decisions.engine import HOLD, STOP
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES, utc_now
from graph_scale_dynamics.observability import law_score, work_left
from graph_scale_dynamics.operations.auto_extend import state as auto_extend_state
from graph_scale_dynamics.operations.campaign_control import (
    ACTIVE, FOCUS_FLAG, PAUSED, PAUSING, SURVEYED, apply_allocation, campaign_chains_running,
    clone_spec, create_campaign, window_of,
    derived_state, pause, reopen, reporting_focus,
    survey_state,
    reopen_problems, resume, set_workers, worker_pool,
)
from graph_scale_dynamics.scheduling.term_selection import catalogue, preflight, selection_diff

CAMPAIGN_MANAGER_CONTRACT = "gsd-campaign-manager-1"

TOP_RUNGS = 3

ACTIONS = ("pause", "resume", "reopen", "preflight", "clone", "create",
           "workers", "allocate", "fleet_pause", "fleet_resume", "delete", "budget", "auto_extend",
           "fleet_workers", "workload")
HELD_BY_A_QUIET_REPORT = frozenset({"resume", "reopen", "workers", "allocate", "fleet_resume"})

_LAWS_BY_RUNG = ("SELECT campaign_id,n,COUNT(DISTINCT candidate_id) AS laws,"
                 "COUNT(*) FILTER (WHERE status='done' AND result_artifact IS NOT NULL) AS graphs,"
                 "COUNT(DISTINCT (candidate_id,seed)) FILTER (WHERE status='done' AND result_artifact IS NOT NULL) "
                 "AS finished,"
                 "COUNT(*) AS created,"
                 "COUNT(DISTINCT (candidate_id,seed)) AS bought,"
                 "COUNT(DISTINCT candidate_id) FILTER (WHERE status IN ('queued','leased')) AS climbing,"
                 "COUNT(*) FILTER (WHERE status IN ('queued','leased')) AS queued FROM jobs "
                 "WHERE kind='simulate' GROUP BY campaign_id,n")
_CLIMBING = ("SELECT campaign_id,COUNT(DISTINCT candidate_id) AS laws FROM jobs "
             "WHERE kind='simulate' AND status IN ('queued','leased') GROUP BY campaign_id")
_MEASURED_BY_RUNG = ("SELECT campaign_id,n,COUNT(*) AS measured FROM rung_summaries "
                     "GROUP BY campaign_id,n")
_STATES = ("SELECT campaign_id,state,COUNT(*) AS c FROM campaign_candidates "
           "GROUP BY campaign_id,state")
_ARCHIVED_STATES = ("SELECT campaign_id,state,COUNT(*) AS c FROM campaign_archive_candidates "
                    "GROUP BY campaign_id,state")
_HELD = "SELECT campaign_id,COUNT(*) AS held FROM engine_decisions_latest WHERE action=? GROUP BY campaign_id"

_STOPPED_BY_RULE = (
    "SELECT campaign_id,rule,COUNT(*) AS c,MIN(reason) AS example FROM engine_decisions_latest "
    "WHERE action=? GROUP BY campaign_id,rule")

_AGGREGATES: dict[str, dict] = {}
_AGGREGATES_LOCK = threading.Lock()
_ACTIVE_TTL = ticks(4)
_SETTLED_TTL = 3600.0


_MEETING_READINGS = (
    "SELECT campaign_id,reading,COUNT(*) AS c FROM (SELECT campaign_id,"
    "diagnostics_json::jsonb#>>'{meeting_reading,reading}' AS reading FROM (SELECT DISTINCT ON "
    "(campaign_id,candidate_id) campaign_id,diagnostics_json FROM rung_diagnostics "
    "ORDER BY campaign_id,candidate_id,n DESC) deepest) readings WHERE reading IS NOT NULL "
    "GROUP BY campaign_id,reading")


def _grouped(repo, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in repo.conn.execute(sql, params).fetchall()]


_COMPUTE = (
    "SELECT j.campaign_id campaign_id,"
    "COALESCE(SUM(a.wall_seconds) FILTER (WHERE j.kind='simulate'),0) simulation_seconds,"
    "COALESCE(SUM(a.wall_seconds) FILTER (WHERE j.kind='analyze'),0) analysis_seconds,"
    "COALESCE(SUM(CASE WHEN a.exit_code IS NOT NULL AND a.exit_code!=0 "
    "THEN a.wall_seconds ELSE 0 END),0) unsuccessful_seconds "
    "FROM jobs j JOIN attempts a ON a.job_id=j.job_id GROUP BY j.campaign_id")
_ANALYSIS_COMPUTE = (
    "SELECT campaign_id, COALESCE(SUM(wall_seconds),0) analysis_seconds FROM analysis_attempts GROUP BY campaign_id")


def compute_seconds(repo) -> dict[str, dict]:
    out: dict[str, dict] = {}
    queued_analysis = {str(row["campaign_id"]): float(row["analysis_seconds"] or 0.0)
                       for row in _grouped(repo, _ANALYSIS_COMPUTE)}
    for row in _grouped(repo, _COMPUTE):
        simulation = float(row["simulation_seconds"] or 0.0)
        analysis = float(row["analysis_seconds"] or 0.0) + queued_analysis.pop(str(row["campaign_id"]), 0.0)
        out[str(row["campaign_id"])] = {
            "simulation_core_seconds": round(simulation, 1),
            "analysis_core_seconds": round(analysis, 1),
            "core_seconds": round(simulation + analysis, 1),
            "unsuccessful_core_seconds": round(float(row["unsuccessful_seconds"] or 0.0), 1),
        }
    return out


def _rung_ceiling(n: int) -> float | None:
    if int(n) < law_score.LADDER[0]:
        return None
    return float(round(100.0 * law_score.depth(int(n))))


def _rung_rows(laws: dict, measured: dict, graphs: dict | None = None) -> list[dict]:
    rungs = sorted(set(laws) | set(measured))
    return [{"n": int(n), "laws": int(laws.get(n, 0)), "graphs": int((graphs or {}).get(n, 0)),
             "measured": int(measured.get(n, 0)), "ceiling": _rung_ceiling(n)}
            for n in rungs]


def high_score(cache_root, campaign_id: str) -> dict | None:
    if cache_root is None:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(campaign_id))[:48] or "campaign"
    path = Path(cache_root) / f"landscape-{safe}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    top = (payload.get("top_candidates") or [])
    if not isinstance(top, list) or not top:
        return None
    best = top[0] if isinstance(top[0], dict) else {}
    if "law_score" not in best:
        return None
    found = best.get("law_score")
    score = found.get("score") if isinstance(found, dict) else None
    if found is not None and not isinstance(score, (int, float)):
        return None
    return {"score": None if found is None else int(score), "candidate_id": best.get("candidate_id"),
            "by": (found or {}).get("by"), "to_n": (found or {}).get("to_n"),
            "generated_utc": payload.get("generated_utc"), "max": 100,
            "scoring": sum(1 for row in top if isinstance(row, dict)
                           and int(((row.get("law_score") or {}).get("score") or 0)) > 0)}


def _slow_scan(repo) -> dict:
    laws: dict[str, dict[int, int]] = {}
    graphs: dict[str, dict[int, int]] = {}
    created: dict[str, dict[int, int]] = {}
    bought: dict[str, dict[int, int]] = {}
    queued: dict[str, dict[int, int]] = {}
    finished: dict[str, dict[int, int]] = {}
    climbing_by_size: dict[str, dict[int, int]] = {}
    for row in _grouped(repo, _LAWS_BY_RUNG):
        climbing_by_size.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["climbing"] or 0)
        finished.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["finished"] or 0)
        laws.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["laws"] or 0)
        graphs.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["graphs"] or 0)
        created.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["created"] or 0)
        bought.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["bought"] or 0)
        queued.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["queued"] or 0)
    measured: dict[str, dict[int, int]] = {}
    for row in _grouped(repo, _MEASURED_BY_RUNG):
        measured.setdefault(str(row["campaign_id"]), {})[int(row["n"])] = int(row["measured"] or 0)
    held = {str(row["campaign_id"]): int(row["held"] or 0)
            for row in _grouped(repo, _HELD, (HOLD,))}
    stopped: dict[str, list[dict]] = {}
    for row in _grouped(repo, _STOPPED_BY_RULE, (STOP,)):
        stopped.setdefault(str(row["campaign_id"]), []).append(
            {"rule": str(row["rule"] or "unrecorded"), "laws": int(row["c"] or 0),
             "example": str(row["example"] or "")})
    for rows in stopped.values():
        rows.sort(key=lambda row: (-row["laws"], row["rule"]))
    given_chains: dict[str, dict[str, int]] = {}
    for row in _grouped(repo, _MEETING_READINGS):
        given_chains.setdefault(str(row["campaign_id"]), {})[str(row["reading"])] = int(row["c"] or 0)
    hand_terms: dict[str, list[str]] = {}
    verdicts: dict[str, dict] = {}
    for campaign in repo.all_campaigns():
        spec, campaign_id = campaign.get("spec") or {}, str(campaign["campaign_id"])
        if (spec.get("search_policy") or {}).get("kind") == "hand":
            hand_terms[campaign_id] = _terms_its_laws_use(repo, campaign_id)
            verdict = _control_verdict(repo, campaign)
            if verdict is not None:
                verdicts[campaign_id] = verdict
    climbing = {str(row["campaign_id"]): int(row["laws"] or 0) for row in _grouped(repo, _CLIMBING)}
    return {"laws": laws, "graphs": graphs, "created": created, "bought": bought, "finished": finished,
            "measured": measured,
            "held": held,
            "compute": compute_seconds(repo), "stopped": stopped, "given_chains": given_chains,
            "hand_terms": hand_terms, "control_verdicts": verdicts, "queued": queued,
            "climbing": climbing, "climbing_by_size": climbing_by_size, "work": work_left.scan(repo)}


def _live_scan(repo) -> dict:
    states: dict[str, dict[str, int]] = {}
    for sql in (_STATES, _ARCHIVED_STATES):
        for row in _grouped(repo, sql):
            bucket = states.setdefault(str(row["campaign_id"]), {})
            bucket[str(row["state"])] = bucket.get(str(row["state"]), 0) + int(row["c"] or 0)
    running = {str(row["campaign_id"]): {"leased": int(row["leased"] or 0),
                                         "queued": int(row["queued"] or 0)}
               for row in repo.worker_allocation()}
    analyses = {str(row["campaign_id"]): int(row["c"] or 0) for row in _grouped(
        repo, "SELECT campaign_id,COUNT(*) AS c FROM analysis_queue WHERE status='leased' "
              "AND lease_expires_utc>=? GROUP BY campaign_id", (utc_now(),))}
    analyses_queued = {str(row["campaign_id"]): int(row["c"] or 0) for row in _grouped(
        repo, "SELECT campaign_id,COUNT(*) AS c FROM analysis_queue WHERE status='queued' GROUP BY campaign_id")}
    return {"states": states, "running": running, "analyses": analyses, "analyses_queued": analyses_queued}


def draw_of(spec: dict) -> dict | None:
    import re
    design = (spec or {}).get("study_design") or {}
    if design.get("kind") != "blind" or not design.get("design_sha256"):
        return None
    name = str(spec.get("name") or "")
    label = re.sub(r"\s*\(\d+ of \d+\)\s*$", "", name.split(": ", 1)[-1])
    return {"key": f"{design.get('study')}:{str(design['design_sha256'])[:12]}", "label": label,
            "batch": int(design.get("campaign") or 0) + 1}


def _terms_its_laws_use(repo, campaign_id: str) -> list[str]:
    ops: set[str] = set()
    for law in repo.candidates(str(campaign_id)):
        ops.update(str(term.get("op")) for term in (law.get("spec") or {}).get("terms") or [])
    return sorted(ops)


def _control_verdict(repo, campaign: dict) -> dict | None:
    try:
        from graph_scale_dynamics.research.control_verdict import campaign_verdict
        return campaign_verdict(repo, campaign)
    except Exception as exc:  # noqa: BLE001
        return {"overall": "unreadable", "why": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _controls(repo, campaign: dict, actives: int) -> dict:
    campaign_id = str(campaign["campaign_id"])
    closed = campaign.get("status") in {"closed", "completed"}
    problems = reopen_problems(repo, campaign_id) if closed else []
    active = campaign.get("status") == ACTIVE
    paused = derived_state(campaign) in (PAUSED, PAUSING)
    return {
        "pause": active and not paused,
        "resume": active and paused,
        "reopen": closed and not problems,
        "reopen_problems": problems,
        "clone": campaign.get("status") != "deleting",
        "workers": campaign.get("status") == "active",
        "delete": not delete_problems(repo, campaign),
        "delete_problems": delete_problems(repo, campaign),
        "archive": False,
        "other_active_campaigns": actives,
    }


def work_supply(repo) -> dict:
    from graph_scale_dynamics.operations.study import budget_reached
    allocation = {str(row["campaign_id"]): row for row in repo.worker_allocation()}
    held = {str(row["campaign_id"]): int(row["held"] or 0)
            for row in _grouped(repo, _HELD, (HOLD,))}
    causes: list[dict] = []
    for campaign in repo.all_campaigns():
        if campaign.get("status") != "active":
            continue
        campaign_id = str(campaign["campaign_id"])
        state = derived_state(campaign)
        queued = int((allocation.get(campaign_id) or {}).get("queued") or 0)
        waiting = held.get(campaign_id, 0)
        surveyed = survey_state(repo, campaign_id)
        if state in {PAUSED, PAUSING}:
            causes.append({"campaign_id": campaign_id, "cause": "paused", "expected": True,
                           "reading": f"campaign {campaign_id} is paused"
                                      + (f" with {queued} job(s) still queued" if queued else "")})
        elif queued == 0 and budget_reached(repo, campaign_id):
            causes.append({"campaign_id": campaign_id, "cause": "law_budget", "expected": True,
                           "reading": f"campaign {campaign_id} is at its law budget and proposes no more"
                                      + (f"; it holds {waiting} at a gate" if waiting else "")})
        elif surveyed is not None:
            causes.append({"campaign_id": campaign_id, "cause": SURVEYED, "expected": True,
                           "reading": f"campaign {campaign_id} has proposed every law its term "
                                      f"set can write ({surveyed.get('held')})"
                                      + (f" and holds {waiting} at a gate" if waiting else "")})
        elif queued == 0 and waiting:
            causes.append({"campaign_id": campaign_id, "cause": "held", "expected": True,
                           "reading": f"campaign {campaign_id} holds {waiting} law(s) at a gate "
                                      "and has queued nothing else"})
        elif queued == 0:
            causes.append({"campaign_id": campaign_id, "cause": "no_work", "expected": False,
                           "reading": f"campaign {campaign_id} is active with nothing queued and "
                                      "nothing held, which the proposer should have filled"})
    if not causes:
        return {"causes": [], "expected": False, "reading": "no campaign is active"}
    return {"causes": causes,
            "expected": all(cause["expected"] for cause in causes),
            "reading": "; ".join(cause["reading"] for cause in causes)}


def _hand_fed_and_settled(repo, campaign_id: str, spec: dict) -> bool:
    from graph_scale_dynamics.operations.study import in_flight, laws_held
    if ((spec or {}).get("search_policy") or {}).get("kind") != "hand":
        return False
    return laws_held(repo, campaign_id) > 0 and not in_flight(repo, campaign_id)


def _campaign_row(repo, campaign: dict, scan: dict, actives: int,
                  cache_root=None) -> dict:
    campaign_id = str(campaign["campaign_id"])
    spec = campaign.get("spec") or {}
    held_now = int((scan["running"].get(campaign_id) or {}).get("leased", 0))
    analyses_now = int((scan.get("analyses") or {}).get(campaign_id, 0))
    state = derived_state(campaign, chains_running=held_now + analyses_now)
    surveyed = survey_state(repo, campaign_id)
    if surveyed is not None and state == ACTIVE:
        state = SURVEYED
    from graph_scale_dynamics.operations.study import DONE, budget_state, quadrant_label
    budget = budget_state(repo, campaign_id, spec)
    if budget and budget.get("state") and state == ACTIVE:
        state = budget["state"]
    elif state == ACTIVE and not budget and _hand_fed_and_settled(repo, campaign_id, spec):
        state = DONE
    from graph_scale_dynamics.observability.rung_distribution import chains_per_seed
    laws = scan["laws"].get(campaign_id, {})
    measured = scan["measured"].get(campaign_id, {})
    graphs = (scan.get("graphs") or {}).get(campaign_id, {})
    rungs = _rung_rows(laws, measured, graphs)
    deepest = rungs[-1] if rungs else None
    states = scan["states"].get(campaign_id, {})
    terms = list(spec.get("operator_whitelist") or [])
    hand_fed = ((spec.get("search_policy") or {}).get("kind") == "hand")
    term_pool = terms
    if hand_fed:
        terms = (scan.get("hand_terms") or {}).get(campaign_id) or terms
    return {
        "campaign_id": campaign_id,
        "name": spec.get("name"),
        "quadrant": quadrant_label(spec),
        "temperature": temperature_of(spec),
        "mean_degree_window": (spec.get("limits") or {}).get("mean_degree_window"),
        "status": campaign.get("status"),
        "state": state,
        "workers_target": campaign.get("workers_target"),
        "worker_share": ("all" if campaign.get("workers_target") is None
                         else int(campaign["workers_target"])),
        "slots_held": held_now,
        "analyses_running": analyses_now,
        "analyses_queued": int((scan.get("analyses_queued") or {}).get(campaign_id, 0)),
        "work_queued": int((scan["running"].get(campaign_id) or {}).get("queued", 0)),
        "created_utc": campaign.get("created_utc"),
        "created_build": campaign.get("created_build"),
        "mode": spec.get("mode"),
        "campaign_role": campaign.get("campaign_role"),
        "parent_campaign_id": campaign.get("parent_campaign_id"),
        "campaign_series_id": campaign.get("campaign_series_id"),
        "science_contract_hash": campaign.get("science_contract_hash"),
        "change_reason": campaign.get("change_reason"),
        "extend_only": repo.campaign_extend_only(campaign_id),
        "terms": terms,
        "term_count": len(terms),
        "hand_fed": hand_fed,
        "term_pool": term_pool if hand_fed and set(term_pool) != set(terms) else None,
        "control_verdict": (scan.get("control_verdicts") or {}).get(campaign_id),
        "draw": draw_of(spec),
        "group": (spec.get("study_design") or {}).get("group"),
        "study": (None if (spec.get("study_design") or {}).get("study") in (None, "")
                  else str(spec["study_design"]["study"])),
        "design_kind": (spec.get("study_design") or {}).get("kind"),
        "focus_part": ((spec.get("study_design") or {}).get("focus") or {}).get("part"),
        "grid": (spec.get("search_policy") or {}).get("grid"),
        "complexity_budget": spec.get("complexity_budget"),
        "ladder_declared": [int(n) for n in (spec.get("ladder") or [])],
        "rungs": rungs,
        "top_rungs": list(reversed(rungs[-TOP_RUNGS:])),
        "deepest_n": deepest["n"] if deepest else None,
        "deepest_laws": deepest["laws"] if deepest else 0,
        "laws_total": int(sum(states.values())),
        "chains_per_seed": chains_per_seed(spec),
        "graphs_total": int(sum(graphs.values())),
        "graphs_finished": int(sum(((scan.get("finished") or {}).get(campaign_id) or {}).values())),
        "graphs_created": int(sum(((scan.get("created") or {}).get(campaign_id) or {}).values())),
        "graphs_bought": int(sum(((scan.get("bought") or {}).get(campaign_id) or {}).values())),
        "laws_by_state": dict(sorted(states.items())),
        "laws_terminal": int(sum(count for name, count in states.items()
                                 if name in TERMINAL_CANDIDATE_STATES)),
        "held": int(scan["held"].get(campaign_id, 0)),
        "surveyed": surveyed,
        "law_budget": budget,
        "study_batch": bool((budget or {}).get("law_budget")),
        "core_seconds": float((scan["compute"].get(campaign_id) or {}).get("core_seconds", 0.0)),
        "compute_hours": round(
            float((scan["compute"].get(campaign_id) or {}).get("core_seconds", 0.0)) / 3600.0, 1),
        "high_score": high_score(cache_root, campaign_id),
        "stopped_by_rule": list(scan["stopped"].get(campaign_id, [])),
        "laws_stopped": int(sum(row["laws"] for row in scan["stopped"].get(campaign_id, []))),
        "meeting_readings": dict((scan.get("given_chains") or {}).get(campaign_id, {})),
        "archived": campaign.get("status") == "archived",
        "controls": _controls(repo, campaign, actives),
    }


def campaign_list(repo) -> list[dict]:
    payload = []
    for row in repo.conn.execute(
            "SELECT campaign_id,status,created_utc,spec_json FROM campaigns ORDER BY created_utc").fetchall():
        spec = json.loads(row["spec_json"])
        link = repo.campaign_link(row["campaign_id"])
        design = spec.get("study_design") or {}
        payload.append({"campaign_id": row["campaign_id"], "status": row["status"], "created_utc": row["created_utc"],
                        "mode": spec.get("mode", "bounded"), "name": spec.get("name"),
                        "parent_campaign_id": link and link["parent_campaign_id"], "channel": link and link["channel"],
                        "study": None if design.get("study") in (None, "") else str(design["study"])})
    return payload


def overview(repo, cache_root=None, *, slow: dict | None = None, campaigns: list | None = None) -> dict:
    campaigns = repo.all_campaigns() if campaigns is None else campaigns
    actives = sum(1 for row in campaigns if row.get("status") == "active")
    scan = (_slow_scan(repo) if slow is None else slow) | _live_scan(repo)
    rows = [_campaign_row(repo, row, scan, actives, cache_root)
            for row in campaigns]
    rows.sort(key=lambda row: (0, int(row["campaign_id"]), "") if str(row.get("campaign_id")).isdigit()
              else (1, 0, str(row.get("campaign_id"))))
    study_work = work_left.attach(rows, scan.get("work") or {}, scan.get("queued") or {}, scan["compute"],
                                  worker_pool(), {str(c["campaign_id"]): c.get("spec") or {} for c in campaigns},
                                  climbing=scan.get("climbing") or {},
                                  by_size={"climbing": scan.get("climbing_by_size") or {},
                                           "measured": scan.get("measured") or {}, "laws": scan.get("laws") or {}})
    return {
        "contract": CAMPAIGN_MANAGER_CONTRACT,
        "reporting_campaign_id": reporting_focus(repo),
        "fleet_paused": repo.get_flag("paused", "0") == "1",
        "fleet_workers": fleet_workers_state(repo),
        "workload": workload_state(repo),
        "auto_extend": auto_extend_state(repo),
        "worker_pool": worker_pool(),
        "campaigns": rows,
        "work_left": study_work,
        "defaults": _defaults_summary(),
        "terms": catalogue(),
        "reading": ("`laws` at a rung counts every law bought into it, whatever became of it; "
                    "`measured` counts the ones that produced evidence there. They differ, and "
                    "the difference is how much of a rung was paid for and not read. A share "
                    "of the fleet is a number of simulation slots a campaign may hold at once; "
                    "the campaigns furthest below their share are offered work first. `stopped` "
                    "groups the laws the engine stopped by the rule that stopped them, which is "
                    "what a term set and a grid actually bought."),
    }


def _mark_stale() -> None:
    with _AGGREGATES_LOCK:
        for entry in _AGGREGATES.values():
            entry["built"] = float("-inf")


def _rebuild_aggregates(target: str, signature: str) -> None:
    held = _AGGREGATES[target]
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.operations.subprocesses import yield_this_thread
    yield_this_thread()
    repo = None
    try:
        repo = Repo(target)
        slow = _slow_scan(repo)
        with _AGGREGATES_LOCK:
            held.update(slow=slow, signature=signature, built=time.monotonic(), error=None)
    except Exception as exc:
        with _AGGREGATES_LOCK:
            held["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if repo is not None:
            repo.close()
        with _AGGREGATES_LOCK:
            held["refreshing"] = False


def warm_aggregates(target) -> bool:
    key = str(target)
    with _AGGREGATES_LOCK:
        held = _AGGREGATES.setdefault(key, {})
        if held.get("slow") is not None or held.get("refreshing"):
            return False
        held["refreshing"] = True
    threading.Thread(target=_rebuild_aggregates, args=(key, ""),
                     name="gsd-campaigns-overview", daemon=True).start()
    return True


def _aggregates(repo, signature: str, active: bool) -> tuple[dict, dict]:
    now = time.monotonic()
    target = getattr(repo, "db_target", None)
    with _AGGREGATES_LOCK:
        held = _AGGREGATES.setdefault(str(target), {})
        entry = dict(held)
    if entry.get("slow") is None:
        slow = _slow_scan(repo)
        with _AGGREGATES_LOCK:
            held.update(slow=slow, signature=signature, built=time.monotonic(),
                        error=None, refreshing=False)
        return slow, {"age_seconds": 0.0, "refreshing": False, "error": None}
    ttl = _ACTIVE_TTL if active else _SETTLED_TTL
    due = entry.get("signature") != signature or now - float(entry.get("built") or 0.0) >= ttl
    refreshing = bool(entry.get("refreshing"))
    if due and not refreshing:
        if target is None:
            slow = _slow_scan(repo)
            with _AGGREGATES_LOCK:
                held.update(slow=slow, signature=signature, built=time.monotonic(), error=None)
            return slow, {"age_seconds": 0.0, "refreshing": False, "error": None}
        with _AGGREGATES_LOCK:
            start = not held.get("refreshing")
            held["refreshing"] = True
        if start:
            threading.Thread(target=_rebuild_aggregates, args=(str(target), signature),
                             name="gsd-campaigns-overview", daemon=True).start()
        refreshing = True
    built = float(entry.get("built") or 0.0)
    age = None if built == float("-inf") else round(max(0.0, now - built), 1)
    return entry["slow"], {"age_seconds": age, "refreshing": refreshing, "error": entry.get("error")}


def cached_overview(repo, cache_root=None) -> dict:
    campaigns = repo.all_campaigns()
    signature = "|".join(f"{row['campaign_id']}:{row.get('status')}" for row in campaigns)
    active = any(row.get("status") == "active" for row in campaigns)
    slow, freshness = _aggregates(repo, signature, active)
    payload = overview(repo, cache_root, slow=slow, campaigns=campaigns)
    payload["aggregates"] = freshness
    return payload


def temperature_of(spec: dict) -> str:
    drawn = (((spec or {}).get("search_policy") or {}).get("grid") or {}).get("zero_temperature")
    if drawn is None:
        from graph_scale_dynamics.operations.study_design import axes_of
        designed = (axes_of(spec) or {}).get("zero_temperature")
        drawn = None if designed is None else [bool(designed)]
    values = {bool(v) for v in drawn} if isinstance(drawn, list) and drawn else {False}
    return "both" if len(values) > 1 else ("zero" if True in values else "finite")


def definition(repo, campaign: dict) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.operations import study
    from graph_scale_dynamics.scheduling.limits import estimated_seconds
    campaign_id = str(campaign.get("campaign_id"))
    spec = campaign.get("spec") or {}
    limits = spec.get("limits") or {}
    policy = Policy.from_spec(spec)
    ladder = [int(n) for n in (spec.get("ladder") or [])]
    budget = study.budget_state(repo, campaign_id, spec) or {"law_budget": None, "laws_held": study.laws_held(repo, campaign_id)}
    return {"quadrant": study.quadrant_label(spec), "name": spec.get("name"),
            "temperature": temperature_of(spec),
            "mean_degree_window": limits.get("mean_degree_window"),
            "dense_cap": policy.dense_cap, "dense_from_n": policy.dense_from_n,
            "empty_mean_degree": policy.empty_mean_degree, "empty_from_n": policy.empty_from_n,
            "connectivity_floor": policy.connectivity_floor, "connectivity_from_n": policy.connectivity_from_n,
            "salt": policy.audit_fraction, "salt_shares": [list(s) for s in policy.salt_shares], "ladder": ladder,
            "work_budgets": [[n, policy.work_budget(n), estimated_seconds(spec, n)] for n in ladder]
            if policy.work_budgets else [],
            "law_budget": budget, "search_seed": campaign.get("search_seed"),
            "complexity_budget": spec.get("complexity_budget")}


def panel(repo, campaign_id: str, cache_root=None) -> dict:
    campaign = repo.campaign(str(campaign_id))
    if campaign is None:
        return {"available": False, "reason": f"no campaign {campaign_id} in this folder"}
    campaigns = repo.all_campaigns()
    signature = "|".join(f"{row['campaign_id']}:{row.get('status')}" for row in campaigns)
    slow, _ = _aggregates(repo, signature, any(row.get("status") == "active" for row in campaigns))
    scan = slow | _live_scan(repo)
    actives = sum(1 for row in campaigns if row.get("status") == "active")
    row = _campaign_row(repo, campaign, scan, actives, cache_root)
    parent_id = campaign.get("parent_campaign_id")
    parent = repo.campaign(str(parent_id)) if parent_id else None
    diff = None
    if parent is not None:
        diff = selection_diff(list((parent.get("spec") or {}).get("operator_whitelist") or []),
                              row["terms"])
    events = [dict(event) for event in repo.campaign_events(str(campaign_id))]
    return {"available": True, "contract": CAMPAIGN_MANAGER_CONTRACT, "campaign": row,
            "parent_terms": list((parent.get("spec") or {}).get("operator_whitelist") or [])
            if parent is not None else None,
            "term_diff": diff, "events": events[-80:],
            "search_policy_grid": ((campaign.get("spec") or {}).get("search_policy") or {}).get("grid"),
            "definition": definition(repo, campaign),
            "frozen": inherited_fields(campaign.get("spec") or {}),
            "terms": catalogue()}


def read(repo, rest: list[str], cache_root=None) -> tuple[dict, int]:
    if rest[:1] == ["overview"] and len(rest) == 1:
        return cached_overview(repo, cache_root), 200
    if rest[:1] == ["panel"] and len(rest) == 2:
        return panel(repo, rest[1], cache_root), 200
    return {"error": "not found"}, 404


SPEC_FIELD_READINGS = {
    "ladder": "the system sizes N a law can climb through",
    "extension_ladder": "the rungs above the base block, bought one at a time by settling",
    "budgets": "hard limits: the largest N, and a wall-clock lifetime (null means none)",
    "complexity_budget": "the most a law's terms may cost together",
    "max_active_candidates": "how many laws may be in their base block at once",
    "proposer": "pool_min: how many proposed laws are kept waiting",
    "limits": "stop rules: the connectivity floor, and the mean-degree window set above (566)",
    "policy": "the decision rules and their thresholds",
    "engine": "the decision engine contract and its rung sizes",
    "base_block": "how the first rungs are measured",
    "default_seeds": "independent chains per rung",
    "stage_seeds": "independent chains per rung, by stage",
    "sampling_contract": "how a chain decides it has sampled enough",
    "resource_governor": "compute throttling; operational, not scientific",
    "resource_limits": "memory lanes for deep rungs; operational, not scientific",
    "rung_extension": "memory estimates for extending a rung; operational",
    "analysis_version": "the measurement contract the evidence is read with",
    "search_space_version": "the search contract version",
    "mode": "continuous runs until paused; finite stops at its budget",
    "search_policy": "blind search; its grid is what the author edits above",
    "name": "a label",
    "description": "a label",
}

_AUTHORED_FIELDS = {"operator_whitelist"}


def _defaults_summary() -> dict:
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    spec = shipped_spec()
    return {"grid": (spec.get("search_policy") or {}).get("grid"),
            "complexity_budget": spec.get("complexity_budget"),
            "terms": list(spec.get("operator_whitelist") or [])}


def inherited_fields(spec: dict) -> list[dict]:
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    shipped = freeze_campaign_spec(shipped_spec())
    spec = freeze_campaign_spec(spec)
    out = []
    for key in sorted(spec):
        if key in _AUTHORED_FIELDS or key.endswith("_contract"):
            continue
        value = spec[key]
        if key == "search_policy":
            value = {k: v for k, v in (value or {}).items() if k != "grid"}
            base = {k: v for k, v in (shipped.get(key) or {}).items() if k != "grid"}
        else:
            base = shipped.get(key)
        out.append({"field": key, "value": value,
                    "reading": SPEC_FIELD_READINGS.get(key, ""),
                    "shipped_default": key in shipped and value == base})
    return out


def delete_problems(repo, campaign: dict) -> list[str]:
    campaign_id = str(campaign["campaign_id"])
    problems = []
    state = derived_state(campaign, chains_running=campaign_chains_running(repo, campaign_id))
    if state == ACTIVE:
        problems.append("pause it first; a running campaign is never deleted")
    elif state == PAUSING:
        problems.append("its chains are still saving their position; wait for the pause to land")
    children = [str(row["child_campaign_id"]) for row in repo.dependent_campaigns(campaign_id)]
    if children:
        problems.append("campaign " + ", ".join(children)
                        + (" was" if len(children) == 1 else " were")
                        + " cloned from it; delete " + ("that" if len(children) == 1 else "those")
                        + " first")
    return problems


def _delete(repo, campaign_id: str, body: dict) -> tuple[dict, int]:
    campaign = repo.campaign(campaign_id)
    if campaign is None:
        return {"error": f"unknown campaign {campaign_id}"}, 404
    if str(body.get("confirm") or "").strip() != str(campaign_id):
        return {"error": f"type {campaign_id} to confirm the deletion"}, 400
    problems = delete_problems(repo, campaign)
    if problems:
        return {"error": "; ".join(problems)}, 409
    from graph_scale_dynamics.operations.maintenance import exclusive_maintenance
    with exclusive_maintenance(repo):
        campaign = repo.campaign(campaign_id)
        if campaign is None:
            return {"error": f"unknown campaign {campaign_id}"}, 404
        problems = delete_problems(repo, campaign)
        if problems:
            return {"error": "; ".join(problems) + " (it changed while the deletion waited its turn)"}, 409
        stopped = repo.stop_campaign_work(campaign_id, reason="campaign deleted from the Campaigns page")
        removed = repo.delete_campaign(campaign_id, force=True)
    if str(repo.get_flag(FOCUS_FLAG, "") or "") == str(campaign_id):
        repo.set_flag(FOCUS_FLAG, "")
    _mark_stale()
    return {"ok": True, "deleted": str(campaign_id), "stopped": stopped, "removed": removed,
            "reading": ("the campaign's database state is gone; its raw result blobs stay on disk "
                        "until `main.py artifacts gc` collects them")}, 200


def _spec_for_create(repo, body: dict) -> tuple[dict | None, str | None, str | None]:
    terms = body.get("operator_whitelist")
    if terms is not None and not isinstance(terms, list):
        return None, None, "operator_whitelist must be a list of term names"
    grid = body.get("grid")
    if grid is not None and not isinstance(grid, dict):
        return None, None, "grid must be an object of grid list names to values"
    parent_id = str(body.get("parent_campaign_id") or "").strip()
    if not parent_id:
        return None, None, ("a new campaign is cloned from one this folder already holds; "
                            "choose the campaign to clone from")
    cloned = clone_spec(repo, parent_id, operator_whitelist=terms, grid=grid,
                        mean_degree_window=body.get("mean_degree_window"))
    if not cloned["ok"]:
        return None, None, cloned["problem"]
    return cloned["spec"], cloned.get("parent_campaign_id"), None


def fleet_workers_state(repo) -> dict:
    from graph_scale_dynamics.scheduling import worker_count
    return worker_count.state_of(repo, worker_pool())


def fleet_workers(repo, value) -> tuple[dict, int]:
    from graph_scale_dynamics.scheduling import worker_count
    most = worker_count.most_of(repo.get_flag(worker_count.MOST_FLAG), worker_pool())
    count, problem = worker_count.asked(value, most)
    if problem:
        return {"error": problem, "most": most}, 400
    repo.set_flag(worker_count.FLAG, "" if count is None else str(count))
    repo.emit("worker_count_asked", {"contract": worker_count.CONTRACT, "target": count, "most": most})
    _mark_stale()
    return {"ok": True} | fleet_workers_state(repo), 200


def workload_state(repo) -> dict:
    from graph_scale_dynamics.scheduling import work_groups
    return work_groups.reading(repo)


def workload(repo, body: dict) -> tuple[dict, int]:
    from graph_scale_dynamics.scheduling import work_groups
    try:
        if body.get("split") is not None:
            work_groups.set_shares(repo, work_groups.split_of(str(body["split"])))
        if body.get("system_cpus") is not None:
            work_groups.set_system(repo, str(body["system_cpus"]))
    except ValueError as exc:
        return {"error": str(exc)} | workload_state(repo), 400
    found = workload_state(repo)
    repo.emit("workload_asked", {"contract": work_groups.CONTRACT, "shares": found["shares"],
                                 "system_cpus": found["system_cpus"]})
    _mark_stale()
    return {"ok": True} | found, 200


def handle(repo, body: dict) -> tuple[dict, int]:
    action = str(body.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return {"error": f"action must be one of {', '.join(ACTIONS)}",
                "hint": "campaigns are never archived from this page"}, 400
    campaign_id = str(body.get("campaign_id") or "").strip()
    reason = str(body.get("reason") or "").strip() or None

    if action in HELD_BY_A_QUIET_REPORT:
        from graph_scale_dynamics.operations.quiet_report import holding
        held = holding(repo)
        if held:
            return {"error": held}, 409

    if action == "auto_extend":
        from graph_scale_dynamics.operations import auto_extend
        outcome = auto_extend.switch(repo, body.get("on") in (True, 1, "1", "on", "true"))
        _mark_stale()
        return outcome, 200

    if action == "fleet_workers":
        return fleet_workers(repo, body.get("workers"))

    if action == "workload":
        return workload(repo, body)

    if action in {"fleet_pause", "fleet_resume"}:
        wanted = action == "fleet_pause"
        repo.set_flag("paused", "1" if wanted else "0")
        cancelled = (repo.operator_pause_cancel_active_work(
            reason="operator stopped the fleet from the Campaigns page") if wanted else None)
        _mark_stale()
        return {"ok": True, "fleet_paused": wanted, "cancellation": cancelled,
                "reading": ("every campaign is stopped and every leased job is back in its "
                            "queue; those rungs start again from the beginning"
                            if wanted else "the fleet claims work again")}, 200

    if action in {"pause", "resume", "reopen"}:
        act = {"pause": pause, "resume": resume, "reopen": reopen}[action]
        extra = {"reason": reason} if reason else {}
        if action == "pause" and body.get("fence"):
            extra["fence"] = True
        outcome = act(repo, campaign_id, **extra)
        if not outcome["ok"]:
            return {"error": outcome["problem"]}, 409
        _mark_stale()
        return outcome, 200

    if action == "workers":
        target = body.get("workers_target")
        outcome = set_workers(repo, campaign_id,
                              None if target in (None, "", "all") else target,
                              **({"reason": reason} if reason else {}))
        if not outcome["ok"]:
            return {"error": outcome["problem"]}, 409
        _mark_stale()
        return outcome, 200

    if action == "budget":
        from graph_scale_dynamics.operations.study import set_law_budget
        laws = body.get("law_budget")
        outcome = set_law_budget(repo, campaign_id, None if laws in (None, "", "none") else laws,
                                 **({"reason": reason} if reason else {}))
        if not outcome["ok"]:
            return {"error": outcome["problem"]}, 409
        _mark_stale()
        return outcome, 200

    if action == "allocate":
        wanted = body.get("allocation")
        if not isinstance(wanted, dict) or not wanted:
            return {"error": "allocation must be an object of campaign id to worker count"}, 400
        outcome = apply_allocation(repo, {str(k): v for k, v in wanted.items()},
                                   **({"reason": reason} if reason else {}))
        if not outcome["ok"]:
            return {"error": outcome["problem"], "outcomes": outcome["outcomes"]}, 409
        _mark_stale()
        return outcome, 200


    if action == "preflight":
        spec, _parent, problem = _spec_for_create(repo, body)
        if problem:
            return {"error": problem}, 400
        grid = (spec.get("search_policy") or {}).get("grid")
        pool = (spec.get("proposer") or {}).get("pool_min")
        verdict = preflight(list(spec.get("operator_whitelist") or []), grid,
                            spec.get("complexity_budget"),
                            pool_min=int(pool) if isinstance(pool, int) else None)
        return dict(verdict, grid=grid, complexity_budget=spec.get("complexity_budget"),
                    mean_degree_window=window_of(spec), inherited=inherited_fields(spec)), 200

    if action == "delete":
        return _delete(repo, campaign_id, body)

    if action == "clone":
        cloned = clone_spec(repo, campaign_id,
                            operator_whitelist=body.get("operator_whitelist"),
                            grid=body.get("grid"), mean_degree_window=body.get("mean_degree_window"))
        if not cloned["ok"]:
            return {"error": cloned["problem"]}, 404
        return cloned, 200

    return _create(repo, body, reason)


_CREATE_LOCK = threading.Lock()
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
CREATE_REQUEST_FLAG = "campaign_create_request:"


def _create(repo, body: dict, reason: str | None) -> tuple[dict, int]:
    request_id = str(body.get("request_id") or "")
    if not request_id:
        return _create_once(repo, body, reason)
    if not _REQUEST_ID.match(request_id):
        return {"error": "request_id must be 8 to 64 letters, digits, '-' or '_'"}, 400
    import hashlib
    import json as _json
    contents = hashlib.sha256(_json.dumps({k: v for k, v in body.items() if k != "request_id"}, sort_keys=True,
                                          default=str).encode("utf-8")).hexdigest()[:16]
    key = f"{CREATE_REQUEST_FLAG}{request_id}:{contents}"
    with _CREATE_LOCK:
        made = repo.get_flag(key, "")
        if made and repo.campaign(made):
            return {"ok": True, "campaign_id": made, "repeated": True,
                    "reading": "this start was already made; the campaign it made is the one shown"}, 200
        return _create_once(repo, body, reason, made=lambda campaign_id: repo.set_flag(key, campaign_id))


def _create_once(repo, body: dict, reason: str | None, made=None) -> tuple[dict, int]:
    spec, parent_id, problem = _spec_for_create(repo, body)
    if problem:
        return {"error": problem}, 400
    if not reason:
        cloned = clone_spec(repo, str(body.get("parent_campaign_id") or ""),
                            operator_whitelist=body.get("operator_whitelist"),
                            grid=body.get("grid"), mean_degree_window=body.get("mean_degree_window"))
        reason = cloned.get("suggested_reason") if cloned.get("ok") else None
    try:
        created = create_campaign(
            repo, spec, parent_campaign_id=parent_id,
            reason=reason or "campaign authored from the Campaigns page")
    except ValueError as refused:
        return {"error": str(refused)}, 409
    campaign_id = str(created["campaign_id"])
    if made is not None:
        made(campaign_id)
    allocation = body.get("allocation")
    if isinstance(allocation, dict) and allocation:
        apply_allocation(repo, {str(k): v for k, v in allocation.items()}
                         | {campaign_id: allocation.get(campaign_id)},
                         reason=f"fleet divided when campaign {campaign_id} was created")
    _mark_stale()
    return {"ok": True, "campaign_id": campaign_id,
            "terms": list(spec.get("operator_whitelist") or []),
            "reading": ("the campaign is created and its term set is frozen; a different term "
                        "set is a new campaign cloned from this one. Its share of the fleet is "
                        "not frozen and can be changed whenever you like.")}, 200


def body_from(raw: bytes) -> dict:
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
