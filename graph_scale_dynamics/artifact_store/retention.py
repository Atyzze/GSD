from __future__ import annotations

import math
from collections import Counter

from graph_scale_dynamics.domain import chain_list as CL


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


COMPACT_SCHEMA = "compact-simulation-evidence-v2"
COMPACT_SCHEMAS = ("compact-simulation-evidence-v1", COMPACT_SCHEMA)


def degree_histogram(n: int, edges) -> dict[str, int]:
    degrees = [0] * n
    for u, v in edges or []:
        degrees[int(u)] += 1
        degrees[int(v)] += 1
    return {str(k): int(v) for k, v in sorted(Counter(degrees).items())}


def compact_payload(envelope: dict, histograms: dict[str, dict]) -> dict:
    return _finite({
        "schema": COMPACT_SCHEMA,
        "source_schema": envelope.get("schema"),
        "engine_version": envelope.get("engine_version"),
        "producer_engine_version": envelope.get("producer_engine_version"),
        "job_id": envelope.get("job_id"),
        "candidate_id": envelope.get("candidate_id"),
        "candidate_fingerprint": envelope.get("candidate_fingerprint"),
        "execution_spec_hash": envelope.get("execution_spec_hash"),
        "n": int(envelope["n"]),
        "seed": envelope.get("seed"),
        "sweeps": envelope.get("sweeps"),
        "cumulative_sweeps": envelope.get("cumulative_sweeps", envelope.get("sweeps")),
        "sweeps_multiplier": envelope.get("sweeps_multiplier", 1),
        "continued_from_sweeps": envelope.get("continued_from_sweeps", 0),
        "dynamics_declared": envelope.get("dynamics_declared"),
        "proposal_model": envelope.get("proposal_model"),
        "random_streams": envelope.get("random_streams"),
        "chains": [dict(record, degree_histogram=histograms.get(record.get("start"))) for record in
                   CL.records(envelope)],
        "trajectory_diagnostics": envelope.get("trajectory_diagnostics"),
        "provenance": envelope.get("provenance"),
        "execution_provenance": envelope.get("execution_provenance"),
        "wall_seconds": envelope.get("wall_seconds"),
        "discarded_raw_fields": ["sampling_checkpoint"],
    })


def compact_raw_envelope(envelope: dict) -> dict:
    n = int(envelope["n"])
    return compact_payload(envelope, {block.get("start"): degree_histogram(n, block.get("edge_list"))
                                      for block in CL.blocks(envelope)})
