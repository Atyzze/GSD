from __future__ import annotations

import json
import threading
import time

from graph_scale_dynamics.domain.model import utc_now

CONTRACT = "gsd-events-1"
PARTS = ["api", "events"]
MOST = 8
PING_SECONDS = 15.0
GATHER_SECONDS = 1.0
RETRY_MS = 5000
READINGS = ("analysis_queue", "candidate_evidence_rebuilds")
RUNS = ("jobs",)
_OPEN = threading.BoundedSemaphore(MOST)


def frame(event: str | None = None, data: dict | None = None, *, comment: str | None = None,
          retry: int | None = None) -> bytes:
    lines = []
    if comment is not None:
        lines.append(f": {comment}")
    if retry is not None:
        lines.append(f"retry: {int(retry)}")
    if event is not None:
        lines.append(f"event: {event}")
    if data is not None:
        lines.append("data: " + json.dumps(data, sort_keys=True))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def gathered(payloads) -> dict:
    tables, statuses, readings, runs = set(), set(), False, False
    for payload in payloads:
        try:
            note = json.loads(payload or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(note, dict):
            continue
        table, status = str(note.get("table") or ""), str(note.get("status") or "")
        tables.add(table)
        statuses.add(status)
        readings = readings or (table in READINGS and status == "done")
        runs = runs or (table in RUNS and status in ("done", "failed", "queued"))
    return {"tables": sorted(t for t in tables if t), "statuses": sorted(s for s in statuses if s),
            "readings": readings, "runs": runs, "at": utc_now()}


def _refuse(handler, code: int, why: str) -> None:
    body = json.dumps({"error": why, "contract": CONTRACT}).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Retry-After", "30")
    handler.end_headers()
    handler.wfile.write(body)


def _head(handler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    handler.close_connection = True


def _send(handler, chunk: bytes) -> None:
    handler.wfile.write(chunk)
    handler.wfile.flush()


def _notes(raw, timeout: float, *, clock=time.monotonic) -> list[str]:
    found = [note.payload for note in raw.notifies(timeout=max(0.0, float(timeout)), stop_after=1)]
    if not found:
        return []
    deadline = clock() + GATHER_SECONDS
    while True:
        left = deadline - clock()
        if left <= 0:
            return found
        found += [note.payload for note in raw.notifies(timeout=left)]


def stream(handler, open_repo, *, on_readings=None, rounds: int | None = None, notes=_notes) -> int:
    if not _OPEN.acquire(blocking=False):
        _refuse(handler, 503, f"{MOST} pages already follow the events; this one polls instead")
        return 0
    sent = 0
    try:
        repo = open_repo()
        try:
            repo.conn.listen_for_work()
            _head(handler)
            _send(handler, frame("hello", {"contract": CONTRACT, "at": utc_now(), "ping_seconds": PING_SECONDS},
                                 retry=RETRY_MS))
            done = 0
            while rounds is None or done < rounds:
                done += 1
                batch = notes(repo.conn.raw, PING_SECONDS)
                if not batch:
                    _send(handler, frame(comment="ping"))
                    continue
                said = gathered(batch)
                if said["readings"] and on_readings is not None:
                    on_readings()
                _send(handler, frame("work", said))
                sent += 1
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass
        finally:
            repo.close()
    finally:
        _OPEN.release()
    return sent


__all__ = ["CONTRACT", "GATHER_SECONDS", "MOST", "PARTS", "PING_SECONDS", "READINGS", "RETRY_MS", "frame", "gathered",
           "stream"]
