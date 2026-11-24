from __future__ import annotations

import hashlib
import http.client
import json
import socket
import threading
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from graph_scale_dynamics.operations.report_home import root_for
from graph_scale_dynamics.services.web import main as web
from graph_scale_dynamics.services.web import streaming

MIB = 1 << 20


def _pattern(size: int) -> bytes:
    block = hashlib.sha256(b"gsd").digest() * 4096
    return (block * (size // len(block) + 1))[:size]


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    bodies: dict = {}
    gate: threading.Event | None = None
    entered: list = []

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route in self.bodies:
            body, framed = self.bodies[route]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if framed:
                self.send_header("Content-Length", str(len(body)))
            else:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            view = memoryview(body)
            try:
                self.wfile.write(view[:MIB])
                self.entered.append(route)
                if self.gate is not None:
                    self.gate.wait(timeout=20)
                self.wfile.write(view[MIB:])
            except OSError:
                self.close_connection = True
            return
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(streaming, "LARGE_SLOT_WAIT_SECONDS", 0.3)
    _Upstream.bodies, _Upstream.gate, _Upstream.entered = {}, None, []
    report_root = root_for(tmp_path / "reports", "1")
    (report_root / "reports").mkdir(parents=True)
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    upstream.daemon_threads = True
    server = web.BoundedThreadingHTTPServer(("127.0.0.1", 0), web.build_handler(
        api_host="127.0.0.1", api_port=upstream.server_address[1], bind_host="127.0.0.1",
        allowed_hosts=(), base_path="", report_root=report_root))
    for each in (upstream, server):
        threading.Thread(target=each.serve_forever, daemon=True).start()
    yield server.server_address[1], report_root
    if _Upstream.gate is not None:
        _Upstream.gate.set()
    for each in (server, upstream):
        each.shutdown()
        each.server_close()


def _fetch(port: int, path: str, **headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", path, headers={"Host": "127.0.0.1", **headers})
    response = conn.getresponse()
    digest, size = hashlib.sha256(), 0
    while chunk := response.read(256 * 1024):
        digest.update(chunk)
        size += len(chunk)
    conn.close()
    return response.status, dict(response.getheaders()), size, digest.hexdigest()


def test_a_large_report_file_streams_whole_with_its_length_and_is_never_held_in_memory(served):
    port, report_root = served
    body = _pattern(24 * MIB + 17)
    (report_root / "reports" / "28.json").write_bytes(body)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        status, headers, size, digest = _fetch(port, "/reports/reports/28.json")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert status == 200 and headers["Content-Length"] == str(len(body))
    assert size == len(body) and digest == hashlib.sha256(body).hexdigest()
    assert peak < 8 * MIB, f"the web process held {peak / MIB:.1f} MiB serving a {len(body) / MIB:.0f} MiB file"


@pytest.mark.parametrize("framed", [True, False], ids=["with_its_length", "close_delimited"])
def test_a_large_api_answer_streams_through_whole(served, framed):
    port, _ = served
    body = _pattern(12 * MIB + 5)
    _Upstream.bodies["/api/landscape/1"] = (body, framed)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        status, headers, size, digest = _fetch(port, "/api/landscape/1")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert status == 200 and size == len(body) and digest == hashlib.sha256(body).hexdigest()
    if framed:
        assert headers["Content-Length"] == str(len(body))
    else:
        assert headers.get("Transfer-Encoding") == "chunked" and "Content-Length" not in headers
    assert peak < 8 * MIB, f"the web process held {peak / MIB:.1f} MiB relaying a {len(body) / MIB:.0f} MiB answer"


def test_a_third_large_answer_at_once_is_told_to_come_back_and_a_small_one_is_not(served):
    port, report_root = served
    body = _pattern(8 * MIB)
    _Upstream.gate = threading.Event()
    for name in ("a", "b", "c"):
        _Upstream.bodies[f"/api/big/{name}"] = (body, True)
    results: dict = {}
    held = [threading.Thread(target=lambda n=n: results.__setitem__(n, _fetch(port, f"/api/big/{n}")), daemon=True)
            for n in ("a", "b")]
    for thread in held:
        thread.start()
    for _ in range(200):
        if len(_Upstream.entered) >= 2:
            break
        threading.Event().wait(0.05)
    assert len(_Upstream.entered) == 2, "both large answers are under way"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", "/api/big/c", headers={"Host": "127.0.0.1"})
    refused = conn.getresponse()
    answer = json.loads(refused.read())
    conn.close()
    assert refused.status == 503 and refused.getheader("Retry-After") == str(streaming.RETRY_AFTER_SECONDS)
    assert answer["retryable"] is True
    small = _fetch(port, "/api/overview/1")
    assert small[0] == 200, "an answer of a few bytes needs no large slot"
    (report_root / "reports" / "16.json").write_bytes(body)
    assert _fetch(port, "/reports/reports/16.json")[0] == 200, "files have slots of their own"
    _Upstream.gate.set()
    for thread in held:
        thread.join(timeout=30)
    assert {n: results[n][2] for n in ("a", "b")} == {"a": len(body), "b": len(body)}
    _Upstream.entered.clear()
    assert _fetch(port, "/api/big/c")[2] == len(body), "the slot came back once an answer was sent"


class _Unclosed:
    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def close(self):
        pass


class _OneStream:
    def __init__(self, sock):
        self.stream = sock.makefile("rb")

    def makefile(self, *_args, **_kwargs):
        return _Unclosed(self.stream)


def _two_responses(port: int, raw: bytes) -> list[tuple[int, bytes]]:
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(raw)
        out = []
        stream = _OneStream(sock)
        for _ in range(2):
            response = http.client.HTTPResponse(stream)
            response.begin()
            out.append((response.status, response.read()))
        return out
    finally:
        sock.close()


@pytest.mark.parametrize("first", ["/api/overview/1", "/assets/system.css", "/no-such-page"])
def test_a_get_carrying_a_body_leaves_the_next_request_on_the_connection_intact(served, first):
    port, _ = served
    raw = (f"GET {first} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 34\r\n\r\n"
           "GET /api/smuggled HTTP/1.1\r\nX: y\r\n"
           "GET /api/second HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n").encode()
    (status_one, body_one), (status_two, body_two) = _two_responses(port, raw)
    assert status_one in (200, 404)
    assert status_two == 200 and json.loads(body_two) == {"path": "/api/second"}
    assert b"smuggled" not in body_one + body_two


def test_a_body_too_large_or_unframed_is_refused_and_the_connection_ends(served):
    port, _ = served
    for header in (f"Content-Length: {web.MAX_REQUEST_BYTES + 1}", "Transfer-Encoding: chunked",
                   "Content-Length: 3\r\nContent-Length: 4"):
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        try:
            sock.sendall(f"GET /api/overview/1 HTTP/1.1\r\nHost: 127.0.0.1\r\n{header}\r\n\r\n".encode())
            response = http.client.HTTPResponse(sock)
            response.begin()
            response.read()
            assert response.status in (400, 411, 413), header
            assert response.getheader("Connection") == "close", header
            try:
                sock.sendall(b"GET /api/second HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                after = sock.recv(1)
            except (BrokenPipeError, ConnectionResetError):
                after = b""
            assert after == b"", f"the connection stayed open after a refused body ({header})"
        finally:
            sock.close()


def test_the_scrub_for_outside_viewers_still_reads_a_bounded_body(tmp_path):
    class Failing(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"error": "Traceback: the folder secret " + "x" * (2 * MIB),
                               "request_id": "r-2"}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    api = ThreadingHTTPServer(("127.0.0.1", 0), Failing)
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1",
        allowed_hosts=(), base_path="", report_root=None))
    for each in (api, server):
        threading.Thread(target=each.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("GET", "/api/overview/1", headers={"Host": "127.0.0.1", "X-Forwarded-For": "203.0.113.9"})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        assert response.status == 500 and body == {"error": "internal server error"}
    finally:
        for each in (server, api):
            each.shutdown()
            each.server_close()


def test_the_streaming_constants_keep_their_promises():
    assert streaming.CHUNK_BYTES <= streaming.LARGE_BODY_BYTES < 16 * MIB
    assert streaming.LARGE_BODY_SLOTS >= 1 and streaming.RETRY_AFTER_SECONDS >= 1
    assert Path(streaming.__file__).parent == Path(web.__file__).parent
