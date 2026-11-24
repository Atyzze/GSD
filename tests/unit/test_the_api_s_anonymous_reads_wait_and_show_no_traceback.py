from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.observability import evidence_sources, incidents
from graph_scale_dynamics.services.api import admin_view, dashboard_limit
from graph_scale_dynamics.services.api import main as api_main
from graph_scale_dynamics.services.web import main as web_main

TOKEN, INTERNAL = "the-admin-token", "the-internal-token"
SECRET = "password=hunter2"


class _Repo:
    def __init__(self, _target=None):
        self.conn = SimpleNamespace(execute=lambda _sql, *_a: SimpleNamespace(
            fetchall=lambda: [{"campaign_id": "c1"}], fetchone=lambda: None))

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

    def publish_runtime_imports(self, *_args, **_kwargs):
        return False


def _serve(handler):
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _get(port: int, path: str, **headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("GET", path, headers={"Host": "127.0.0.1", **headers})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        return response.status, json.loads(raw)
    except ValueError:
        return response.status, raw.decode("utf-8", "replace")


@pytest.fixture
def api(monkeypatch, tmp_path: Path):
    incidents.clear()
    monkeypatch.setattr(api_main, "Repo", _Repo)
    var = tmp_path / "var"
    (var / "log").mkdir(parents=True)
    (var / "log" / evidence_sources.SUPERVISOR_LOG_NAME).write_text(
        f"[worker] Traceback (most recent call last):\n[worker] KeyError: '{SECRET}'\n", encoding="utf-8")

    def build(**kwargs):
        handler = api_main.build_handler("unused", str(tmp_path / "blobs"), TOKEN, 0, snapshot_tmp=tmp_path / "tmp",
                                         calibration_root=var / "calibration", repository_root=tmp_path,
                                         internal_token=INTERNAL, **kwargs)
        server = _serve(handler)
        servers.append(server)
        return server.server_address[1]

    servers: list = []
    yield build
    for server in servers:
        server.shutdown()
        server.server_close()
    incidents.clear()


LIMITED = ("/api/structure/c1/law", "/api/gate", "/api/gate/c1", "/api/performance/c1", "/api/memory-ledger",
           "/api/stranded/c1", "/api/schema", "/api/calibration", "/api/calibration/cells", "/api/supervisor-log",
           "/api/runtime-imports", "/api/reports/status/c1", "/api/campaigns")


def test_every_read_that_walks_the_database_or_the_disk_waits_for_the_dashboard_s_slot(api, monkeypatch):
    monkeypatch.setenv("GSD_DASHBOARD_DB_CONCURRENCY", "1")
    monkeypatch.setattr(dashboard_limit, "SLOT_WAIT_SECONDS", 0.1)
    entered, release = threading.Event(), threading.Event()

    def held_payload(_repo, campaign_id):
        if campaign_id == "hold":
            entered.set()
            release.wait(timeout=20)
        return {"campaign_id": campaign_id}

    monkeypatch.setattr(api_main.evidence_sources, "performance_payload", held_payload)
    port = api()
    holder: dict = {}
    thread = threading.Thread(target=lambda: holder.update(answer=_get(port, "/api/performance/hold")), daemon=True)
    thread.start()
    assert entered.wait(timeout=10), "the first read took the one slot"
    try:
        for path in LIMITED:
            status, body = _get(port, path, **{"X-GSD-Admin-Token": TOKEN})
            assert status == 503 and body == dashboard_limit.BUSY, (path, status, body)
    finally:
        release.set()
    thread.join(timeout=20)
    assert holder["answer"] == (200, {"campaign_id": "hold"})
    for path in ("/api/performance/c1", "/api/supervisor-log", "/api/gate/c1", "/api/schema"):
        status, _body = _get(port, path, **{"X-GSD-Admin-Token": TOKEN})
        assert status != 503, (path, status)
    assert dashboard_limit.limited(["api", "structure", "c1", "law"]) and not dashboard_limit.limited(
        ["api", "overview", "c1"]), "the cached pages answer from their caches and take no slot here"


def test_the_services_console_is_the_admin_s_and_the_study_runner_s_alone(api, tmp_path):
    port = api()
    web = web_main.ThreadingHTTPServer(("127.0.0.1", 0), web_main.build_handler(
        api_host="127.0.0.1", api_port=port, bind_host="127.0.0.1", allowed_hosts=(), base_path="",
        report_root=None))
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        for target, headers in ((port, {}), (port, {"X-GSD-Admin-Token": "wrong"}),
                                (web.server_address[1], {}),
                                (web.server_address[1], {"X-Forwarded-For": "203.0.113.7"}),
                                (web.server_address[1], {"X-GSD-Internal-Token": INTERNAL})):
            status, body = _get(target, "/api/supervisor-log", **headers)
            assert status == 403 and SECRET not in json.dumps(body), (target, headers, status)
        for target, headers in ((port, {"X-GSD-Admin-Token": TOKEN}), (port, {"X-GSD-Internal-Token": INTERNAL}),
                                (web.server_address[1], {"X-GSD-Admin-Token": TOKEN})):
            status, body = _get(target, "/api/supervisor-log?lines=100", **headers)
            assert status == 200 and SECRET in body, (target, headers, status)
    finally:
        web.shutdown()
        web.server_close()


def _fail_with_detail():
    raise RuntimeError(f"the overview could not be built\nDETAIL: row 7 of the folder's table\nHINT: {SECRET}")


def _until(port: int, path: str, found, **headers):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, body = _get(port, path, **headers)
        if found(body):
            return status, body
        time.sleep(0.05)
    raise AssertionError(f"{path} never showed what was waited for: {body}")


def test_an_incident_seen_by_a_viewer_who_is_not_the_admin_carries_no_traceback(api, monkeypatch):
    def failing(*_args, **_kwargs):
        _fail_with_detail()

    monkeypatch.setattr(api_main, "build_fast_overview", failing)
    port = api()
    _, body = _until(port, "/api/overview/c1",
                     lambda b: (b.get("dashboard_response") or {}).get("last_refresh_error"))
    response = body["dashboard_response"]
    assert SECRET not in json.dumps(body), "the detail of the failure reached a viewer without the token"
    assert response["last_refresh_error"] == "RuntimeError: the overview could not be built"
    (incident,) = response["incidents"]
    assert "traceback" not in incident and "\n" not in incident["error"]
    assert incident["where"] == "overview refresh" and incident["count"] >= 1
    assert incident["origin"] and incident["last_epoch"], "the summary keeps where and when"
    for headers in ({"X-GSD-Admin-Token": TOKEN}, {"X-GSD-Internal-Token": INTERNAL}):
        _, seen = _get(port, "/api/overview/c1", **headers)
        whole = seen["dashboard_response"]
        assert SECRET in whole["last_refresh_error"] and "Traceback" in whole["incidents"][0]["traceback"], headers


def test_a_worker_s_stderr_reaches_only_the_admin(api, monkeypatch):
    stderr = ("Traceback (most recent call last):\n  File \"/home/operator/secret/landscape.py\", line 3\n"
              f"    {SECRET}\nValueError: the landscape could not be read\n")
    monkeypatch.setattr(api_main.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=1, stderr=stderr))
    port = api()
    _, body = _until(port, "/api/landscape/c1?meta=1", lambda b: b.get("last_refresh_error"))
    assert body["last_refresh_error"] == "ValueError: the landscape could not be read"
    assert SECRET not in json.dumps(body) and "/home/operator" not in json.dumps(body)
    _, seen = _get(port, "/api/landscape/c1?meta=1", **{"X-GSD-Admin-Token": TOKEN})
    assert SECRET in seen["last_refresh_error"], "the admin still reads the worker's stderr whole"


def test_one_line_keeps_the_exception_and_drops_the_rest():
    assert admin_view.one_line("RuntimeError: Traceback (most recent call last):\n  File x\nKeyError: 'k'") == (
        "KeyError: 'k'")
    assert admin_view.one_line("OperationalError: gone\nDETAIL: more") == "OperationalError: gone"
    assert admin_view.one_line(None) is None and admin_view.one_line("x" * 900) == "x" * admin_view.LINE_CHARS
    assert admin_view.incidents([{"error": "a\nb", "traceback": "t"}], admin=True) == [
        {"error": "a\nb", "traceback": "t"}]
