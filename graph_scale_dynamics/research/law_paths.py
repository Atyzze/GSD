from __future__ import annotations

import math
from pathlib import Path

from graph_scale_dynamics.research.refused_rungs import masked

PATH_FIELDS = ("d_s", "d_V", "d_B", "d_w", "k")


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def law_paths(source: Path, *, ids: bool = False, refused_too: bool = False) -> list:
    import ijson
    path = Path(source)
    if path.is_dir():
        path = path / "reports" / "05.json"
    if not path.is_file():
        return []
    out = []
    with open(path, "rb") as handle:
        for specimen in ijson.items(handle, "body.specimens.item", use_float=True):
            law = str((specimen or {}).get("candidate_id") or "")
            ph = (specimen or {}).get("phenotype") or {}
            per_n = ph.get("per_n") or {}
            base = ph.get("base_sizes") or []
            rows = []
            for sizes, vectors, buckets, degrees in (
                    (base, ph.get("probe_vectors") or {}, ph.get("probe_bucket_vectors") or {},
                     [(per_n.get(str(n)) or {}).get("mean_degree") for n in base]),
                    (ph.get("extension_sizes") or [], ph.get("extension_probe_vectors") or {},
                     ph.get("extension_probe_bucket_vectors") or {}, list(ph.get("extension_mean_degree_vector") or []))):
                columns = [list(vectors.get(probe) or []) if refused_too else
                           masked(vectors.get(probe) or [], buckets.get(probe)) for probe in PATH_FIELDS[:4]] + [degrees]
                for i, n in enumerate(sizes):
                    values = tuple(_num(column[i]) if i < len(column) else None for column in columns)
                    if any(v is not None for v in values[:4]):
                        rows.append((int(n), *values))
            if rows:
                out.append((law, sorted(rows)) if ids else sorted(rows))
    return out
