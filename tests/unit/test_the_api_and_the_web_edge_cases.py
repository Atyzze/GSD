from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_access_file_keeps_only_the_dashboard_s_words_and_so_many_keys():
    from graph_scale_dynamics.services.web import bundle_keeper as B
    assert B.route_pattern("/api/landscape/5") == "/api/landscape/{id}"
    assert B.route_pattern("/api/hello-from-a-stranger") == "/api/{x}"
    for word in ("api", "landscape", "overview", "reports"):
        assert word in B._known()
    counter = B.AccessCounter()
    counter._counts.update({f"/r{i}": {"direct": 1} for i in range(B.MAX_ROUTES)})
    counter.record("/api/overview/9", None, None)
    assert B.OTHER in counter.payload()["routes"], "the keys are bounded"


@pytest.fixture
def servers(tmp_path):
    from graph_scale_dynamics.services.api import main as api_main
    from graph_scale_dynamics.services.web import main as web_main
    api = api_main.ThreadingHTTPServer(("127.0.0.1", 0), api_main.build_handler(
        "unused", str(tmp_path), "token", 8765, bind_host="127.0.0.1"))
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1",
        allowed_hosts=(), base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield api.server_address[1], web.server_address[1]
    for server in (api, web):
        server.shutdown()
        server.server_close()


def _malformed(port: int, path: str, **headers) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", path)
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "not-a-number")
    for key, value in headers.items():
        conn.putheader(key, value)
    conn.endheaders()
    response = conn.getresponse()
    body = json.loads(response.read() or b"{}")
    conn.close()
    assert "malformed" in str(body.get("error")) or response.status != 400, body
    return response.status


def test_a_malformed_request_is_answered_400(servers):
    api, web = servers
    assert _malformed(web, "/api/pause") == 400
    assert _malformed(api, "/api/campaigns/manage", **{"X-GSD-Admin-Token": "token"}) == 400


def test_a_gone_process_s_samples_are_dropped(monkeypatch):
    from graph_scale_dynamics.services.api import host
    host._SERVICE_PROC_SAMPLES[2 ** 22 + 7] = (0.0, 0.0, None, None)
    out = host._service_process_sample(2 ** 22 + 7)
    assert out["process_state"] == "missing" and (2 ** 22 + 7) not in host._SERVICE_PROC_SAMPLES


def test_the_structure_reading_is_given_its_time_and_asked_again():
    from graph_scale_dynamics.services.web import main as web
    assert any(prefix == "/api/structure/" for prefix, _ in web.SLOW_ROUTES)


def test_a_create_is_on_record_before_the_fleet_is_divided(monkeypatch):
    from graph_scale_dynamics.services.api import campaign_manager as CM

    class Repo:
        flags: dict = {}

        def get_flag(self, key, default=""):
            return self.flags.get(key, default)

        def set_flag(self, key, value):
            self.flags[key] = value

        def campaign(self, campaign_id):
            return {"campaign_id": campaign_id}

    monkeypatch.setattr(CM, "_spec_for_create", lambda repo, body: ({"operator_whitelist": []}, None, None))
    monkeypatch.setattr(CM, "create_campaign", lambda repo, spec, **kw: {"campaign_id": "7"})

    def divide(*a, **k):
        raise RuntimeError("the division failed after the create")

    monkeypatch.setattr(CM, "apply_allocation", divide)
    repo = Repo()
    body = {"request_id": "abcdefgh12", "allocation": {"1": 2}}
    with pytest.raises(RuntimeError):
        CM._create(repo, body, "a reason")
    answer, status = CM._create(repo, body, "a reason")
    assert status == 200 and answer["campaign_id"] == "7" and answer.get("repeated")


def test_a_500_names_its_exception_only_to_a_request_that_carries_the_admin_token(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from graph_scale_dynamics.services.web import main as web_main

    class Failing(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"error": "KeyError: 'the folder secret'", "request_id": "r-1"}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    api = ThreadingHTTPServer(("127.0.0.1", 0), Failing)
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1",
        allowed_hosts=(), base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def ask(**headers):
            conn = http.client.HTTPConnection("127.0.0.1", web.server_address[1], timeout=10)
            conn.request("GET", "/api/overview", headers=headers)
            response = conn.getresponse()
            out = (response.status, json.loads(response.read()))
            conn.close()
            return out
        here = ask()
        assert here == (500, {"error": "internal server error", "request_id": "r-1"}), (
            "a proxy on this machine that names no client looks local: the address decides nothing")
        assert ask(**{"X-Forwarded-For": "203.0.113.7"}) == here
        admin = ask(**{"X-GSD-Admin-Token": "the token"})
        assert admin[0] == 500 and "the folder secret" in admin[1]["error"], "the API checks the token it is passed"
    finally:
        for server in (api, web):
            server.shutdown()
            server.server_close()
