from __future__ import annotations

import json
from pathlib import Path

REPORT_ROOT: Path | None = None


def delete(base: Path, filename: str) -> dict:
    from graph_scale_dynamics.reporting.study_bundle import INDEX_NAME, _atomic_write, bundles_dir, read_index
    folder = bundles_dir(base)
    index = read_index(base)
    entries = index.get("bundles") or []
    entry = next((b for b in entries if b.get("filename") == filename), None)
    if entry is None or Path(filename).name != filename:
        raise KeyError(filename)
    freed = 0
    for name in (entry.get("filename"), entry.get("svg"), entry.get("maps"), entry.get("explorer"), entry.get("gates"),
                 entry.get("front"), entry.get("advice")):
        target = folder / str(name or "")
        if name and target.parent == folder and target.is_file():
            freed += target.stat().st_size
            target.unlink()
    index["bundles"] = [b for b in entries if b.get("filename") != filename]
    _atomic_write(folder / INDEX_NAME, json.dumps(index, indent=1, sort_keys=True).encode("utf-8"))
    return {"deleted": filename, "freed_bytes": freed, "left": len(index["bundles"])}


def post(handler, parts: list[str], max_bytes: int) -> None:
    from graph_scale_dynamics.operations.report_home import base_of
    if parts[2:] != ["delete"]:
        return handler._json({"error": "use POST /api/study-bundles/delete"}, 404)
    if REPORT_ROOT is None:
        return handler._json({"error": "this runtime has no report root, so no study bundles"}, 404)
    try:
        length = int(handler.headers.get("Content-Length", 0))
    except ValueError:
        return handler._json({"error": "invalid Content-Length"}, 400)
    if length < 0 or length > max_bytes:
        return handler._json({"error": "request body too large"}, 413)
    try:
        body = json.loads(handler.rfile.read(length).decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return handler._json({"error": "invalid JSON"}, 400)
    filename = str((body or {}).get("filename") or "")
    try:
        return handler._json(delete(base_of(REPORT_ROOT), filename))
    except KeyError:
        return handler._json({"error": f"no study bundle named {filename!r} in the index"}, 404)
    except OSError as exc:
        return handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
