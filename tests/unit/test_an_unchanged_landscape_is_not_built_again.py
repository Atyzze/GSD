from __future__ import annotations

import http.client
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.services.api import landscape_inputs
from graph_scale_dynamics.services.api import main as api_main


class _Repo:
    def __init__(self, _target):
        self.conn = SimpleNamespace(execute=lambda _sql, *_a: SimpleNamespace(
            fetchall=lambda: [{"campaign_id": "c1"}]))

    def close(self):
        pass

    def get_flag(self, _key, default=""):
        return default

    def set_flag(self, _key, _value):
        pass


@pytest.fixture
def api(monkeypatch, tmp_path: Path):
    launched: list[list[str]] = []
    state = {"inputs": "a" * 20}

    def run(cmd, **_kwargs):
        launched.append(list(cmd))
        body = Path(cmd[cmd.index("--output") + 1])
        meta = Path(cmd[cmd.index("--meta") + 1])
        body.write_text(json.dumps({"campaign_id": "c1", "dimension_points": [], "revision": "r1"}))
        inputs = cmd[cmd.index("--inputs") + 1] if "--inputs" in cmd else None
        meta.write_text(json.dumps({"campaign_id": "c1", "revision": "r1", **({"inputs": inputs} if inputs else {})}))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(api_main, "Repo", _Repo)
    monkeypatch.setattr(api_main.subprocess, "run", run)
    monkeypatch.setattr(landscape_inputs, "stamp", lambda _conn: state["inputs"])
    handler = api_main.build_handler("unused", str(tmp_path), "token", 0, snapshot_tmp=tmp_path / "tmp",
                                     exploration_map_mode="off", past_research_mode="off")
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def get(path: str):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        response = conn.getresponse()
        body = json.loads(response.read() or b"{}")
        conn.close()
        return response.status, body

    def settle():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(t.name.startswith("gsd-landscape-") for t in threading.enumerate()):
            time.sleep(0.05)

    body = tmp_path / "tmp" / "dashboard-cache" / "landscape-c1.json"
    yield SimpleNamespace(get=get, launched=launched, state=state, settle=settle, body=body)
    server.shutdown()
    server.server_close()


def _age(api, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(api.body, (old, old))


def test_a_landscape_whose_inputs_are_unchanged_is_kept_and_no_worker_starts(api):
    api.get("/api/landscape/c1?meta=1")
    api.settle()
    assert len(api.launched) == 1 and api.launched[0][-2:] == ["--inputs", "a" * 20]
    for _ in range(5):
        _age(api, 3600)
        status, meta = api.get("/api/landscape/c1?meta=1")
        api.settle()
        assert status == 200 and meta["revision"] == "r1" and meta["inputs"] == "a" * 20
    assert len(api.launched) == 1, "an idle folder's landscape was built again: " + str(api.launched)
    assert time.time() - api.body.stat().st_mtime < 60, "a kept landscape is marked as read now, so its age resets"


def test_a_write_to_what_the_landscape_reads_builds_it_again(api):
    api.get("/api/landscape/c1?meta=1")
    api.settle()
    api.state["inputs"] = "b" * 20
    _age(api, 3600)
    api.get("/api/landscape/c1?meta=1")
    api.settle()
    assert [cmd[-1] for cmd in api.launched] == ["a" * 20, "b" * 20]


def test_inputs_that_cannot_be_read_build_it_as_before(api, monkeypatch):
    monkeypatch.setattr(landscape_inputs, "stamp", lambda _conn: (_ for _ in ()).throw(OSError("down")))
    for _ in range(2):
        api.get("/api/landscape/c1?meta=1")
        api.settle()
        _age(api, 3600)
    assert len(api.launched) == 2 and all("--inputs" not in cmd for cmd in api.launched)


def test_a_fresh_landscape_is_not_checked_at_all(api, monkeypatch):
    api.get("/api/landscape/c1?meta=1")
    api.settle()
    checked = []
    monkeypatch.setattr(landscape_inputs, "stamp", lambda _conn: checked.append(1) or "a" * 20)
    for _ in range(3):
        api.get("/api/landscape/c1?meta=1")
    api.settle()
    assert checked == [] and len(api.launched) == 1, "inside its TTL the landscape is served as it is"
