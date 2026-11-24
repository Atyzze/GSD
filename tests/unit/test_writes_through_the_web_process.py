from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.services.web import main as web_main

TOKEN = "secret-token"


class _Repo:
    flags: dict = {}
    workers: dict = {}

    def __init__(self, _target):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_flag(self, key, value):
        self.flags[key] = value

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_workers_target(self, campaign_id, target):
        self.workers[campaign_id] = target


@pytest.fixture
def through_web(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api_main, "Repo", _Repo)
    monkeypatch.setattr(api_main.campaign_manager, "handle", lambda repo, sent: (
        _Repo.workers.update({sent["campaign_id"]: sent["target"]}) or ({"ok": True}, 200)))
    _Repo.flags, _Repo.workers = {}, {}
    api = api_main.ThreadingHTTPServer(("127.0.0.1", 0), api_main.build_handler(
        "unused", str(tmp_path), TOKEN, 8765, bind_host="127.0.0.1"))
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="0.0.0.0",
        allowed_hosts=("snekpas.nl",), base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def post(path: str, body: dict, _method: str = "POST", **headers):
        conn = http.client.HTTPConnection("127.0.0.1", web.server_address[1], timeout=10)
        conn.request(_method, path, body=json.dumps(body).encode(),
                     headers={"Host": headers.pop("Host", "snekpas.nl"), "Content-Type": "application/json", **headers})
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), payload

    yield post
    for server in (api, web):
        server.shutdown()
        server.server_close()


def test_a_write_that_is_not_json_is_refused_through_the_web_process(through_web):
    status, _headers, _body = through_web("/api/pause", {"paused": True}, **{
        "Content-Type": "text/plain", "Origin": "http://snekpas.nl", "X-GSD-Admin-Token": TOKEN})
    assert status == 415, "a form or a text/plain POST is what a cross-site page can send without a preflight"


def test_no_answer_opens_a_cross_origin_read(through_web):
    _status, headers, _body = through_web("/api/pause", {"paused": True}, Origin="https://evil.example")
    assert not any(name.lower().startswith("access-control-allow") for name in headers)


def test_a_foreign_origin_holding_the_token_is_refused_at_the_front_door(through_web):
    status, _headers, body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
        "Origin": "https://evil.example", "X-GSD-Admin-Token": TOKEN})
    assert status == 403 and "origin not allowed" in json.loads(body)["error"]
    assert _Repo.workers == {}, "the API never saw it"
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
        "Referer": "https://evil.example/page", "X-GSD-Admin-Token": TOKEN})
    assert status == 403 and _Repo.workers == {}, "a Referer from another site, where no Origin is sent"
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
        "Origin": "null", "X-GSD-Admin-Token": TOKEN})
    assert status == 403 and _Repo.workers == {}, "an opaque origin is never this dashboard's page"


def test_another_port_on_the_same_host_is_another_origin(through_web):
    for origin in ("http://snekpas.nl:8888", "https://snekpas.nl:8443", "http://snekpas.nl:443"):
        status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
            "Origin": origin, "X-GSD-Admin-Token": TOKEN})
        assert status == 403 and _Repo.workers == {}, origin
    for origin in ("http://snekpas.nl:80", "https://snekpas.nl", "https://snekpas.nl:443"):
        status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
            "Origin": origin, "X-GSD-Admin-Token": TOKEN})
        assert status == 200, origin
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 2}, Host="127.0.0.1:8080", **{
        "Origin": "http://127.0.0.1:8888", "X-GSD-Admin-Token": TOKEN})
    assert status == 403 and _Repo.workers.get("camp-x") == 1, "a page on 8888 is not the dashboard on 8080"
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 2}, Host="127.0.0.1:8080", **{
        "Origin": "http://127.0.0.1:8080", "X-GSD-Admin-Token": TOKEN})
    assert status == 200 and _Repo.workers.get("camp-x") == 2


def test_the_page_s_own_origin_with_the_token_is_admin_from_any_device(through_web):
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 1}, **{
        "Origin": "http://snekpas.nl", "X-GSD-Admin-Token": TOKEN})
    assert status == 200 and _Repo.workers == {"camp-x": 1}
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 2}, **{
        "Origin": "http://snekpas.nl"})
    assert status == 403 and _Repo.workers == {"camp-x": 1}, "without the token, no device is admin"
    status, _headers, _body = through_web("/api/campaigns/manage", {"campaign_id": "camp-x", "target": 3}, **{
        "X-GSD-Admin-Token": TOKEN})
    assert status == 200 and _Repo.workers == {"camp-x": 3}, "a tool that sends no Origin and holds the token"


def test_options_is_answered_405(through_web):
    status, headers, _body = through_web("/api/pause", {}, _method="OPTIONS", Origin="https://evil.example")
    assert status == 405 and headers.get("Allow") == "GET, POST"
    assert not any(name.lower().startswith("access-control-allow") for name in headers)


def test_pause_needs_the_token_even_from_a_page_of_this_dashboard(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "Repo", _Repo)
    _Repo.flags, _Repo.workers = {}, {}
    api = api_main.ThreadingHTTPServer(("127.0.0.1", 0), api_main.build_handler(
        "unused", str(tmp_path), TOKEN, 8765, bind_host="127.0.0.1"))
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="0.0.0.0",
        allowed_hosts=("snekpas.nl",), base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def pause(paused: bool, **headers):
            conn = http.client.HTTPConnection("127.0.0.1", web.server_address[1], timeout=10)
            conn.request("POST", "/api/pause", body=json.dumps({"paused": paused}).encode(),
                         headers={"Host": "snekpas.nl", "Content-Type": "application/json", **headers})
            response = conn.getresponse()
            response.read()
            conn.close()
            return response.status
        assert pause(True, Origin="http://snekpas.nl") == 403, "a page of this dashboard, no token: until 662 public pause"
        assert pause(False) == 403, "a request no page made needs the token"
        assert pause(False, **{"X-GSD-Admin-Token": TOKEN}) == 200
        assert pause(True, Origin="https://evil.example") == 403, "another site, refused at the front door"
    finally:
        for server in (api, web):
            server.shutdown()
            server.server_close()
