from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from graph_scale_dynamics.services.api import campaign_manager as CM
from graph_scale_dynamics.services.web import main as W


class _SlowApi(BaseHTTPRequestHandler):
    delay = 0.0
    writes: list[str] = []

    def log_message(self, *args):
        pass

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        time.sleep(self.delay)
        if self.command == "POST":
            type(self).writes.append(self.path)
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer


@pytest.fixture
def proxied():
    api = ThreadingHTTPServer(("127.0.0.1", 0), _SlowApi)
    web = ThreadingHTTPServer(("127.0.0.1", 0), W.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1",
        allowed_hosts=("127.0.0.1",), base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    _SlowApi.writes = []

    def send(method: str, path: str, delay: float):
        _SlowApi.delay = delay
        conn = http.client.HTTPConnection("127.0.0.1", web.server_address[1], timeout=30)
        conn.request(method, path, body=b"{}" if method == "POST" else None,
                     headers={"Host": "127.0.0.1", "Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read() or b"{}")

    yield send
    for server in (api, web):
        server.shutdown()
        server.server_close()


def test_a_write_slower_than_the_reading_timeout_completes_and_is_reported_as_done(proxied, monkeypatch):
    monkeypatch.setenv("GSD_WEB_API_TIMEOUT_SECONDS", "0.25")
    status, body = proxied("POST", "/api/campaigns/manage", 1.0)
    assert status == 200 and body == {"ok": True}, (status, body)


def test_a_read_slower_than_its_timeout_is_still_cut_off(proxied, monkeypatch):
    status, body = proxied("GET", "/api/campaigns", 2.5)
    assert status == 503 and body["retryable"] is True


def test_a_write_that_times_out_says_its_outcome_is_unknown_not_retryable(proxied, monkeypatch):
    monkeypatch.setattr(W, "WRITE_TIMEOUT_SECONDS", 0.3)
    status, body = proxied("POST", "/api/campaigns/manage", 2.5)
    assert status == 504 and body["retryable"] is False and "reload" in body["error"]
    time.sleep(1.5)
    assert _SlowApi.writes == ["/api/campaigns/manage"], "the API made the change all the same"


class _Repo:
    def __init__(self):
        self.flags, self.campaigns = {}, {}

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value

    def campaign(self, campaign_id):
        return self.campaigns.get(campaign_id)


def test_a_start_sent_again_is_answered_with_the_campaign_the_first_made(monkeypatch):
    repo = _Repo()
    made = []

    def create_once(_repo, _body, _reason, made_now=None, **kw):
        time.sleep(0.2)
        campaign_id = f"c{len(made) + 1}"
        made.append(campaign_id)
        if kw.get("made"):
            kw["made"](campaign_id)
        repo.campaigns[campaign_id] = {"campaign_id": campaign_id}
        return {"ok": True, "campaign_id": campaign_id}, 200

    monkeypatch.setattr(CM, "_create_once", create_once)
    body = {"action": "create", "request_id": "a1b2c3d4-retry"}
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(CM._create(repo, dict(body), None)))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert made == ["c1"], "a start pressed again made a second campaign"
    assert sorted(a[0]["campaign_id"] for a in answers) == ["c1", "c1"]
    assert any(a[0].get("repeated") for a in answers)
    assert CM._create(repo, {"action": "create", "request_id": "another-start"}, None)[0]["campaign_id"] == "c2"
    edited = dict(body, operator_whitelist=["edge_count"])
    assert CM._create(repo, edited, None)[0]["campaign_id"] == "c3", "the same id with edited terms is a new start"
    assert CM._create(repo, {"action": "create", "request_id": "bad id!"}, None)[1] == 400
