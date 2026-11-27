from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class CandidateState(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    REJECTED_STATIC = "REJECTED_STATIC"
    PILOT_QUEUED = "PILOT_QUEUED"
    PILOT_RUNNING = "PILOT_RUNNING"
    BASE_BLOCK_RUNNING = "BASE_BLOCK_RUNNING"
    EXTENDING = "EXTENDING"
    HELD = "HELD"
    STOPPED = "STOPPED"
    DONE = "DONE"
    REJECTED_HEALTH = "REJECTED_HEALTH"
    DISCOVERY_ACTIVE = "DISCOVERY_ACTIVE"
    PARKED = "PARKED"
    REJECTED_SCALING = "REJECTED_SCALING"
    ROBUSTNESS_ACTIVE = "ROBUSTNESS_ACTIVE"
    QUARANTINE = "QUARANTINE"


RUNNING_CANDIDATE_STATES = frozenset({
    CandidateState.BASE_BLOCK_RUNNING.value,
    CandidateState.EXTENDING.value,
    CandidateState.HELD.value,
    CandidateState.DISCOVERY_ACTIVE.value,
    CandidateState.PILOT_RUNNING.value,
})
ENGINE_RUNNING_STATES = frozenset({
    CandidateState.BASE_BLOCK_RUNNING.value,
    CandidateState.EXTENDING.value,
    CandidateState.HELD.value,
})


ATTEMPT_CLASS_MEMORY_FLOOR = "preempted_memory_floor"
ATTEMPT_CLASS_MEMORY_RUNAWAY = "memory_runaway_requeued"
LANE_YIELD_REASON = "gave its lane to a law bought on its own reading"
ATTEMPT_CLASS_LANE_YIELD = "preempted_lane_yield"
MODE_YIELD_REASON = "gave its slot to the mode the fleet is in"
ATTEMPT_CLASS_MODE_YIELD = "preempted_fleet_mode"
ATTEMPT_CLASS_CAMPAIGN_PAUSED = "preempted_campaign_paused"
ATTEMPT_CLASS_NO_SPACE = "no_space_left"
ATTEMPT_CLASS_WORKER_CAP = "preempted_worker_cap"
ATTEMPT_CLASS_LEASE_LOST = "lease_generation_lost"
ATTEMPT_CLASS_WORKER_VANISHED = "worker_vanished"
INTERRUPTED_ATTEMPT_CLASSES = ("preempted_fleet_paused", "preempted_fleet_shutdown", "supervisor_interrupted",
                               ATTEMPT_CLASS_MEMORY_FLOOR, ATTEMPT_CLASS_MEMORY_RUNAWAY, ATTEMPT_CLASS_LANE_YIELD, ATTEMPT_CLASS_CAMPAIGN_PAUSED,
                               ATTEMPT_CLASS_NO_SPACE, ATTEMPT_CLASS_WORKER_CAP, ATTEMPT_CLASS_LEASE_LOST,
                               ATTEMPT_CLASS_WORKER_VANISHED, ATTEMPT_CLASS_MODE_YIELD)
VANISHED_FIRST_WAIT_SECONDS = 60.0
VANISHED_LONGEST_WAIT_SECONDS = 3600.0


def vanished_wait_seconds(times: int) -> float:
    return min(VANISHED_LONGEST_WAIT_SECONDS, VANISHED_FIRST_WAIT_SECONDS * 2 ** max(0, int(times) - 1))
STORAGE_ATTEMPT_CLASSES = ("no_result", "exception:OSError", "corrupt_receipt")


def interrupted_sql(alias: str = "a") -> str:
    names = ",".join(f"'{name}'" for name in INTERRUPTED_ATTEMPT_CLASSES)
    return f"COALESCE({alias}.error_class,'') IN ({names})"


TERMINAL_CANDIDATE_STATES = frozenset({
    CandidateState.REJECTED_STATIC.value,
    CandidateState.REJECTED_HEALTH.value,
    CandidateState.REJECTED_SCALING.value,
    CandidateState.PARKED.value,
    CandidateState.QUARANTINE.value,
    CandidateState.STOPPED.value,
    CandidateState.DONE.value,
})


class JobKind(str, Enum):
    SIMULATE = "simulate"
    ANALYZE = "analyze"


POLICY_RULE_VERSION = "policy-contract-19"

EVIDENCE_SUMMARY_CONTRACT = "rung-summary-3"


ENSEMBLE_CODE_PREFIX = "G"


def ensemble_code(ordinals_by_n: dict) -> str | None:
    ordinals = {}
    for key, value in (ordinals_by_n or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            ordinals[int(key)] = int(value)
    if not ordinals:
        return None

    return f"{ENSEMBLE_CODE_PREFIX}-{min(ordinals.values())}"


def candidate_id(candidate_spec: dict) -> str:
    return content_hash({"kind": "candidate", "spec": candidate_spec})


def job_id(campaign: str, candidate: str, kind: str, stage: str, n: int, seed: int,
           replicate: int, engine_version: str) -> str:
    return content_hash({"kind": "job", "campaign": campaign, "candidate": candidate,
                         "job_kind": kind, "stage": stage, "n": int(n), "seed": int(seed),
                         "replicate": int(replicate), "engine_version": engine_version})


def analysis_id(input_artifact: str, analysis_version: str, params: dict) -> str:
    return content_hash({"kind": "analysis", "input": input_artifact,
                         "version": analysis_version, "params": params})


def decision_id(rule_version: str, snapshot: dict) -> str:
    return content_hash({"kind": "decision", "rule_version": rule_version, "snapshot": snapshot})


def candidate_numbers(repo, campaign_id: str) -> dict:
    return {
        str(row["candidate_id"]): int(row["candidate_number"])
        for row in repo.conn.execute(
            "SELECT candidate_id,candidate_number FROM campaign_candidates "
            "WHERE campaign_id=? AND candidate_number IS NOT NULL",
            (str(campaign_id),),
        )
    }


def candidate_number_for(repo, campaign_id: str, candidate_id: str) -> int | None:
    row = repo.conn.execute(
        "SELECT candidate_number FROM campaign_candidates "
        "WHERE campaign_id=? AND candidate_id=?",
        (str(campaign_id), str(candidate_id)),
    ).fetchone()
    if row is None or row["candidate_number"] is None:
        return None
    return int(row["candidate_number"])
