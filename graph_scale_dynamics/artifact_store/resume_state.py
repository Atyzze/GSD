from __future__ import annotations

import gzip
import json
import os
import re
import time
from pathlib import Path

from graph_scale_dynamics.scaleflow.one_shot import RESUME_CONTRACT

from graph_scale_dynamics.domain.cadence import ticks  # noqa: E402

RESUME_DIR = "resume"
STOP_GRACE_SECONDS = ticks(30)
FLEET_STOP_GRACE_SECONDS = STOP_GRACE_SECONDS + ticks(3)
RESUME_MIN_SECONDS = 20.0
STOP_FILE_NAME = "stop"


def stop_file_for(job_file: str | Path) -> Path:
    return Path(job_file).parent / STOP_FILE_NAME
RESUME_PRUNE_MIN_AGE_SECONDS = 600.0
_SAFE = re.compile(r"[A-Za-z0-9_.-]{1,160}")


def resume_root(blob_root: str | Path) -> Path:
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    return BlobStore(blob_root).volatile_root


def resume_path(blob_root: str | Path | None, job_id: str) -> Path | None:
    if not blob_root or not _SAFE.fullmatch(str(job_id or "")):
        return None
    return Path(blob_root) / RESUME_DIR / f"{job_id}.json.gz"


def save_resume_state(path: Path, state: dict, *, execution_spec_hash: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(state, execution_spec_hash=str(execution_spec_hash), saved_utc=time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=1) as handle:
        json.dump(body, handle, separators=(",", ":"), allow_nan=False)
    os.replace(temporary, path)
    note = {"seconds_spent": float(state.get("seconds_spent") or 0.0),
            "chunks": len(state.get("history") or []), "in_chunk": bool(state.get("in_chunk")),
            "saved_utc": body["saved_utc"]}
    note_temporary = path.with_name(f"{path.name}.{os.getpid()}.note.tmp")
    note_temporary.write_text(json.dumps(note), encoding="utf-8")
    os.replace(note_temporary, resume_note_path(path))


def resume_note_path(state_path: Path) -> Path:
    return Path(state_path).with_name(Path(state_path).name.replace(".json.gz", ".note.json"))


def read_resume_note(blob_root: str | Path | None, job_id: str) -> dict | None:
    path = resume_path(blob_root, job_id)
    if path is None:
        return None
    try:
        return json.loads(resume_note_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_resume_state(path: Path, *, execution_spec_hash: str) -> tuple[dict | None, str]:
    path = Path(path)
    if not path.is_file():
        return None, "no saved state"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError, EOFError) as exc:
        return None, f"unreadable ({type(exc).__name__})"
    if not isinstance(state, dict) or state.get("contract") != RESUME_CONTRACT:
        return None, f"contract {state.get('contract') if isinstance(state, dict) else None!r}"
    if state.get("execution_spec_hash") != str(execution_spec_hash):
        return None, "written for another execution (engine or policy changed)"
    if not isinstance(state.get("checkpoint"), dict) or not isinstance(state.get("history"), list):
        return None, "incomplete"
    return state, "resumed"


def resume_saved_at(blob_root: str | Path | None, job_id: str) -> float | None:
    path = resume_path(blob_root, job_id)
    try:
        return path.stat().st_mtime if path is not None else None
    except OSError:
        return None


def discard_resume_state(path: Path | None) -> None:
    if path is None:
        return
    for target in (Path(path), resume_note_path(Path(path))):
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def prune_resume_states(conn, blob_root: str | Path, *, min_age_seconds: float = RESUME_PRUNE_MIN_AGE_SECONDS,
                        now: float | None = None,
                        keep: tuple[str, ...] = ("queued", "leased", "failed", "lost", "cancelled")) -> dict:
    directory = Path(blob_root) / RESUME_DIR
    if not directory.is_dir():
        return {"examined": 0, "removed": 0, "bytes_removed": 0}
    clock = time.time() if now is None else float(now)
    files = [f for f in directory.iterdir() if f.is_file() and clock - f.stat().st_mtime >= float(min_age_seconds)
             and not f.name.endswith(".note.json")]
    states = {f.name[:-len(".json.gz")]: f for f in files if f.name.endswith(".json.gz")}
    live = set()
    if states:
        rows = conn.execute(
            "SELECT job_id FROM jobs WHERE status IN (" + ",".join("?" for _ in keep) + ") AND job_id IN ("
            + ",".join("?" for _ in states) + ")", (*keep, *states)).fetchall()
        live = {str(row["job_id"]) for row in rows}
    removed, freed = 0, 0
    for f in files:
        stale = f.name.endswith(".tmp") or (f.name.endswith(".json.gz") and f.name[:-len(".json.gz")] not in live)
        if stale:
            size = f.stat().st_size
            discard_resume_state(f)
            removed, freed = removed + 1, freed + size
    return {"examined": len(files), "removed": removed, "bytes_removed": freed}
