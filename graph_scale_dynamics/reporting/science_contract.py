from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONTRACT = "gsd-science-contract-2"
TABLE_SCIENCE = ("analysis_version", "estimator_fingerprint", "cells")
TABLE_IN_BUNDLE = "calibration/probe_calibration.json"


def parts(root: Path | None = None) -> tuple[dict, bytes | None]:
    from graph_scale_dynamics.calibration import durable_artifact_path
    from graph_scale_dynamics.calibration import fingerprint as F
    from graph_scale_dynamics.calibration import start_reading as S
    from graph_scale_dynamics.observability import catalogue, law_score
    from graph_scale_dynamics.services.worker.engine_registry import rust_source_version
    table = Path(durable_artifact_path(root))
    raw = table.read_bytes() if table.is_file() else None
    found = {"analysis_version": F.analysis_version(), "estimator_fingerprint": F.estimator_fingerprint(),
             "starts_fingerprint": S.fingerprint(), "score": law_score.CONTRACT, "catalogue": catalogue.CONTRACT,
             "engine": rust_source_version(), "calibration_cells_sha256": cells_sha256(raw)}
    return found, raw


def cells_sha256(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    try:
        table = json.loads(raw)
    except ValueError:
        table = None
    if not isinstance(table, dict):
        return hashlib.sha256(raw).hexdigest()
    kept = {key: table.get(key) for key in TABLE_SCIENCE}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def science(root: Path | None = None) -> tuple[dict, bytes | None]:
    found, raw = parts(root)
    digest = hashlib.sha256(json.dumps(found, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"contract": CONTRACT, **found, "sha256": digest,
            "calibration_table_sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
            "table": TABLE_IN_BUNDLE if raw is not None else None,
            "reading": ("two bundles whose sha256 is the same were read by the same probes, starts' reading, score, "
                        "catalogue and engine, on the same calibration table's cells, which the bundle carries (the "
                        "file's own sha256 beside it, its adoption times not in the hash: since 861); a different "
                        "sha256 says which of these differs")}, raw


def same(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    keys = sorted(k for k in set(a) | set(b)
                  if k not in ("contract", "sha256", "table", "reading", "calibration_table_sha256"))
    return {"same": bool(a.get("sha256")) and a.get("sha256") == b.get("sha256"),
            "differ": [k for k in keys if a.get(k) != b.get(k)]}
