from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.services.api import readings_route

TOKEN = "secret-token"


class _Repo:
    calls: list = []
    flags: dict = {}

    def __init__(self, target=None):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id, "status": "closed", "spec": {}}

    def delete_campaign(self, *args, **kwargs):
        _Repo.calls.append(("delete_campaign", args, kwargs))
        return {}

    def stop_campaign_work(self, *args, **kwargs):
        _Repo.calls.append(("stop_campaign_work", args, kwargs))
        return 0


@pytest.fixture
def server(monkeypatch, tmp_path: Path):
    _Repo.calls = []
    monkeypatch.setattr(api_main, "Repo", _Repo)
    handler = api_main.build_handler("unused", str(tmp_path), TOKEN, 8765, bind_host="127.0.0.1")
    httpd = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(httpd, path: str, body: dict, *, admin: bool) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    headers = {"Host": f"127.0.0.1:{httpd.server_port}", "Content-Type": "application/json"}
    if admin:
        headers["X-GSD-Admin-Token"] = TOKEN
    conn.request("POST", path, body=json.dumps(body).encode(), headers=headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        return response.status, json.loads(raw or b"{}")
    except ValueError:
        return response.status, {}


def test_no_route_deletes_a_campaign_outside_the_campaigns_page(server):
    for path in ("/api/campaign/7/delete", "/api/campaigns/7/delete", "/api/campaign/7"):
        status, _ = _post(server, path, {"confirm": "7"}, admin=True)
        assert status >= 400, (path, status)
    assert not [c for c in _Repo.calls if c[0] == "delete_campaign"]


def test_a_study_bundle_is_deleted_by_an_admin_only(server, monkeypatch):
    seen = []

    def post(handler, db_path, parts, max_bytes):
        seen.append(parts)
        return handler._json({"ok": True}, 200)

    monkeypatch.setattr(readings_route, "post", post)
    assert readings_route.handles(["api", "study-bundles", "delete"])
    status, _ = _post(server, "/api/study-bundles/delete", {"filename": "study_256_x.tar.zst"}, admin=False)
    assert status == 403 and seen == [], "without the admin capability nothing reaches the delete"
    status, body = _post(server, "/api/study-bundles/delete", {"filename": "study_256_x.tar.zst"}, admin=True)
    assert status == 200 and body == {"ok": True} and seen == [["api", "study-bundles", "delete"]]


class _PageRepo:
    def __init__(self, problems=()):
        self.problems, self.calls, self.flags = list(problems), [], {}

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id} if campaign_id == "7" else None

    def stop_campaign_work(self, campaign_id, reason):
        self.calls.append(("stop", campaign_id))
        return 3

    def delete_campaign(self, campaign_id, force=False):
        self.calls.append(("delete", campaign_id, force))
        return {"campaigns": 1}

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def test_the_page_deletes_only_a_campaign_named_back_and_through_the_fenced_path(monkeypatch):
    from contextlib import contextmanager

    from graph_scale_dynamics.operations import maintenance
    from graph_scale_dynamics.services.api import campaign_manager as M
    held = []

    @contextmanager
    def exclusive(repo):
        held.append("in")
        yield
        held.append("out")

    monkeypatch.setattr(maintenance, "exclusive_maintenance", exclusive)
    monkeypatch.setattr(M, "_mark_stale", lambda: None)
    repo = _PageRepo()
    monkeypatch.setattr(M, "delete_problems", lambda r, campaign: r.problems)
    assert M._delete(repo, "404", {"confirm": "404"})[1] == 404
    for confirm in (None, "", "8", " 77 "):
        body, status = M._delete(repo, "7", {"confirm": confirm})
        assert status == 400 and "type 7" in body["error"], confirm
    assert repo.calls == [] and held == []
    blocked = _PageRepo(problems=["its fleet is running"])
    body, status = M._delete(blocked, "7", {"confirm": "7"})
    assert status == 409 and "its fleet is running" in body["error"] and blocked.calls == []
    body, status = M._delete(repo, "7", {"confirm": " 7 "})
    assert status == 200 and body["deleted"] == "7"
    assert repo.calls == [("stop", "7"), ("delete", "7", True)] and held == ["in", "out"]


def test_every_campaign_action_the_page_can_send_needs_the_admin_token(server, monkeypatch):
    from graph_scale_dynamics.services.api import campaign_manager
    reached = []
    monkeypatch.setattr(campaign_manager, "handle", lambda repo, sent: reached.append(sent) or ({"ok": True}, 200))
    for action in campaign_manager.ACTIONS:
        status, _ = _post(server, "/api/campaigns/manage", {"action": action, "campaign_id": "7"}, admin=False)
        assert status == 403, (action, status)
    assert reached == [], "without the admin capability no campaign action reaches the manager"
    status, body = _post(server, "/api/campaigns/manage", {"action": "pause", "campaign_id": "7"}, admin=True)
    assert status == 200 and body == {"ok": True} and len(reached) == 1
