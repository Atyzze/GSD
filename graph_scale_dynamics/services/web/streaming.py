from __future__ import annotations

import http.client
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from graph_scale_dynamics.domain.cadence import ticks

CHUNK_BYTES = 1 << 20
LARGE_BODY_BYTES = 4 << 20
LARGE_BODY_SLOTS = 2
LARGE_SLOT_WAIT_SECONDS = 2.0
RETRY_AFTER_SECONDS = int(ticks(1))
ERROR_BODY_BYTES = 64 * 1024
BODY_KINDS = ("file", "api")
NO_BODY_STATUSES = frozenset({204, 304})

SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self' 'unsafe-inline'; "
     "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
     "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"),
)

JSON = "application/json; charset=utf-8"


class LargeBodies:
    def __init__(self, slots: int | None = None):
        count = int(LARGE_BODY_SLOTS if slots is None else slots)
        self.slots = {kind: threading.BoundedSemaphore(count) for kind in BODY_KINDS}

    @contextmanager
    def held(self, kind: str, size: int | None):
        if size is not None and int(size) <= LARGE_BODY_BYTES:
            yield True
            return
        slot = self.slots[kind]
        if not slot.acquire(timeout=LARGE_SLOT_WAIT_SECONDS):
            yield False
            return
        try:
            yield True
        finally:
            slot.release()


def send_head(handler, code: int, content_type: str, length: int | None, *, cache_control: str = "no-store",
              extra_headers: dict | None = None) -> str:
    framing = "length" if length is not None else ("chunked" if handler.request_version == "HTTP/1.1" else "close")
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    for header, value in (extra_headers or {}).items():
        handler.send_header(str(header), str(value))
    if framing == "length":
        handler.send_header("Content-Length", str(int(length)))
    elif framing == "chunked":
        handler.send_header("Transfer-Encoding", "chunked")
    else:
        handler.send_header("Connection", "close")
    handler.send_header("Cache-Control", cache_control)
    for header, value in SECURITY_HEADERS:
        handler.send_header(header, value)
    handler.end_headers()
    return framing


def copy_body(handler, source, length: int | None, framing: str) -> bool:
    sent = 0
    try:
        while length is None or sent < length:
            chunk = source.read(CHUNK_BYTES if length is None else min(CHUNK_BYTES, length - sent))
            if not chunk:
                break
            if framing == "chunked":
                handler.wfile.write(b"%x\r\n" % len(chunk))
                handler.wfile.write(chunk)
                handler.wfile.write(b"\r\n")
            else:
                handler.wfile.write(chunk)
            sent += len(chunk)
        complete = length is None or sent == length
        if complete and framing == "chunked":
            handler.wfile.write(b"0\r\n\r\n")
    except (OSError, http.client.HTTPException):
        complete = False
    if not complete or framing == "close":
        handler.close_connection = True
    return complete


def refuse(handler, code: int, error: str, **extra) -> None:
    handler.close_connection = True
    handler._send(json.dumps({"error": error, **extra}).encode(), JSON, code,
                  extra_headers={"Connection": "close"})


def busy(handler) -> None:
    handler._send(json.dumps({
        "error": f"busy: {LARGE_BODY_SLOTS} large answers of this kind are already being sent; ask again shortly",
        "retryable": True, "retry_after_ms": RETRY_AFTER_SECONDS * 1000,
    }).encode(), JSON, 503, extra_headers={"Retry-After": RETRY_AFTER_SECONDS})


def read_request_body(handler, limit: int) -> tuple[bool, bytes]:
    coding = str(handler.headers.get("Transfer-Encoding") or "").strip().lower()
    if coding and coding != "identity":
        refuse(handler, 411, "a request body must carry a Content-Length")
        return False, b""
    declared = {str(value).strip() for value in (handler.headers.get_all("Content-Length") or [])}
    try:
        if len(declared) > 1:
            raise ValueError("Content-Length declared twice")
        length = int(next(iter(declared), "") or 0)
    except ValueError as exc:
        refuse(handler, 400, "malformed request", detail=type(exc).__name__)
        return False, b""
    if length < 0 or length > int(limit):
        refuse(handler, 413, f"a request body must be 0 to {int(limit):,} bytes")
        return False, b""
    body = handler.rfile.read(length) if length else b""
    if len(body) != length:
        handler.close_connection = True
        return False, b""
    return True, body


def serve_file(handler, large: LargeBodies, target: Path, content_type: str, *,
               extra_headers: dict | None = None) -> None:
    try:
        source = open(target, "rb")
    except OSError:
        handler._send(b'{"error":"not found"}', "application/json", 404)
        return
    with source:
        size = os.fstat(source.fileno()).st_size
        with large.held("file", size) as held:
            if not held:
                return busy(handler)
            try:
                framing = send_head(handler, 200, content_type, size, extra_headers=extra_headers)
            except OSError:
                handler.close_connection = True
                return
            copy_body(handler, source, size, framing)


def upstream_length(response) -> int | None:
    if response.status in NO_BODY_STATUSES or 100 <= response.status < 200:
        return 0
    if (response.getheader("Transfer-Encoding") or "").strip().lower() not in ("", "identity"):
        return None
    try:
        length = int(response.getheader("Content-Length") or "")
    except ValueError:
        return None
    return length if length >= 0 else None


def relay(handler, large: LargeBodies, response, *, scrub) -> None:
    content_type = response.getheader("Content-Type") or "application/octet-stream"
    if scrub is not None:
        handler._send(*scrub(response.read(ERROR_BODY_BYTES)), response.status)
        return
    length = upstream_length(response)
    if length is not None and length <= LARGE_BODY_BYTES:
        handler._send(response.read(length) if length else b"", content_type, response.status)
        return
    with large.held("api", length) as held:
        if not held:
            return busy(handler)
        try:
            framing = send_head(handler, response.status, content_type, length)
        except OSError:
            handler.close_connection = True
            return
        copy_body(handler, response, length, framing)
