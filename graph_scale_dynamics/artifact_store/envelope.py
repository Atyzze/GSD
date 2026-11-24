from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from graph_scale_dynamics.domain import chain_list as CL

RAW_ENVELOPE_SCHEMA = "raw-simulation-envelope-v2"


class EnvelopeValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EnvelopeValidationError(message)


def _finite_tree(value, path: str = "envelope") -> None:
    if isinstance(value, float):
        _require(math.isfinite(value), f"{path}: non-finite number")
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _finite_tree(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _finite_tree(child, f"{path}[{index}]")


def _validate_edges(edges, n: int, path: str) -> set[tuple[int, int]]:
    _require(isinstance(edges, list), f"{path}: must be a list")
    seen: set[tuple[int, int]] = set()
    for index, edge in enumerate(edges):
        _require(isinstance(edge, (list, tuple)) and len(edge) == 2,
                 f"{path}[{index}]: edge must have two endpoints")
        u, v = edge
        _require(isinstance(u, int) and not isinstance(u, bool),
                 f"{path}[{index}][0]: endpoint must be an integer")
        _require(isinstance(v, int) and not isinstance(v, bool),
                 f"{path}[{index}][1]: endpoint must be an integer")
        _require(0 <= u < v < n,
                 f"{path}[{index}]: expected canonical 0 <= u < v < n")
        pair = (u, v)
        _require(pair not in seen, f"{path}[{index}]: duplicate edge {pair}")
        seen.add(pair)
    return seen


def validate_raw_envelope(envelope: dict, *, expected_n: int | None = None,
                          expected_seed: int | None = None,
                          expected_job_id: str | None = None,
                          expected_candidate_id: str | None = None) -> dict:
    _require(isinstance(envelope, dict), "envelope must be an object")
    _require(envelope.get("schema") == RAW_ENVELOPE_SCHEMA,
             "unsupported raw envelope schema")
    n = envelope.get("n")
    seed = envelope.get("seed")
    sweeps = envelope.get("sweeps")
    moves = envelope.get("moves")
    _require(isinstance(n, int) and not isinstance(n, bool) and n > 0,
             "n must be a positive integer")
    _require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an integer")
    _require(isinstance(sweeps, int) and not isinstance(sweeps, bool) and sweeps > 0,
             "sweeps must be a positive integer")
    _require(isinstance(moves, int) and moves == sweeps * n,
             "moves must equal sweeps * n")
    multiplier = envelope.get("sweeps_multiplier", 1)
    _require(isinstance(multiplier, int) and not isinstance(multiplier, bool) and multiplier >= 1,
             "sweeps_multiplier must be a positive integer")
    declared_sweeps = envelope.get("declared_sweeps")
    if declared_sweeps is not None:
        _require(isinstance(declared_sweeps, int) and not isinstance(declared_sweeps, bool)
                 and declared_sweeps >= 1, "declared_sweeps must be a positive integer")
        _require(sweeps == declared_sweeps * multiplier,
                 "executed sweeps must equal declared_sweeps * sweeps_multiplier")
    execution_spec_hash = envelope.get("execution_spec_hash")
    if execution_spec_hash is not None:
        _require(isinstance(execution_spec_hash, str) and len(execution_spec_hash) == 64
                 and all(c in "0123456789abcdef" for c in execution_spec_hash),
                 "execution_spec_hash must be a lowercase SHA-256 digest")
    if expected_n is not None:
        _require(n == int(expected_n), "envelope n does not match the producing job")
    if expected_seed is not None:
        _require(seed == int(expected_seed), "envelope seed does not match the producing job")
    if expected_job_id is not None:
        _require(envelope.get("job_id") == expected_job_id,
                 "envelope job_id does not match the producing job")
    candidate_id = envelope.get("candidate_id")
    candidate_fingerprint = envelope.get("candidate_fingerprint")
    _require(isinstance(candidate_id, str) and len(candidate_id) == 64,
             "candidate_id must be a SHA-256 identity")
    _require(candidate_fingerprint == candidate_id,
             "candidate_fingerprint must equal candidate_id")
    if expected_candidate_id is not None:
        _require(candidate_id == expected_candidate_id,
                 "envelope candidate_id does not match the producing job")

    records = envelope.get("chains")
    _require(isinstance(records, list) and records, "chains must be a non-empty list")
    blocks = (envelope.get("sampling_checkpoint") or {}).get("chains")
    _require(isinstance(blocks, list), "sampling_checkpoint.chains must be a list")
    names = [record.get("start") if isinstance(record, dict) else None for record in records]
    _require(names[0] == CL.FROM_EMPTY, "the first chain is the chain from empty")
    _require(len(set(names)) == len(names) and all(isinstance(name, str) and name for name in names),
             "every chain is named by its start, once")
    by_name = {block.get("start"): block for block in blocks if isinstance(block, dict)}
    _require(set(by_name) <= set(names), "a checkpoint block names a chain the envelope does not list")
    for index, record in enumerate(records):
        path = f"chains[{index}]"
        _require(isinstance(record.get("acceptance"), dict), f"{path}.acceptance must be an object")
        block = by_name.get(record["start"])
        if block is None:
            _require(bool(record.get("skipped")), f"{path} ran and has no checkpoint block")
            continue
        edges = _validate_edges(block.get("edge_list"), n, f"{path}.edge_list")
        _require(isinstance(block.get("trajectory"), list), f"{path}.trajectory must be a list")
        final = record.get("final") if not record.get("skipped") else block.get("final")
        _require(isinstance(final, dict), f"{path}.final must be an object")
        _require(final.get("edge_count") == len(edges), f"{path}.final.edge_count does not match the edge list")
        expected_mean_degree = 2.0 * len(edges) / n
        mean_degree = final.get("mean_degree")
        _require(isinstance(mean_degree, (int, float)) and not isinstance(mean_degree, bool)
                 and math.isfinite(float(mean_degree))
                 and math.isclose(float(mean_degree), expected_mean_degree, rel_tol=1e-10, abs_tol=1e-12),
                 f"{path}.final.mean_degree does not match the edge list")
        late = block.get("late_change")
        if late is not None:
            _require(isinstance(late, dict) and isinstance(late.get("from_move"), int),
                     f"{path}.late_change must be an object with its from_move")
            added = _validate_edges(late.get("added"), n, f"{path}.late_change.added")
            removed = _validate_edges(late.get("removed"), n, f"{path}.late_change.removed")
            _require(not (added & removed), f"{path}.late_change adds and removes one edge")
            _require(added <= edges, f"{path}.late_change adds an edge the chain does not end with")
            _require(not (removed & edges), f"{path}.late_change removes an edge the chain ends with")
        del edges

    _require(isinstance(envelope.get("engine_version"), str), "engine_version must be a string")
    provenance = envelope.get("provenance")
    _require(isinstance(provenance, dict), "provenance must be an object")
    _require(isinstance(provenance.get("build_number"), int)
             and not isinstance(provenance.get("build_number"), bool),
             "provenance.build_number must be an integer")
    _require(isinstance(provenance.get("lease_generation"), int)
             and not isinstance(provenance.get("lease_generation"), bool)
             and provenance.get("lease_generation") > 0,
             "provenance.lease_generation must be a positive integer")
    _require(isinstance(provenance.get("source_fingerprint"), str)
             and len(provenance.get("source_fingerprint")) >= 8,
             "provenance.source_fingerprint must be a recorded fingerprint")
    if "environment_fingerprint" in provenance:
        _require(isinstance(provenance.get("environment_fingerprint"), str)
                 and len(provenance.get("environment_fingerprint")) >= 8,
                 "provenance.environment_fingerprint must be a recorded fingerprint")
    if "environment" in provenance:
        _require(isinstance(provenance.get("environment"), dict),
                 "provenance.environment must be an object")
    _finite_tree(envelope)
    return envelope


def classify_raw_envelope_provenance(envelope: dict, *, expected_candidate_id: str,
                                     expected_lease_generation: int | None = None) -> dict:
    candidate_id = envelope.get("candidate_id")
    candidate_fingerprint = envelope.get("candidate_fingerprint")
    provenance = envelope.get("provenance")
    if candidate_id != expected_candidate_id or candidate_fingerprint != expected_candidate_id:
        return {
            "status": "integrity-failed",
            "identity_verified": False,
            "fenced_publication_verified": False,
            "detail": "executed candidate identity does not match the producing job",
        }
    generation = provenance.get("lease_generation") if isinstance(provenance, dict) else None
    if expected_lease_generation is not None and generation != int(expected_lease_generation):
        return {
            "status": "integrity-failed",
            "identity_verified": True,
            "fenced_publication_verified": False,
            "detail": "envelope lease generation does not match the producing claim",
        }
    source_execution_verified = bool(provenance.get("source_execution_verified"))
    return {
        "status": "verified",
        "identity_verified": True,
        "fenced_publication_verified": True,
        "source_execution_verified": source_execution_verified,
        "source_verification_contract": provenance.get("source_verification_contract"),
        "build_number": provenance["build_number"],
        "source_fingerprint": provenance["source_fingerprint"],
        "environment_fingerprint": provenance.get("environment_fingerprint"),
        "environment": provenance.get("environment"),
        "lease_generation": generation,
        "detail": (
            "digest, executed candidate identity, child-verified source/environment provenance, "
            "and fenced lease generation verified"
            if source_execution_verified else
            "digest, executed candidate identity, recorded build/environment provenance, "
            "and fenced lease generation verified; producer source execution was not independently verified"
        ),
    }
