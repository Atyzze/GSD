from __future__ import annotations

from graph_scale_dynamics.domain.model import (
    INTERRUPTED_ATTEMPT_CLASSES, STORAGE_ATTEMPT_CLASSES, TERMINAL_CANDIDATE_STATES, CandidateState)
from graph_scale_dynamics.observability.child_diagnostics import NO_SPACE_STOP_TEXT, same_reason_exhausted
from graph_scale_dynamics.operations import memory_giveback as M
from graph_scale_dynamics.operations import scratch_repair as S

FAILURE_REPAIR_CONTRACT = "gsd-failure-repair-1"
RESCUE_CONTRACT = "gsd-failure-repair-2"
REPLAY_CONTRACT = "gsd-failure-repair-3"
COUNTED_STOP_TEXT = "third failure with reason"
REFUSED_TEXT = "memory admission refused permanently"
STORAGE_ANALYSIS_MARKERS = ("OSError", "staging_io", "no_space_left", "missing_success_receipt",
                            "missing_failure_receipt", "invalid_terminal_receipt")
ANALYSIS_LEASE_EXPIRED = "lease_expired"
DETERMINISTIC_ANALYSIS_PREFIXES = ("analysis_exception", "payload_contract", "artifact_integrity",
                                   "envelope_contract", "provenance", "analysis_provenance")
NAMED = 12
_ACTIVE_JOB = "EXISTS (SELECT 1 FROM campaigns c WHERE c.campaign_id=j.campaign_id AND c.status='active')"
_ACTIVE_ANALYSIS = "EXISTS (SELECT 1 FROM campaigns c WHERE c.campaign_id=q.campaign_id AND c.status='active')"
_UNSUPERSEDED = ("NOT EXISTS (SELECT 1 FROM analysis_queue b WHERE b.campaign_id=q.campaign_id "
                 "AND b.candidate_id=q.candidate_id AND b.analysis_version=q.analysis_version AND b.n=q.n "
                 "AND b.seed=q.seed AND b.status='done')")


def the_fleets(classes: list[str]) -> bool:
    return all(c in INTERRUPTED_ATTEMPT_CLASSES or c in STORAGE_ATTEMPT_CLASSES for c in classes)


def seed_is_the_fleets(status: str, error: str | None, classes: list[str]) -> bool:
    text = str(error or "")
    if REFUSED_TEXT in text or NO_SPACE_STOP_TEXT in text or not classes:
        return False
    if status == "lost":
        return same_reason_exhausted(classes) is None
    if status != "failed":
        return False
    return the_fleets(classes) or (COUNTED_STOP_TEXT in text and same_reason_exhausted(classes) is None)


def analysis_is_the_fleets(error_class: str | None) -> bool:
    cls = str(error_class or "")
    if cls.startswith(DETERMINISTIC_ANALYSIS_PREFIXES):
        return False
    return (cls in INTERRUPTED_ATTEMPT_CLASSES or cls == ANALYSIS_LEASE_EXPIRED
            or any(marker in cls for marker in STORAGE_ANALYSIS_MARKERS))


def _own(seed: dict) -> list[str]:
    own = [c for c in seed["classes"] if c not in INTERRUPTED_ATTEMPT_CLASSES]
    if own:
        return own
    text = str(seed.get("error") or "")
    if NO_SPACE_STOP_TEXT in text:
        return ["its output does not fit the RAM scratch"]
    return ["memory refused for good"] if REFUSED_TEXT in text else ["unrecorded"]


def _failed_seeds(repo) -> dict[tuple[str, str], list[dict]]:
    jobs = {str(r["job_id"]): dict(r) | {"classes": []} for r in repo.conn.execute(
        "SELECT j.job_id,j.campaign_id,j.candidate_id,j.n,j.seed,j.status,j.error FROM jobs j "
        f"WHERE j.kind='simulate' AND j.status IN ('failed','lost') AND {_ACTIVE_JOB}").fetchall()}
    if jobs:
        for row in repo.conn.execute(
                "SELECT a.job_id,a.error_class FROM attempts a JOIN jobs j ON j.job_id=a.job_id WHERE j.kind='simulate' "
                f"AND j.status IN ('failed','lost') AND {_ACTIVE_JOB} AND a.finished_utc IS NOT NULL "
                "AND a.error IS NOT NULL ORDER BY a.job_id,a.started_utc,a.number").fetchall():
            if str(row["job_id"]) in jobs:
                jobs[str(row["job_id"])]["classes"].append(str(row["error_class"] or "unknown"))
    by_law: dict[tuple[str, str], list[dict]] = {}
    for job in jobs.values():
        job["fleets"] = seed_is_the_fleets(str(job["status"]), job["error"], job["classes"])
        by_law.setdefault((str(job["campaign_id"]), str(job["candidate_id"])), []).append(job)
    return by_law


def _failed_analyses(repo) -> dict[tuple[str, str], list[dict]]:
    contracts: dict[str, str] = {}
    by_law: dict[tuple[str, str], list[dict]] = {}
    events = M.given_back_events(repo)
    for row in repo.conn.execute(
            "SELECT q.campaign_id,q.input_artifact,q.analysis_version,q.candidate_id,q.n,q.seed,q.error_class,q.error,"
            "q.producer_job "
            f"FROM analysis_queue q WHERE q.status='failed' AND {_ACTIVE_ANALYSIS} AND {_UNSUPERSEDED}").fetchall():
        campaign_id = str(row["campaign_id"])
        if campaign_id not in contracts:
            contracts[campaign_id] = str(repo.campaign_analysis_contract(campaign_id))
        if str(row["analysis_version"]) != contracts[campaign_id]:
            continue
        item = dict(row)
        if str(item.get("error") or "").startswith(M.RAW_LOST_TEXT):
            continue
        kind = M.KIND_REPLAYED if M.is_replay_due(repo, item, events) else M.kind_of(item, events)
        if kind is None and M.is_rescue_due(repo, row["error_class"], campaign_id, row["input_artifact"], events):
            kind = M.KIND_RESCUE
        item |= {"fleets": analysis_is_the_fleets(row["error_class"]) or kind is not None, "giveback": kind}
        by_law.setdefault((str(row["campaign_id"]), str(row["candidate_id"])), []).append(item)
    return by_law


def _given_back_before(repo) -> set[tuple[str, str, str, str]]:
    return S.given_back(repo, (FAILURE_REPAIR_CONTRACT, RESCUE_CONTRACT, REPLAY_CONTRACT))


def _contract(entry: dict) -> str:
    kinds = {a.get("giveback") for a in entry.get("analyses") or []}
    if M.KIND_REPLAYED in kinds:
        return REPLAY_CONTRACT
    return RESCUE_CONTRACT if M.KIND_RESCUE in kinds else FAILURE_REPAIR_CONTRACT


def _laws(repo) -> dict:
    seeds, analyses = _failed_seeds(repo), _failed_analyses(repo)
    before = _given_back_before(repo) if (seeds or analyses) else set()
    out: dict[str, list] = {"running": [], "reinstate": [], "again": [], "left": []}
    for key in sorted(set(seeds) | set(analyses)):
        campaign_id, law = key
        work_seeds, work_analyses = seeds.get(key, []), analyses.get(key, [])
        row = repo.conn.execute(
            "SELECT c.state,d.rule,d.at_n,d.reason,d.decision_id,d.created_utc FROM campaign_candidates c LEFT JOIN "
            "engine_decisions_latest d ON d.campaign_id=c.campaign_id AND d.candidate_id=c.candidate_id "
            "WHERE c.campaign_id=? AND c.candidate_id=?", (campaign_id, law)).fetchone()
        mine = [s for s in work_seeds if s["fleets"]]
        theirs = [a for a in work_analyses if a["fleets"]]
        own = sorted({c for s in work_seeds if not s["fleets"] for c in _own(s)}
                     | {str(a["error_class"] or "unknown") for a in work_analyses if not a["fleets"]})
        entry = {"campaign_id": campaign_id, "candidate_id": law, "jobs": mine, "analyses": theirs, "own": own,
                 "state": None if row is None else row["state"],
                 "stop": None if row is None else {"rule": row["rule"], "at_n": row["at_n"], "reason": row["reason"],
                                                    "decision_id": row["decision_id"], "utc": row["created_utc"]}}
        if row is None:
            out["left"].append(entry)
        elif row["state"] != CandidateState.STOPPED.value:
            if row["state"] not in TERMINAL_CANDIDATE_STATES and (mine or theirs):
                out["running"].append(entry)
        elif row["rule"] != "failed":
            continue
        elif own or not (mine or theirs):
            out["left"].append(entry)
        elif (campaign_id, law, S.rung(row["at_n"]), _contract(entry)) in before:
            out["again"].append(entry)
        else:
            out["reinstate"].append(entry)
    return out


def survey(repo) -> dict:
    laws = _laws(repo)
    return {"contract": FAILURE_REPAIR_CONTRACT, **{k: [_name(e) for e in v] for k, v in laws.items()}}


_UNCLASSED_FENCE = ("error_class IS NULL AND error IS NOT NULL AND exit_code=-15 AND finished_utc IS NOT NULL")


def reclassify_pause_fences(repo) -> int:
    from graph_scale_dynamics.db.repo import FENCE_PAUSED_CLASS
    return int(repo.conn.execute(f"UPDATE attempts SET error_class='{FENCE_PAUSED_CLASS}' WHERE {_UNCLASSED_FENCE}"
                                 ).rowcount or 0)


def repair(repo) -> dict:
    repo.begin_transaction(attempts=12)
    try:
        pauses_named = reclassify_pause_fences(repo)
        laws = _laws(repo)
        requeued_jobs = requeued_analyses = given_back = 0
        for entry in laws["running"]:
            requeued_jobs += S._requeue_jobs(repo, [str(j["job_id"]) for j in entry["jobs"]])
            requeued_analyses += S._requeue_analyses(repo, entry["analyses"])
            given_back += M.mark_given_back(repo, entry["analyses"])
        reinstated = []
        for entry in laws["reinstate"]:
            contract = _contract(entry)
            done = S._reinstate(repo, entry, contract=contract,
                                why=("for failures the fleet made (interruptions, workers that died, the storage), "
                                     "none the law's own") if contract == FAILURE_REPAIR_CONTRACT else
                                ("its analysis given back once more with the deepest ceiling (621: a give-back that "
                                 "lost its room), none of its failures the law's own yet")
                                if contract == RESCUE_CONTRACT else
                                ("its give-back never reached the replay that failed (625: the raw output lost, the "
                                 "job run again under another artifact), none of its failures the law's own yet"))
            requeued_jobs += done["jobs"]
            requeued_analyses += done["analyses"]
            given_back += M.mark_given_back(repo, entry["analyses"])
            reinstated.append(_name(entry))
        repo.conn.execute("COMMIT")
    except Exception:
        repo.conn.rollback_if_open()
        raise
    return {"contract": FAILURE_REPAIR_CONTRACT, "pauses_named": pauses_named, "jobs_requeued": requeued_jobs,
            "analyses_requeued": requeued_analyses, "memory_given_back": given_back, "laws_reinstated": reinstated,
            "laws_again": [_name(e) for e in laws["again"]],
            "laws_left": [_name(e) for e in laws["left"] if (e.get("stop") or {}).get("rule") == "failed"]}


def _name(entry: dict) -> dict:
    stop = entry.get("stop") or {}
    return {"campaign_id": entry["campaign_id"], "law": str(entry["candidate_id"])[:10], "at_n": stop.get("at_n"),
            "own": list(entry.get("own") or [])}


def _named(laws: list[dict]) -> str:
    shown = ", ".join(f"{e['law']} (campaign {e['campaign_id']}, N={e['at_n']})" for e in laws[:NAMED])
    return shown + (f" and {len(laws) - NAMED} more" if len(laws) > NAMED else "")


def render(result: dict) -> list[str]:
    lines = []
    if result.get("pauses_named"):
        lines.append(f"repair: {result['pauses_named']:,} attempt(s) a pause closed with no class named an interruption "
                     "(they had read as the job's own unknown failures)")
    if result.get("jobs_requeued") or result.get("analyses_requeued"):
        lines.append(f"repair: queued again {result['jobs_requeued']:,} seed(s) and {result['analyses_requeued']:,} "
                     "analysis(es) that failed for the fleet (interruptions, workers that died, the storage)")
    if result.get("memory_given_back"):
        lines.append(f"repair: {result['memory_given_back']:,} analysis(es) stopped at the memory ceiling given back "
                     "once, with the deepest rung's ceiling")
    if result.get("laws_reinstated"):
        lines.append(f"repair: {len(result['laws_reinstated'])} law(s) stopped `failed` for those alone are running "
                     f"again: {_named(result['laws_reinstated'])}")
    if result.get("laws_again"):
        lines.append(f"repair: {len(result['laws_again'])} law(s) failed again where they were given back and stay "
                     f"stopped: {_named(result['laws_again'])}")
    left = result.get("laws_left") or []
    if left:
        counts: dict[str, int] = {}
        for entry in left:
            for cls in entry["own"] or ["unknown"]:
                counts[cls] = counts.get(cls, 0) + 1
        by = ", ".join(f"{cls} {n}" for cls, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"repair: {len(left)} law(s) stay stopped `failed` for failures of their own ({by}): "
                     f"{_named(left)}")
    return lines
