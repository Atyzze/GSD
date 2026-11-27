from __future__ import annotations

import math

from copy import deepcopy
import json
import secrets

from graph_scale_dynamics.db.repo import utc_now as _utc_now
from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_CAMPAIGN_PAUSED

CAMPAIGN_CONTROL_CONTRACT = "gsd-campaign-control-1"

PAUSE_MEMO_PREFIX = "paused_was_extend_only:"

ACTIVE = "active"

PAUSED = "paused"

PAUSING = "pausing"


def derived_state(campaign: dict, *, chains_running: int = 0) -> str:
    status = str(campaign.get("status") or "")
    if status == "active" and campaign.get("workers_target") == 0:
        return PAUSING if int(chains_running or 0) > 0 else PAUSED
    return status


def is_paused(repo, campaign_id: str) -> bool:
    row = repo.conn.execute(
        "SELECT status,workers_target FROM campaigns WHERE campaign_id=?",
        (str(campaign_id),),
    ).fetchone()
    return row is not None and derived_state(dict(row)) in (PAUSED, PAUSING)


def paused_reason(repo, campaign_id: str | None) -> str | None:
    if repo.get_flag("paused", "0") == "1":
        return "fleet stopped"
    if campaign_id and is_paused(repo, campaign_id):
        return "campaign paused"
    return None


def pause_attempt_class(stop_reason: str | None) -> str | None:
    from graph_scale_dynamics.db.repo import ATTEMPT_CLASS_FLEET_PAUSED
    from graph_scale_dynamics.domain.model import (ATTEMPT_CLASS_DEPTH_YIELD, ATTEMPT_CLASS_LANE_YIELD,
                                                   DEPTH_YIELD_REASON, LANE_YIELD_REASON)
    if stop_reason is None:
        return None
    if stop_reason == LANE_YIELD_REASON:
        return ATTEMPT_CLASS_LANE_YIELD
    if stop_reason == DEPTH_YIELD_REASON:
        return ATTEMPT_CLASS_DEPTH_YIELD
    return (ATTEMPT_CLASS_FLEET_PAUSED if stop_reason == "fleet stopped"
            else ATTEMPT_CLASS_CAMPAIGN_PAUSED)


def _campaign_or_problem(repo, campaign_id: str) -> tuple[dict | None, str | None]:
    campaign = repo.campaign(str(campaign_id)) if campaign_id else None
    if campaign is None:
        return None, f"unknown campaign {campaign_id}"
    return campaign, None


def pause(repo, campaign_id: str, *, reason: str = "operator paused the campaign",
          fence: bool = False) -> dict:
    campaign, problem = _campaign_or_problem(repo, campaign_id)
    if problem:
        return {"ok": False, "problem": problem}
    campaign_id = str(campaign_id)
    if derived_state(campaign) == PAUSED:
        return {"ok": True, "state": PAUSED, "changed": False,
                "reading": "already paused"}
    if campaign.get("status") != "active":
        return {"ok": False, "problem": (
            f"only an active campaign can be paused; {campaign_id} is {campaign.get('status')}. "
            "A closed campaign is reopened rather than resumed.")}
    was_extend_only = repo.campaign_extend_only(campaign_id)
    was_share = campaign.get("workers_target")
    repo.set_flag(f"{PAUSE_MEMO_PREFIX}{campaign_id}",
                  json.dumps({"extend_only": bool(was_extend_only), "workers_target": was_share}))
    repo.set_campaign_extend_only(campaign_id, True)
    repo.set_workers_target(campaign_id, 0)
    fenced = fence_campaign_leases(repo, campaign_id, reason=reason) if fence else 0
    running = 0 if fence else campaign_chains_running(repo, campaign_id)
    repo.record_campaign_event(campaign_id, "campaign_paused", {
        "reason": reason, "was_extend_only": bool(was_extend_only),
        "was_workers_target": was_share, "fenced": int(fenced),
        "chains_still_saving": int(running),
        "contract": CAMPAIGN_CONTROL_CONTRACT,
    })
    return {"ok": True, "state": PAUSING if running else PAUSED, "changed": True,
            "was_extend_only": bool(was_extend_only), "chains_running": int(running),
            "fenced": int(fenced),
            "reading": (f"{fenced} leased job(s) returned to the queue; the fleet is free now "
                        "and those rungs start again from the beginning"
                        if fence else
                        (f"no new work is claimed for this campaign; {running} chain(s) are "
                         "saving their position and will resume byte-identically"
                         if running else
                         "no new simulation, analysis or proposal work is claimed for this "
                         "campaign; nothing queued was cancelled"))}


def resume(repo, campaign_id: str, *, reason: str = "operator resumed the campaign") -> dict:
    campaign, problem = _campaign_or_problem(repo, campaign_id)
    if problem:
        return {"ok": False, "problem": problem}
    campaign_id = str(campaign_id)
    if campaign.get("status") != "active":
        return {"ok": False, "problem": (
            f"{campaign_id} is {campaign.get('status')}, not paused; reopen it instead")}
    if derived_state(campaign) != PAUSED:
        return {"ok": True, "state": "active", "changed": False, "reading": "already running"}
    memo = _pause_memo(repo, campaign_id)
    repo.set_campaign_extend_only(campaign_id, memo["extend_only"])
    repo.set_workers_target(campaign_id, memo["workers_target"])
    repo.set_flag(f"{PAUSE_MEMO_PREFIX}{campaign_id}", "")
    repo.record_campaign_event(campaign_id, "campaign_resumed", {
        "reason": reason, "extend_only_restored": memo["extend_only"],
        "workers_target": memo["workers_target"],
        "contract": CAMPAIGN_CONTROL_CONTRACT,
    })
    return {"ok": True, "state": "active", "changed": True,
            "extend_only_restored": memo["extend_only"],
            "workers_target": memo["workers_target"],
            "reading": ("claiming is open again with the share it had; every checkpointed "
                        "chain continues from the position it saved")}


def fence_campaign_leases(repo, campaign_id: str, *, reason: str) -> int:
    now = _utc_now()
    repo.begin_transaction(attempts=12)
    try:
        leased = [str(row["job_id"]) for row in repo.conn.execute(
            "SELECT job_id FROM jobs WHERE campaign_id=? AND status='leased' FOR UPDATE",
            (str(campaign_id),)).fetchall()]
        if leased:
            marks = ",".join("?" for _ in leased)
            repo.conn.execute(
                "UPDATE attempts SET finished_utc=COALESCE(finished_utc,?),"
                "wall_seconds=COALESCE(wall_seconds,GREATEST(0,EXTRACT(EPOCH FROM "
                "(CURRENT_TIMESTAMP-started_utc::timestamptz)))),"
                "exit_code=COALESCE(exit_code,-15),error=COALESCE(error,?),"
                f"error_class=COALESCE(error_class,'{ATTEMPT_CLASS_CAMPAIGN_PAUSED}') "
                f"WHERE finished_utc IS NULL AND job_id IN ({marks})",
                (now, reason, *leased))
        jobs = repo.conn.execute(
            "UPDATE jobs SET status='queued',lease_owner=NULL,lease_expires_utc=NULL,"
            "memory_reservation_bytes=0,lease_generation=lease_generation+1,"
            "attempts=GREATEST(0,attempts-1),next_attempt_utc=NULL,updated_utc=?,error=NULL "
            "WHERE campaign_id=? AND status='leased'", (now, str(campaign_id))).rowcount
        repo.conn.execute(
            "UPDATE analysis_queue SET status='queued',lease_owner=NULL,claim_token=NULL,"
            "lease_expires_utc=NULL,memory_reservation_bytes=0,next_attempt_utc=NULL,"
            "attempts=GREATEST(0,attempts-1),error=NULL,error_class=NULL,updated_utc=? "
            "WHERE campaign_id=? AND status='leased'", (now, str(campaign_id)))
        repo.conn.execute("COMMIT")
        return int(jobs or 0)
    except Exception:
        repo.conn.rollback_if_open()
        raise


def campaign_chains_running(repo, campaign_id: str) -> int:
    row = repo.conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE campaign_id=? AND kind='simulate' "
        "AND status='leased'", (str(campaign_id),)).fetchone()
    return int((row or {"c": 0})["c"] or 0)


def analysis_stop_reason(repo, campaign_id: str, now: str | None = None) -> str | None:
    from graph_scale_dynamics.domain.model import utc_now
    row = repo.conn.execute(
        "SELECT c.status,c.workers_target,(SELECT COUNT(*) FROM jobs j WHERE j.campaign_id=c.campaign_id "
        "AND j.kind='simulate' AND j.status='leased' AND j.lease_expires_utc>=?) AS chains "
        "FROM campaigns c WHERE c.campaign_id=?", (now or utc_now(), str(campaign_id))).fetchone()
    if row is None or derived_state(dict(row)) not in (PAUSED, PAUSING):
        return None
    if int(row["chains"] or 0) > 0:
        return None
    return "campaign paused; its chains have saved"


def _pause_memo(repo, campaign_id: str) -> dict:
    raw = repo.get_flag(f"{PAUSE_MEMO_PREFIX}{campaign_id}", "")
    try:
        stored = json.loads(raw)
    except ValueError:
        return {"extend_only": raw == "1", "workers_target": None}
    if not isinstance(stored, dict):
        return {"extend_only": False, "workers_target": None}
    share = stored.get("workers_target")
    return {"extend_only": bool(stored.get("extend_only")),
            "workers_target": int(share) if isinstance(share, int) and share > 0 else None}


def reopen_problems(repo, campaign_id: str) -> list[str]:
    from graph_scale_dynamics.scheduling.provenance import provenance_mismatches
    campaign = repo.campaign(str(campaign_id)) if campaign_id else None
    if campaign is None:
        return [f"unknown campaign {campaign_id}"]
    status = campaign.get("status")
    if status == "active":
        return []
    problems: list[str] = []
    if status != "closed":
        problems.append(f"only a closed campaign can be reopened; this one is {status}")
    if repo.campaign_link(str(campaign_id)) is not None:
        problems.append("a linked confirmation child stays a sealed lifecycle record")
    if campaign["spec"].get("mode") not in {"continuous", "finite"}:
        problems.append(f"reopen does not support campaign mode {campaign['spec'].get('mode')}")
    problems.extend(provenance_mismatches(campaign))
    return problems


def reopen(repo, campaign_id: str, *,
           reason: str = "operator reopened a closed campaign") -> dict:
    campaign, problem = _campaign_or_problem(repo, campaign_id)
    if problem:
        return {"ok": False, "problem": problem}
    campaign_id = str(campaign_id)
    if campaign.get("status") == "active":
        return {"ok": True, "state": derived_state(campaign), "changed": False,
                "reading": "already active"}
    problems = reopen_problems(repo, campaign_id)
    if problems:
        return {"ok": False, "problem": "; ".join(problems)}
    repo.set_workers_target(campaign_id, None)
    restored = None
    if repo.get_flag(f"{PAUSE_MEMO_PREFIX}{campaign_id}", ""):
        restored = _pause_memo(repo, campaign_id)["extend_only"]
        repo.set_campaign_extend_only(campaign_id, restored)
        repo.set_flag(f"{PAUSE_MEMO_PREFIX}{campaign_id}", "")
    repo.set_campaign_status(campaign_id, "active")
    if campaign["spec"].get("mode") == "continuous":
        repo.set_flag("home_campaign", campaign_id)
    revived = repo.revive_stopped_work(campaign_id)
    repo.record_campaign_event(campaign_id, "campaign_reopened", {
        "reason": reason, "search_seed": int(campaign["search_seed"]),
        "contract": CAMPAIGN_CONTROL_CONTRACT, "revived": revived,
        **({"extend_only_restored": restored} if restored is not None else {}),
    })
    return {"ok": True, "state": "active", "changed": True, "revived": revived,
            "search_seed": int(campaign["search_seed"]),
            "reading": ("reopened with its original immutable policy and search seed; every "
                        "candidate and every measurement it already holds is still there")}


def grid_diff(parent: dict | None, child: dict | None) -> dict:
    def shape(entry, key=""):
        if entry is None:
            return "none"
        if isinstance(entry, dict) and "min" in entry and "max" in entry:
            return f"{entry['min']:g}..{entry['max']:g}"
        if key in ("local_moves", "zero_temperature") and isinstance(entry, list):
            return "/".join(str(v).lower() for v in entry) or "none"
        if isinstance(entry, dict):
            return ", ".join(sorted(str(key) for key in entry)) or "none"
        if isinstance(entry, list):
            return len(entry)
        return entry

    before = dict(parent or {})
    after = dict(child or {})
    changed = {}
    for key in sorted(set(before) | set(after)):
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        changed[key] = {"from": shape(was, key), "to": shape(now, key)}
    parts = [f"{key} {value['from']} to {value['to']}" for key, value in changed.items()]
    return {"changed": changed, "summary": "; ".join(parts) or "same grid as the parent"}


DEFAULTS = "defaults"


def shipped_spec() -> dict:
    from importlib import resources
    path = resources.files("graph_scale_dynamics") / "resources" / "configs" / "campaign_engine_survey.json"
    return json.loads(path.read_text(encoding="utf-8"))


def window_problem(window) -> str | None:
    if not isinstance(window, dict):
        return "mean_degree_window must be an object with a min and a max"
    for end in ("min", "max"):
        value = window.get(end)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"the mean-degree window's {end} must be a number"
    if window["min"] < 0:
        return "the mean-degree window's min cannot be below 0"
    if window["max"] <= window["min"]:
        return "the mean-degree window's max must be above its min"
    return None


def window_of(spec: dict) -> dict:
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.limits import limits
    effective = limits(spec)
    return {"min": effective["mean_degree_window"]["min"], "max": effective["mean_degree_window"]["max"],
            "dense_cap": Policy.from_spec(spec).dense_cap,
            "armed_from_n": effective["mean_degree_cap_armed_from_n"]}


def derive_spec(parent_spec: dict, source: str, *, operator_whitelist: list[str] | None = None,
                grid: dict | None = None, mean_degree_window: dict | None = None) -> dict:
    from graph_scale_dynamics.scheduling.term_selection import selection_diff
    parent_spec = deepcopy(parent_spec)
    parent_terms = list(parent_spec.get("operator_whitelist") or [])
    terms = list(operator_whitelist) if operator_whitelist is not None else parent_terms
    spec = deepcopy(parent_spec)
    spec["operator_whitelist"] = terms
    parent_grid = dict(((parent_spec.get("search_policy") or {}).get("grid") or {}))
    wanted_grid = dict(parent_grid)
    if grid is not None:
        if not isinstance(grid, dict):
            return {"ok": False, "problem": "search_policy.grid must be an object"}
        wanted_grid.update(grid)
        from graph_scale_dynamics.services.proposer.blind import DEFAULT_GRID, validate_grid
        problems = validate_grid(dict(DEFAULT_GRID, **wanted_grid))
        if problems:
            return {"ok": False, "problem": "; ".join(problems)}
        policy = dict(spec.get("search_policy") or {})
        policy["grid"] = wanted_grid
        spec["search_policy"] = policy
    parent_window = window_of(parent_spec)
    if mean_degree_window is not None:
        problem = window_problem(mean_degree_window)
        if problem:
            return {"ok": False, "problem": problem}
        from graph_scale_dynamics.operations.study import set_mean_degree_window
        set_mean_degree_window(spec, mean_degree_window["min"], mean_degree_window["max"])
    window = window_of(spec)
    for key in ("campaign_provenance_contract", "search_policy_contract",
                "resource_policy_contract"):
        spec.pop(key, None)
    _not_its_parents_study(spec, source)
    diff = selection_diff(parent_terms, terms)
    grids = grid_diff(parent_grid, wanted_grid)
    moved = (window["min"], window["max"]) != (parent_window["min"], parent_window["max"])
    window_change = (f"mean-degree window {window['min']:g} to {window['max']:g} (was {parent_window['min']:g} to "
                     f"{parent_window['max']:g})") if moved else None
    changes = [part for part in (diff["summary"], grids["summary"], window_change)
               if part and not part.startswith("same ")] or ["nothing changed"]
    return {"ok": True, "spec": spec, "parent_terms": parent_terms, "diff": diff,
            "parent_grid": parent_grid, "grid": wanted_grid, "grid_diff": grids,
            "parent_mean_degree_window": parent_window, "mean_degree_window": window,
            "suggested_reason": f"{source}: " + "; ".join(changes)}


STUDY_KEYS = ("study_design", "growth_study", "controls_criterion", "controls_capped_at")


def _not_its_parents_study(spec: dict, source: str) -> None:
    from graph_scale_dynamics.operations import standing_controls
    from graph_scale_dynamics.operations.study import quadrant_label
    named_as = quadrant_label(spec)
    for key in STUDY_KEYS:
        spec.pop(key, None)
    if str(spec.get("name")) == standing_controls.NAME:
        spec["name"] = shipped_spec().get("name")
    if named_as:
        spec["description"] = f"A campaign cloned from one made as {named_as} ({source})."


def clone_spec(repo, campaign_id: str, *, operator_whitelist: list[str] | None = None,
               grid: dict | None = None, mean_degree_window: dict | None = None) -> dict:
    if str(campaign_id) == DEFAULTS:
        derived = derive_spec(shipped_spec(), "started from the shipped defaults",
                              operator_whitelist=operator_whitelist, grid=grid,
                              mean_degree_window=mean_degree_window)
        if derived.get("ok"):
            derived["parent_campaign_id"] = None
        return derived
    campaign, problem = _campaign_or_problem(repo, campaign_id)
    if problem:
        return {"ok": False, "problem": problem}
    derived = derive_spec(campaign["spec"], f"cloned from campaign {campaign_id}",
                          operator_whitelist=operator_whitelist, grid=grid,
                          mean_degree_window=mean_degree_window)
    if derived.get("ok"):
        derived["parent_campaign_id"] = str(campaign_id)
    return derived


def create_campaign(repo, spec: dict, *, parent_campaign_id: str | None = None,
                    reason: str | None = None, search_seed: int | None = None,
                    role: str | None = None, report_artifact: str | None = None,
                    report_sha256: str | None = None) -> dict:
    from graph_scale_dynamics.decisions.engine import is_engine_campaign
    from graph_scale_dynamics.scheduling.campaign import validate_campaign
    from graph_scale_dynamics.scheduling.provenance import freeze_campaign_spec
    frozen = freeze_campaign_spec(spec)
    problems = validate_campaign(frozen)
    if not is_engine_campaign(frozen):
        problems.append(
            "the spec declares no decision engine (an `engine` block with its contract); "
            "campaigns without one are refused")
    if problems:
        raise ValueError("invalid frozen campaign specification: " + "; ".join(problems))
    return repo.create_campaign(
        frozen,
        search_seed=secrets.randbits(63) if search_seed is None else int(search_seed),
        role=role or str(frozen.get("campaign_role") or "discovery"),
        parent_campaign_id=parent_campaign_id, change_reason=reason,
        based_on_report_artifact=report_artifact, based_on_report_sha256=report_sha256,
    )


def claim_home_if_unset(repo, campaign_id: str) -> str:
    stored = str(repo.get_flag("home_campaign", "") or "")
    if stored and repo.campaign(stored) is not None:
        return stored
    repo.set_flag("home_campaign", str(campaign_id))
    return str(campaign_id)


def worker_pool() -> int:
    from graph_scale_dynamics.scheduling.cpu import cpu_topology
    return int(cpu_topology()[1])


def workers_problem(repo, campaign_id: str, target) -> tuple[dict | None, int | None, str | None]:
    campaign, problem = _campaign_or_problem(repo, campaign_id)
    if problem:
        return None, None, problem
    if target is not None:
        try:
            target = max(0, int(target))
        except (TypeError, ValueError):
            return None, None, f"{target!r} is not a number of workers"
    if campaign.get("status") not in {"active"}:
        return None, None, (f"{campaign_id} is {campaign.get('status')}; only an active campaign has a share "
                            "of the fleet. Reopen it first.")
    return campaign, target, None


def set_workers(repo, campaign_id: str, target: int | None, *,
                reason: str = "operator changed the campaign's share of the fleet") -> dict:
    campaign, target, problem = workers_problem(repo, campaign_id, target)
    if problem:
        return {"ok": False, "problem": problem}
    campaign_id = str(campaign_id)
    if target == 0:
        return pause(repo, campaign_id, reason=reason)
    if derived_state(campaign) == PAUSED:
        resumed = resume(repo, campaign_id, reason=reason)
        if not resumed["ok"]:
            return resumed
    repo.set_workers_target(campaign_id, target)
    repo.record_campaign_event(campaign_id, "campaign_share_changed", {
        "reason": reason, "workers_target": target, "pool": worker_pool(),
        "contract": CAMPAIGN_CONTROL_CONTRACT,
    })
    return {"ok": True, "state": derived_state(repo.campaign(campaign_id)),
            "workers_target": target, "changed": True,
            "reading": (f"this campaign may hold {target} simulation slots at once"
                        if target is not None else
                        "this campaign takes whatever the fleet has going")}


def apply_allocation(repo, allocation: dict, *,
                     reason: str = "operator re-divided the fleet") -> dict:
    outcomes = {}
    problems = [f"{campaign_id}: {problem}" for campaign_id, target in allocation.items()
                for _, _, problem in [workers_problem(repo, str(campaign_id), target)] if problem]
    if problems:
        return {"ok": False, "problem": "; ".join(problems) + "; nothing was changed",
                "outcomes": {}, "pool": worker_pool()}
    for campaign_id, target in allocation.items():
        done = set_workers(repo, str(campaign_id), target, reason=reason)
        outcomes[str(campaign_id)] = done
        if not done["ok"]:
            problems.append(f"{campaign_id}: {done['problem']}")
    return {"ok": not problems, "problem": "; ".join(problems) or None,
            "outcomes": outcomes, "pool": worker_pool()}


SURVEYED_PREFIX = "search_space_surveyed:"

SURVEYED = "surveyed"


def record_survey_complete(repo, campaign_id: str, *, held: int, wanted: int,
                           rounds: int) -> dict:
    record = {"contract": CAMPAIGN_CONTROL_CONTRACT, "state": SURVEYED,
              "held": int(held), "pool_min": int(wanted), "rounds": int(rounds),
              "at": _utc_now(),
              "reading": (f"every law this term set can write is proposed: {held} distinct "
                          f"physical laws against a pool of {wanted}. The campaign is not "
                          "stalled, it is finished proposing; the laws it holds go on being "
                          "measured. Clone it with another term, or with more scales in the "
                          "grid, to widen the space.")}
    repo.set_flag(f"{SURVEYED_PREFIX}{campaign_id}", json.dumps(record))
    repo.emit("campaign_space_surveyed", dict(record, campaign_id=campaign_id))
    return record


def survey_state(repo, campaign_id: str) -> dict | None:
    raw = repo.get_flag(f"{SURVEYED_PREFIX}{campaign_id}", "")
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def clear_survey(repo, campaign_id: str) -> None:
    if repo.get_flag(f"{SURVEYED_PREFIX}{campaign_id}", ""):
        repo.set_flag(f"{SURVEYED_PREFIX}{campaign_id}", "")


FOCUS_FLAG = "home_campaign"


def reporting_focus(repo) -> str | None:
    stored = str(repo.get_flag(FOCUS_FLAG, "") or "").strip()
    if stored:
        campaign = repo.campaign(stored)
        if campaign is not None and campaign.get("status") == ACTIVE:
            return stored
    live = [campaign for campaign in repo.active_campaigns()
            if (campaign.get("spec") or {}).get("mode") == "continuous"]
    if not live:
        return None
    live.sort(key=lambda campaign: str(campaign.get("created_utc") or ""), reverse=True)
    return str(live[0]["campaign_id"])


def set_reporting_focus(repo, campaign_id: str | None) -> None:
    repo.set_flag(FOCUS_FLAG, str(campaign_id or ""))


def clear_stale_focus(repo) -> str | None:
    stored = str(repo.get_flag(FOCUS_FLAG, "") or "").strip()
    if not stored:
        return None
    campaign = repo.campaign(stored)
    if campaign is not None and campaign.get("status") == ACTIVE:
        return None
    repo.set_flag(FOCUS_FLAG, "")
    return stored


def focus_problem(repo, campaign: dict) -> str | None:
    campaign_id = str(campaign.get("campaign_id") or "")
    if campaign.get("status") != ACTIVE:
        return f"campaign {campaign_id} is {campaign.get('status')}"
    if (campaign.get("spec") or {}).get("mode") != "continuous":
        return "reporting follows a continuous campaign"
    if repo.campaign_link(campaign_id) is not None:
        return "a linked confirmation campaign reports with the campaign it confirms"
    return None
