from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONTRACT = "gsd-science-contract-1"
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
             "engine": rust_source_version(),
             "calibration_table_sha256": None if raw is None else hashlib.sha256(raw).hexdigest()}
    return found, raw


def science(root: Path | None = None) -> tuple[dict, bytes | None]:
    found, raw = parts(root)
    digest = hashlib.sha256(json.dumps(found, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"contract": CONTRACT, **found, "sha256": digest,
            "table": TABLE_IN_BUNDLE if raw is not None else None,
            "reading": ("two bundles whose sha256 is the same were read by the same probes, starts' reading, score, "
                        "catalogue and engine, on the same calibration table, which the bundle carries; a different "
                        "sha256 says which of these differs")}, raw


def same(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    keys = sorted(k for k in set(a) | set(b) if k not in ("contract", "sha256", "table", "reading"))
    return {"same": bool(a.get("sha256")) and a.get("sha256") == b.get("sha256"),
            "differ": [k for k in keys if a.get(k) != b.get(k)]}
