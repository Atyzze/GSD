from __future__ import annotations

import os
import re

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.domain.cadence import ticks
from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES, TERMINAL_CANDIDATE_STATES


TERMINAL_STATES = tuple(sorted(TERMINAL_CANDIDATE_STATES))
FENCE_PAUSED_CLASS = "preempted_fleet_paused"
assert FENCE_PAUSED_CLASS in INTERRUPTED_ATTEMPT_CLASSES
FENCE_OUTRANKS = frozenset(INTERRUPTED_ATTEMPT_CLASSES) | {
    "unknown", "signal:SIGTERM", "signal:SIGKILL", "signal:SIGINT", "signal:SIGHUP"}

def runnable_candidate_sql(state_col: str) -> str:
    marks = ",".join("?" for _ in TERMINAL_STATES)
    return f"{state_col} NOT IN ({marks})"


def analysis_runnable_candidate_sql(state_col: str) -> str:
    return runnable_candidate_sql(state_col)


def candidate_may_run_job(state: str) -> bool:
    return state not in TERMINAL_CANDIDATE_STATES

_DETERMINISTIC_ANALYSIS_FAILURE_SQL = (
    "(COALESCE(analysis_queue.error_class,'') LIKE 'analysis_exception%' "
    "OR COALESCE(analysis_queue.error_class,'') LIKE 'payload_contract%' "
    "OR COALESCE(analysis_queue.error_class,'') LIKE 'artifact_integrity%' "
    "OR COALESCE(analysis_queue.error_class,'') LIKE 'envelope_contract%' "
    "OR COALESCE(analysis_queue.error_class,'') LIKE 'provenance%' "
    "OR COALESCE(analysis_queue.error_class,'') LIKE 'analysis_provenance%')"
)

def retryable_db_error(exc: BaseException) -> bool:
    return isinstance(exc, DatabaseOperationalError) and bool(exc.transient)


CAMPAIGN_LINK_PURPOSES = frozenset({
    "confirmation", "audit", "robustness", "frontier_probe",
})
CAMPAIGN_LINK_CHANNELS = frozenset({
    "merit", "uncertainty", "audit", "manual", "top-down",
})


def _validated_search_seed(value: int) -> int:
    seed = int(value)
    if seed < 0 or seed >= 2**63:
        raise ValueError("search_seed must be in [0, 2^63)")
    return seed


def _validated_persisted_seed(value: int) -> int:
    seed = int(value)
    if seed < 0 or seed >= 2**31:
        raise ValueError("persisted job seed must be in [0, 2^31)")
    return seed


_ROLE_SUFFIX = re.compile(r"(-\d+)+$")


def _service_role(service: str) -> str:
    return _ROLE_SUFFIX.sub("", str(service)) or str(service)


def analyzer_identity() -> str:
    from graph_scale_dynamics.domain.science_identity import science_fingerprint
    from graph_scale_dynamics.domain.version import runtime_fingerprint
    identity = science_fingerprint()
    return runtime_fingerprint() if identity == "unavailable" else f"science:{identity}"


ATTEMPT_CLASS_MEMORY_HARD_STOP = "memory_hard_stop"
ATTEMPT_CLASS_FLEET_SHUTDOWN = "preempted_fleet_shutdown"
ATTEMPT_CLASS_FLEET_PAUSED = "preempted_fleet_paused"
ATTEMPT_CLASS_LEASE_LOST = "lease_generation_lost"
ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED = "supervisor_interrupted"


def _probe_seconds_columns(metrics: dict) -> tuple:
    blocks = [(metrics or {}).get("probe_seconds")]
    from graph_scale_dynamics.domain.chain_list import chain_probes
    blocks.extend((given or {}).get("probe_seconds") for given in chain_probes(metrics).values()
                  if isinstance(given, dict))

    def value(key):
        found = [float(block[key]) for block in blocks
                 if isinstance(block, dict) and isinstance(block.get(key), (int, float))
                 and not isinstance(block.get(key), bool)]
        return sum(found) if found else None

    return (value("d_s"), value("d_V"), value("d_B"), value("d_w"))


def heartbeat_interval_seconds() -> float:
    return max(ticks(1), float(os.environ.get("GSD_HEARTBEAT_INTERVAL_SECONDS", str(ticks(8)))))
