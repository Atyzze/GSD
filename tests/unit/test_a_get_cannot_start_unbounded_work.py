from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.services.api import dashboard_workers
from graph_scale_dynamics.services.api import main as api_main

CAMPAIGNS = ("c1", "c2", "c3")


class _Repo:
    def __init__(self, _target):
        self.conn = SimpleNamespace(execute=lambda _sql, *_a: SimpleNamespace(
            fetchall=lambda: [{"campaign_id": c} for c in CAMPAIGNS]))

    def close(self):
        pass

    def get_flag(self, _key, default=""):
        return default

    def set_flag(self, _key, _value):
        pass


@pytest.fixture
def api(monkeypatch, tmp_path: Path):
    launched: list[list[str]] = []
    release = threading.Event()
    outcome = {"returncode": 0}

    def run(cmd, **_kwargs):
        launched.append(list(cmd))
        release.wait(timeout=10)
        return SimpleNamespace(returncode=outcome["returncode"], stderr="failed" if outcome["returncode"] else "")

    monkeypatch.setattr(api_main, "Repo", _Repo)
    monkeypatch.setattr(api_main.subprocess, "run", run)
    handler = api_main.build_handler("unused", str(tmp_path), "token", 0, snapshot_tmp=tmp_path / "tmp",
                                     exploration_map_mode="lazy", past_research_mode="off")
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def get(path: str):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        response = conn.getresponse()
        body = json.loads(response.read() or b"{}")
        conn.close()
        return response.status, body

    yield SimpleNamespace(get=get, launched=launched, release=release, outcome=outcome)
    release.set()
    server.shutdown()
    server.server_close()


def _workers(launched, module: str) -> list[str]:
    return [cmd[cmd.index("--campaign") + 1] for cmd in launched if module in " ".join(cmd)]


def test_an_id_that_names_no_campaign_starts_nothing(api):
    for i in range(40):
        status, body = api.get(f"/api/landscape/x{i}")
        assert status == 404 and body["error"] == "unknown campaign"
        assert api.get(f"/api/overview/x{i}?exploration=1")[0] == 404
        assert api.get(f"/api/overview/x{i}")[0] == 404
    time.sleep(0.3)
    assert api.launched == [], "a worker was started for a campaign that does not exist"


def test_at_most_two_workers_run_at_once(api):
    for campaign in CAMPAIGNS:
        api.get(f"/api/landscape/{campaign}")
        api.get(f"/api/overview/{campaign}?exploration=1")
    time.sleep(0.5)
    assert len(api.launched) == dashboard_workers.DASHBOARD_WORKER_SLOTS, api.launched
    api.release.set()
    time.sleep(0.5)
    for campaign in CAMPAIGNS:
        api.get(f"/api/landscape/{campaign}")
    time.sleep(0.5)
    assert len(_workers(api.launched, "landscape_worker")) >= 2, "the slots came back once the workers ended"


def test_a_failed_worker_is_not_started_again_on_every_poll(api):
    api.outcome["returncode"] = 1
    api.release.set()
    api.get("/api/landscape/c1")
    time.sleep(0.5)
    for _ in range(10):
        status, body = api.get("/api/landscape/c1")
        assert status == 202
    time.sleep(0.3)
    assert _workers(api.launched, "landscape_worker") == ["c1"], api.launched


def test_a_section_that_is_off_on_the_dashboard_still_answers_the_explorer_within_the_bound(api):
    status, _body = api.get("/api/overview/c1?past=1")
    assert status != 409
    time.sleep(0.3)
    assert len(_workers(api.launched, "overview_worker")) <= 2


def test_a_history_build_cannot_hold_up_the_landscape(api):
    for campaign in CAMPAIGNS:
        api.get(f"/api/overview/{campaign}?exploration=1")
    time.sleep(0.4)
    assert len(_workers(api.launched, "overview_worker")) == 1, "history holds one slot, not the landscape's"
    status, _body = api.get("/api/landscape/c1")
    time.sleep(0.4)
    assert status != 404 and _workers(api.launched, "landscape_worker") == ["c1"]


def test_a_real_campaign_is_not_called_unknown_when_the_list_cannot_be_read(monkeypatch, tmp_path):
    class _Down:
        def __init__(self, _target):
            raise OSError("database unavailable")

    monkeypatch.setattr(api_main, "Repo", _Down)
    monkeypatch.setattr(api_main.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stderr=""))
    handler = api_main.build_handler("unused", str(tmp_path), "token", 0, snapshot_tmp=tmp_path / "tmp",
                                     exploration_map_mode="lazy", past_research_mode="off")
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("GET", "/api/landscape/c1", headers={"Host": "127.0.0.1"})
        response = conn.getresponse()
        body = json.loads(response.read() or b"{}")
        conn.close()
        assert response.status == 503 and body["retryable"] is True, (response.status, body)
    finally:
        server.shutdown()
        server.server_close()
