from __future__ import annotations

from array import array
from collections import Counter
import math
import re

import numpy as np

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.envelope import RAW_ENVELOPE_SCHEMA
from graph_scale_dynamics.artifact_store.retention import compact_payload
from graph_scale_dynamics.domain import chain_list as CL


_HEX64 = re.compile(r"[0-9a-f]{64}")


class StreamingEnvelopeError(ValueError):
    pass


def _validate_core(values: dict[str, object], *, edge_counts: dict[str, int],
                   expected_n: int | None, expected_seed: int | None,
                   expected_job_id: str | None, expected_candidate_id: str | None) -> None:
    if values.get("schema") != RAW_ENVELOPE_SCHEMA:
        raise StreamingEnvelopeError("unsupported raw envelope schema")
    n = values.get("n")
    seed = values.get("seed")
    sweeps = values.get("sweeps")
    moves = values.get("moves")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise StreamingEnvelopeError("n must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise StreamingEnvelopeError("seed must be an integer")
    if not isinstance(sweeps, int) or isinstance(sweeps, bool) or sweeps <= 0:
        raise StreamingEnvelopeError("sweeps must be a positive integer")
    if not isinstance(moves, int) or moves != sweeps * n:
        raise StreamingEnvelopeError("moves must equal sweeps * n")
    multiplier = values.get("sweeps_multiplier", 1)
    if not isinstance(multiplier, int) or isinstance(multiplier, bool) or multiplier < 1:
        raise StreamingEnvelopeError("sweeps_multiplier must be a positive integer")
    declared = values.get("declared_sweeps")
    if declared is not None:
        if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
            raise StreamingEnvelopeError("declared_sweeps must be a positive integer")
        if sweeps != declared * multiplier:
            raise StreamingEnvelopeError("executed sweeps do not match declared_sweeps * multiplier")
    if expected_n is not None and n != int(expected_n):
        raise StreamingEnvelopeError("envelope n does not match the producing job")
    if expected_seed is not None and seed != int(expected_seed):
        raise StreamingEnvelopeError("envelope seed does not match the producing job")
    if expected_job_id is not None and values.get("job_id") != expected_job_id:
        raise StreamingEnvelopeError("envelope job_id does not match the producing job")
    candidate_id = values.get("candidate_id")
    if not isinstance(candidate_id, str) or len(candidate_id) != 64:
        raise StreamingEnvelopeError("candidate_id must be a SHA-256 identity")
    if values.get("candidate_fingerprint") != candidate_id:
        raise StreamingEnvelopeError("candidate_fingerprint must equal candidate_id")
    if expected_candidate_id is not None and candidate_id != expected_candidate_id:
        raise StreamingEnvelopeError("envelope candidate_id does not match the producing job")
    spec_hash = values.get("execution_spec_hash")
    if spec_hash is not None and (not isinstance(spec_hash, str) or not _HEX64.fullmatch(spec_hash)):
        raise StreamingEnvelopeError("execution_spec_hash must be a lowercase SHA-256 digest")
    records = values.get("chains")
    if not isinstance(records, list) or not records or (records[0] or {}).get("start") != CL.FROM_EMPTY:
        raise StreamingEnvelopeError("chains must list the chain from empty first")
    for record in records:
        name = record.get("start")
        if not isinstance(record.get("acceptance"), dict):
            raise StreamingEnvelopeError(f"the {name} chain's acceptance must be an object")
        if record.get("skipped"):
            continue
        final = record.get("final")
        if not isinstance(final, dict):
            raise StreamingEnvelopeError(f"the {name} chain's final must be an object")
        if name not in edge_counts or final.get("edge_count") != edge_counts[name]:
            raise StreamingEnvelopeError(f"the {name} chain's final.edge_count does not match its edge list")
        mean_degree = final.get("mean_degree")
        expected_mean = 2.0 * edge_counts[name] / n
        if (not isinstance(mean_degree, (int, float)) or isinstance(mean_degree, bool)
                or not math.isfinite(float(mean_degree))
                or not math.isclose(float(mean_degree), expected_mean, rel_tol=1e-10, abs_tol=1e-12)):
            raise StreamingEnvelopeError(f"the {name} chain's final.mean_degree does not match its edge list")
    if not isinstance(values.get("engine_version"), str):
        raise StreamingEnvelopeError("engine_version must be a string")
    provenance = values.get("provenance")
    if not isinstance(provenance, dict):
        raise StreamingEnvelopeError("provenance must be an object")
    build = provenance.get("build_number")
    generation = provenance.get("lease_generation")
    source_fp = provenance.get("source_fingerprint")
    if not isinstance(build, int) or isinstance(build, bool):
        raise StreamingEnvelopeError("provenance.build_number must be an integer")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
        raise StreamingEnvelopeError("provenance.lease_generation must be a positive integer")
    if not isinstance(source_fp, str) or len(source_fp) < 8:
        raise StreamingEnvelopeError("provenance.source_fingerprint must be recorded")


def publish_envelope_artifacts(
    store: BlobStore,
    envelope: dict,
    *,
    expected_n: int | None = None,
    expected_seed: int | None = None,
    expected_job_id: str | None = None,
    expected_candidate_id: str | None = None,
    keep_checkpoint: bool = True,
    compresslevel: int = 1,
) -> dict:
    if not isinstance(envelope, dict):
        raise StreamingEnvelopeError("raw simulation envelope must be an object")
    n = envelope.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise StreamingEnvelopeError("n must be a positive integer")
    code = "I" if n <= 0xFFFFFFFF else "Q"
    histograms, edge_counts = {}, {}
    for block in CL.blocks(envelope):
        name = str(block.get("start"))
        edges = block.get("edge_list")
        if not isinstance(edges, list):
            raise StreamingEnvelopeError(f"the {name} chain's edge_list must be a JSON array")
        degrees = array(code, [0]) * n
        keys = np.empty(len(edges), dtype=np.int64)
        for index, raw_pair in enumerate(edges):
            if (not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2
                    or isinstance(raw_pair[0], bool) or isinstance(raw_pair[1], bool)):
                raise StreamingEnvelopeError("edges must contain integer pairs")
            u, v = int(raw_pair[0]), int(raw_pair[1])
            if not (0 <= u < v < n):
                raise StreamingEnvelopeError(f"invalid canonical edge ({u}, {v}) for n={n}")
            keys[index] = u * n + v
            degrees[u] += 1
            degrees[v] += 1
        if np.unique(keys).size != len(edges):
            raise StreamingEnvelopeError(f"the {name} chain's edge list repeats an edge")
        del keys
        histograms[name] = {str(k): int(v) for k, v in sorted(Counter(degrees).items())}
        edge_counts[name] = len(edges)
    _validate_core(
        envelope, edge_counts=edge_counts, expected_n=expected_n, expected_seed=expected_seed,
        expected_job_id=expected_job_id, expected_candidate_id=expected_candidate_id,
    )
    compact = compact_payload(envelope, histograms)
    compact_digest, compact_size = store.put_json_stream(compact, compresslevel=compresslevel)
    from graph_scale_dynamics.artifact_store.chain_record import XZ_PRESET, encode_record
    record_digest, record_size = store.put_bytes(encode_record(envelope))
    checkpoint_digest = None
    checkpoint_size = 0
    checkpoint_body_state = None
    if keep_checkpoint:
        checkpoint = envelope.get("sampling_checkpoint")
        if not isinstance(checkpoint, dict):
            raise StreamingEnvelopeError("active raw envelope has no sampling_checkpoint")
        checkpoint_payload = {
            "schema": "simulation-resume-checkpoint-v1",
            "source_schema": envelope.get("schema"),
            "job_id": envelope.get("job_id"),
            "candidate_id": envelope.get("candidate_id"),
            "candidate_fingerprint": envelope.get("candidate_fingerprint"),
            "execution_spec_hash": envelope.get("execution_spec_hash"),
            "n": envelope.get("n"),
            "seed": envelope.get("seed"),
            "sweeps_multiplier": envelope.get("sweeps_multiplier", 1),
            "sampling_checkpoint": checkpoint,
        }
        checkpoint_digest, checkpoint_size = store.put_json_stream_transient(
            checkpoint_payload, compresslevel=compresslevel
        )
        checkpoint_body_state = "transient"
    raw_digest, raw_size, raw_uncompressed_size = store.put_json_stream_transient_with_stats(
        envelope, compresslevel=compresslevel
    )
    final = CL.record(envelope, CL.FROM_EMPTY).get("final") or {}
    peak = int(final.get("peak_edge_count", 0) or 0)
    if peak <= 0:
        for row in CL.trajectory(envelope, CL.FROM_EMPTY):
            if isinstance(row, dict):
                peak = max(peak, int(row.get("edges", 0) or 0))
        peak = max(peak, int(final.get("edge_count", 0) or 0))
    return {
        "artifact_manifest_contract": "simulation-artifact-manifest-v1",
        "raw_digest": raw_digest,
        "raw_size": int(raw_size),
        "raw_uncompressed_size": int(raw_uncompressed_size),
        "raw_body_state": "transient",
        "raw_storage_tier": "tmpfs",
        "raw_encoding": f"gzip-{max(1, min(9, int(compresslevel)))}",
        "compact_digest": compact_digest,
        "compact_size": int(compact_size),
        "record_digest": record_digest,
        "record_size": int(record_size),
        "record_encoding": f"xz-{XZ_PRESET}",
        "checkpoint_digest": checkpoint_digest,
        "checkpoint_size": int(checkpoint_size),
        "checkpoint_body_state": checkpoint_body_state,
        "checkpoint_storage_tier": ("tmpfs" if checkpoint_body_state == "transient" else None),
        "checkpoint_encoding": f"gzip-{max(1, min(9, int(compresslevel)))}",
        "final": final,
        "resource_usage": envelope.get("resource_usage") if isinstance(envelope.get("resource_usage"), dict) else {},
        "trajectory_diagnostics": envelope.get("trajectory_diagnostics") if isinstance(envelope.get("trajectory_diagnostics"), dict) else {},
        "peak_edge_count": int(peak),
    }
