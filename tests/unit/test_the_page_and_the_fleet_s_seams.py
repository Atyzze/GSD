from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_fast_overview_carries_the_scratch_s_open_alerts():
    from graph_scale_dynamics.services.api import overview

    class Repo:
        def operational_alerts(self, *, active_only, limit):
            return [{"alert_key": "scratch:full", "source": "scratch", "severity": "error", "message": "full",
                     "detail_json": "{}", "detail": {}},
                    {"alert_key": "liveness:x", "source": "liveness", "severity": "warn", "message": "slow",
                     "detail_json": "{}", "detail": {}}]
    found = overview._scratch_alerts(Repo())
    assert [a["alert_key"] for a in found] == ["scratch:full"] and "detail_json" not in found[0]

    class Broken:
        def operational_alerts(self, **_):
            raise RuntimeError("no table")
    assert overview._scratch_alerts(Broken()) == []


def test_a_restore_writes_nothing_outside_the_state_directory(tmp_path):
    from graph_scale_dynamics.operations import backup
    var = tmp_path / "var"
    for bad in ("/etc/gsd-escaped", "../escaped/file.json", "a/../../escaped.json"):
        manifest = {"var_state": {"root": "state", "files": [{"path": bad}]}}
        with pytest.raises(ValueError, match="unsafe backup manifest path|escapes"):
            backup.restore_var_state(tmp_path / "backup", manifest, var)
    assert not (tmp_path / "escaped").exists() and not Path("/etc/gsd-escaped").exists()


def _handler(length: str):
    from http.client import HTTPMessage

    from graph_scale_dynamics.services.web import main as web
    Handler = web.build_handler(api_host="127.0.0.1", api_port=1, bind_host="127.0.0.1", allowed_hosts=(),
                                base_path="", report_root=None, access_counter=web.AccessCounter())
    sent = []
    handler = Handler.__new__(Handler)
    handler.headers = HTTPMessage()
    handler.headers["Content-Length"] = length
    handler.rfile = io.BytesIO(b"x" * 10)
    handler.close_connection = False
    handler._send = lambda body, content_type, code=200, **kw: sent.append((code, json.loads(body)))
    return handler, sent


def test_the_web_process_refuses_a_body_too_large_or_negative():
    from graph_scale_dynamics.services.web import main as web
    for length in (str(web.MAX_REQUEST_BYTES + 1), "-1"):
        handler, sent = _handler(length)
        handler._answering(handler._proxy)
        assert sent and sent[0][0] == 413, length
        assert handler.close_connection, "a body left unread ends the connection"
    handler, sent = _handler("lots")
    handler._answering(handler._proxy)
    assert sent and sent[0][0] == 400 and sent[0][1]["error"] == "malformed request"
    assert handler.close_connection
    assert web.SOCKET_TIMEOUT_SECONDS > 0 and web.MAX_CONCURRENT_REQUESTS > 0


def test_the_release_keeps_the_host_s_state_out():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import package_release as P
    for rel in ("tools/diagrams/node_modules/x/index.js", "calibration/probe_calibration.json.before-adopt",
                "calibration/probe_calibration.json.12.ab.tmp", "graph_scale_dynamics/gsd_engine_rs.cpython-313.so"):
        assert not P.include_in_release(P.ROOT / rel), rel
    assert P.include_in_release(P.ROOT / "runtime/bootstrap/linux-amd64/libc.so.6"), "the runtime's libraries ship"


def test_a_kept_alive_connection_frees_its_slot_when_idle():
    from graph_scale_dynamics.services.web import main as web
    Handler = web.build_handler(api_host="127.0.0.1", api_port=1, bind_host="127.0.0.1", allowed_hosts=(),
                                base_path="", report_root=None, access_counter=web.AccessCounter())
    handler = Handler.__new__(Handler)
    timeouts = []

    class Connection:
        def settimeout(self, value):
            timeouts.append(value)

    handler.connection, handler._requests_served = Connection(), 0
    handler.close_connection = True
    import http.server
    original = http.server.BaseHTTPRequestHandler.handle_one_request
    http.server.BaseHTTPRequestHandler.handle_one_request = lambda self: None
    try:
        handler.handle_one_request()
        handler.handle_one_request()
    finally:
        http.server.BaseHTTPRequestHandler.handle_one_request = original
    assert timeouts == [web.KEEPALIVE_IDLE_SECONDS] and 0 < web.KEEPALIVE_IDLE_SECONDS < web.SOCKET_TIMEOUT_SECONDS
    assert web.MAX_CONCURRENT_REQUESTS == 64
