from __future__ import annotations

import http.client
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.operations import quiet_report
from graph_scale_dynamics.services.api import answer_cache, gate_route, readings_route
from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.services.web import main as web_main

TOKEN = "the-admin-token"
SECRET = "password=hunter2 in /home/operator/259"


class _Repo:
    published: list = []
    refused = False
    stored: list = []

    def __init__(self, _target=None):
        if _Repo.refused:
            raise DatabaseOperationalError(f"could not connect: {SECRET}", transient=False)
        self.conn = SimpleNamespace(execute=lambda _sql, *_a: SimpleNamespace(fetchall=lambda: list(_Repo.stored),
                                                                               fetchone=lambda: None))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        pass

    def get_flag(self, _key, default=""):
        return default

    def campaign(self, _campaign_id):
        return None

    def active_campaigns(self):
        return []

    def publish_runtime_imports(self, service, **_kwargs):
        _Repo.published.append(service)
        return True


@pytest.fixture
def served(monkeypatch, tmp_path: Path):
    _Repo.published, _Repo.refused, _Repo.stored = [], False, []
    monkeypatch.setattr(api_main, "Repo", _Repo)
    monkeypatch.setattr(readings_route, "Repo", _Repo)
    monkeypatch.setattr(gate_route, "Repo", _Repo)
    monkeypatch.setattr(readings_route.study_route, "REPORT_ROOT", readings_route.study_route.REPORT_ROOT)
    db = f"folder-schema:{tmp_path.name}"
    api = api_main.ThreadingHTTPServer(("127.0.0.1", 0), api_main.build_handler(
        db, str(tmp_path / "blobs"), TOKEN, 0, snapshot_tmp=tmp_path / "tmp", calibration_root=tmp_path / "cal",
        repository_root=tmp_path, report_root=tmp_path / "reports", report_campaign_id="c1"))
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=api.server_address[1], bind_host="127.0.0.1", allowed_hosts=(),
        base_path="", report_root=None))
    for server in (api, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(api=api.server_address[1], web=web.server_address[1], db=db)
    for server in (api, web):
        server.shutdown()
        server.server_close()


def _ask(port: int, path: str, method: str = "GET", body: dict | None = None, **headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    sent = json.dumps(body).encode() if body is not None else None
    extra = {"Content-Type": "application/json"} if sent is not None else {}
    conn.request(method, path, body=sent, headers={"Host": "127.0.0.1", **extra, **headers})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    return response.status, json.loads(raw or b"{}")


def test_a_looping_reader_of_a_law_or_the_gate_costs_one_computation(served, monkeypatch):
    asked: list[tuple] = []
    monkeypatch.setattr(readings_route, "structure", lambda repo, c, law: asked.append((c, law)) or {"law": law})
    monkeypatch.setattr(gate_route, "folder_status", lambda repo, c=None: asked.append(("gate", c)) or {"c": c})
    for _ in range(5):
        assert _ask(served.web, "/structure-data/c1/law-a") == (200, {"law": "law-a"})
        assert _ask(served.api, "/api/gate/c1") == (200, {"c": "c1"})
    assert asked == [("c1", "law-a"), ("gate", "c1")], asked
    assert _ask(served.api, "/api/structure/c1/law-b")[0] == 200 and asked[-1] == ("c1", "law-b"), "keyed by the law"
    monkeypatch.setattr(gate_route, "set_early_stage", lambda repo, on: {"on": on})
    assert _ask(served.api, "/api/gate/early_stage", "POST", {"on": True}, **{"X-GSD-Admin-Token": TOKEN})[0] == 200
    _ask(served.api, "/api/gate/c1")
    assert asked[-1] == ("gate", "c1") and len(asked) == 4, "the gate's own write is seen at once"


def test_the_cache_is_bounded_answers_its_age_and_computes_once_for_many():
    now = [0.0]
    cache = answer_cache.AnswerCache(seconds=30, entries=2, clock=lambda: now[0])
    for key in ("a", "b", "c"):
        cache.answer(("structure", "db", key), lambda: key)
    assert cache.computed == 3 and len(cache._answers) == 2
    cache.answer(("structure", "db", "a"), lambda: "a again")
    assert cache.computed == 4, "the oldest went when a third came"
    now[0] = 31.0
    assert cache.answer(("structure", "db", "c"), lambda: "c, later") == "c, later", "withdrawn on its own age"
    slow = answer_cache.AnswerCache()
    calls: list[int] = []

    def compute():
        calls.append(1)
        time.sleep(0.2)
        return "once"
    threads = [threading.Thread(target=slow.answer, args=(("gate", "db", None), compute)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert calls == [1], "eight readers at once paid for one computation"


def test_a_fault_s_detail_goes_with_the_admin_token_not_the_address(served, monkeypatch, capsys):
    def failing(repo, c, law):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(readings_route, "structure", failing)
    for port, headers in ((served.api, {}), (served.web, {}), (served.web, {"X-Forwarded-For": "203.0.113.7"}),
                          (served.api, {"X-GSD-Admin-Token": "wrong"}), (served.web, {"X-GSD-Admin-Token": "wrong"})):
        status, body = _ask(port, "/api/structure/c1/law-x", **headers)
        assert status == 500 and body["error"] == "internal server error" and body["request_id"], (port, headers)
        assert SECRET not in json.dumps(body), (port, headers)
    assert SECRET in capsys.readouterr().err, "the detail goes to the log, under its request id"
    for port in (served.api, served.web):
        status, body = _ask(port, "/api/structure/c1/law-x", **{"X-GSD-Admin-Token": TOKEN})
        assert status == 500 and SECRET in body["error"], port
    _Repo.refused = True
    status, body = _ask(served.web, "/api/campaigns")
    assert status == 503 and body.get("retryable") and "detail" not in body and SECRET not in json.dumps(body)
    status, body = _ask(served.web, "/api/campaigns", **{"X-GSD-Admin-Token": TOKEN})
    assert status == 503 and SECRET in body["detail"]


def test_a_read_writes_nothing_and_the_write_waits_for_the_token(served, monkeypatch):
    _Repo.stored = [{"key": "runtime_imports:api", "value": json.dumps({"service": "api", "pid": 1,
                                                                          "modules": ["an.old.module"]})}]
    status, body = _ask(served.web, "/api/runtime-imports")
    assert status == 200 and _Repo.published == [], "a GET published the API's imports"
    assert [(r["service"], r["pid"]) for r in body["services"]] == [("api", os.getpid())], "the API's own set, live"
    assert _ask(served.web, "/api/runtime-imports", "POST", {})[0] == 403 and _Repo.published == []
    assert _ask(served.web, "/api/runtime-imports", "POST", {}, **{"X-GSD-Admin-Token": TOKEN})[0] == 200
    assert _Repo.published == ["api"]

    started: list[bool] = []
    monkeypatch.setattr(quiet_report, "ensure_runner", lambda open_repo, **kw: started.append(True) or True)
    monkeypatch.setattr(quiet_report, "state", lambda repo: {"stage": quiet_report.ACTIVE_STAGES[0]})
    monkeypatch.setattr(quiet_report, "in_progress", lambda repo: True)
    monkeypatch.setattr(quiet_report, "work_in_flight", lambda repo, now=None: {})
    for _ in range(3):
        status, body = _ask(served.web, "/api/reports/status/c1")
        assert status == 200 and body["quiet_report"]["stage"] == quiet_report.ACTIVE_STAGES[0]
    assert started == [], "a status read restarted the quiet report's runner"
    monkeypatch.setattr(quiet_report, "request", lambda repo, c, action="start", **kw: ({"error": "in progress"}, 409))
    assert _ask(served.web, "/api/reports/trigger", "POST", {"campaign_id": "c1"})[0] == 403 and started == []
    status, _ = _ask(served.web, "/api/reports/trigger", "POST", {"campaign_id": "c1"}, **{"X-GSD-Admin-Token": TOKEN})
    assert status == 409 and started == [True], "the admin's POST is where the runner is made sure of"
