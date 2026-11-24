from __future__ import annotations

import hashlib
import json
import lzma

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL

RECORD_CONTRACT = "chain-record-4"
XZ_PRESET = 3
_TERM_FIELDS = ("observable", "energy_component", "coefficient")


def sorted_pairs(edges) -> np.ndarray:
    pairs = np.asarray(list(edges) if not isinstance(edges, np.ndarray) else edges, dtype=np.int64)
    pairs = pairs.reshape(-1, 2) if pairs.size else np.zeros((0, 2), dtype=np.int64)
    pairs = np.sort(pairs, axis=1)
    return pairs[np.lexsort((pairs[:, 1], pairs[:, 0]))]


def graph_digest(edges) -> dict:
    pairs = np.ascontiguousarray(sorted_pairs(edges), dtype="<i8")
    return {"edges": int(len(pairs)), "sha256": hashlib.sha256(pairs.tobytes()).hexdigest()}


def trajectory_columns(points: list) -> dict:
    points = [p for p in points or [] if isinstance(p, dict)]
    keys: list = []
    for point in points:
        for key in point:
            if key not in keys and key != "active_term_components":
                keys.append(key)
    columns = {key: [point.get(key) for point in points] for key in keys}
    terms = []
    first = next((p.get("active_term_components") for p in points if p.get("active_term_components")), None)
    for index, term in enumerate(first or []):
        terms.append({k: term.get(k) for k in ("term_index", "op", "params", "scale")})
        for field in _TERM_FIELDS:
            columns[f"term{index}.{field}"] = [
                ((p.get("active_term_components") or [{}] * (index + 1))[index] or {}).get(field)
                if len(p.get("active_term_components") or []) > index else None
                for p in points]
    return {"points": len(points), "terms": terms, "columns": columns}


def _late_change(late_change, final_edges: int):
    from graph_scale_dynamics.engine.engine import late_edge_overlap
    if not late_change:
        return None
    return {"from_move": int(late_change["from_move"]), "added": len(late_change.get("added") or []),
            "removed": len(late_change.get("removed") or []),
            "overlap": late_edge_overlap(late_change, final_edges)}


def build_record(envelope: dict) -> dict:
    n = int(envelope["n"])
    chains = []
    for row in CL.records(envelope):
        block = CL.block(envelope, row.get("start"))
        chains.append({"start": row.get("start"), "init": row.get("init"), "ran": not row.get("skipped"),
                       "graph": graph_digest(block.get("edge_list") or []),
                       "trajectory": trajectory_columns(block.get("trajectory")), "accounting": row.get("accounting"),
                       "late_change": _late_change(block.get("late_change"), len(block.get("edge_list") or []))})
    return {
        "contract": RECORD_CONTRACT,
        "n": n, "seed": envelope.get("seed"), "job_id": envelope.get("job_id"),
        "candidate_id": envelope.get("candidate_id"),
        "execution_spec_hash": envelope.get("execution_spec_hash"),
        "engine_version": envelope.get("engine_version"),
        "trajectory_structure_stride": envelope.get("trajectory_structure_stride"),
        "chains": chains,
        "sampling_checkpoints": envelope.get("sampling_checkpoints"),
        "descent": envelope.get("descent"),
        "rung_terminal": envelope.get("rung_terminal"),
    }


def encode_record(envelope: dict, *, preset: int = XZ_PRESET) -> bytes:
    document = build_record(envelope)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return lzma.compress(raw, format=lzma.FORMAT_XZ, preset=preset)


def decode_record(blob: bytes) -> dict:
    return json.loads(lzma.decompress(blob).decode("utf-8"))


def read_record(store, digest: str) -> dict:
    return decode_record(store.get_bytes(digest, verify=True))


def chain_names(record: dict) -> list[str]:
    return [str(chain.get("start")) for chain in record.get("chains") or []]
