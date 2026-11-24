from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from graph_scale_dynamics.services.api import admin_link
from graph_scale_dynamics.services.api import main as api_main

TOKEN = "this-run-s-token"
OLD = "an-earlier-run-s-token"
ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "graph_scale_dynamics" / "resources" / "ui"
NODE = shutil.which("node")


class _Repo:
    def __init__(self, _target=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def close(self):
        pass

    def get_flag(self, _key, default=""):
        return default


def _ask(port: int, method: str, path: str, token: str | None, body: dict | None = None):
    headers = {"Host": "127.0.0.1"}
    if token:
        headers["X-GSD-Admin-Token"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    response = conn.getresponse()
    answer = json.loads(response.read() or b"{}")
    conn.close()
    return response.status, answer


@pytest.fixture
def api(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api_main, "Repo", _Repo)
    said: list[str] = []
    monkeypatch.setattr(admin_link, "_said", said.append)
    handler = api_main.build_handler("unused", str(tmp_path / "blobs"), TOKEN, 0, snapshot_tmp=tmp_path / "tmp",
                                     calibration_root=tmp_path / "calibration", repository_root=tmp_path,
                                     internal_token="internal")
    server = api_main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], said
    server.shutdown()
    server.server_close()


def test_the_link_is_current_stale_or_none_and_only_the_current_one_is_admin():
    link = admin_link.AdminLink(TOKEN, say=lambda _line: None)
    assert [link.state(t) for t in (TOKEN, OLD, "")] == ["current", "stale", "none"]
    assert link.payload(TOKEN, loopback=True)["admin"] is True
    assert link.payload(TOKEN, loopback=False)["admin"] is False
    assert link.payload(OLD, loopback=True)["admin"] is False
    assert admin_link.AdminLink("", say=lambda _line: None).state(TOKEN) == "stale"


def test_refusals_are_counted_and_said_at_most_once_a_minute():
    said: list[str] = []
    now = [0.0]
    link = admin_link.AdminLink(TOKEN, say=said.append, clock=lambda: now[0], minted_utc="2026-11-24T14:00:00Z")
    link.refused(OLD, "/api/campaigns/manage")
    link.refused(OLD, "/api/campaigns/manage")
    link.refused("", "/api/pause")
    link.refused(TOKEN, "/api/pause")
    assert len(said) == 1 and "1 with an admin link that is not this run's" in said[0]
    assert "2026-11-24T14:00:00Z" in said[0] and OLD not in said[0]
    now[0] = admin_link.SAY_EVERY_SECONDS + 1
    link.refused(OLD, "/api/pause")
    assert len(said) == 2 and "refused 3 write(s)" in said[1] and "2 with an admin link" in said[1]
    assert link.payload("", loopback=True)["refused"] == {"stale": 3, "none": 1}


def test_an_accepted_write_is_said_without_the_token():
    said: list[str] = []
    admin_link.AdminLink(TOKEN, say=said.append).accepted("campaigns/manage", "fleet_workers")
    assert len(said) == 1 and "campaigns/manage fleet_workers accepted" in said[0] and TOKEN not in said[0]


def test_the_api_answers_which_link_a_page_holds(api):
    port, _said = api
    for token, state, admin in ((TOKEN, "current", True), (OLD, "stale", False), (None, "none", False)):
        status, answer = _ask(port, "GET", "/api/access", token)
        assert status == 200 and answer["link"] == state and answer["admin"] is admin, (token, answer)
        assert answer["local_admin"] is admin and answer["can_pause"] is admin
        assert TOKEN not in json.dumps(answer)


def test_an_earlier_run_s_link_is_refused_with_the_reason(api):
    port, said = api
    status, answer = _ask(port, "POST", "/api/campaigns/manage", OLD, {"action": "fleet_workers", "workers": 2})
    assert status == 403 and answer["error"] == "admin token required" and "not this run's" in answer["hint"]
    status, answer = _ask(port, "POST", "/api/pause", OLD, {"paused": True})
    assert status == 403 and "not this run's" in answer["hint"]
    status, answer = _ask(port, "POST", "/api/campaigns/manage", None, {"action": "fleet_workers", "workers": 2})
    assert status == 403 and "hint" not in answer
    assert any("refused" in line and "not this run's" in line for line in said)
    assert _ask(port, "GET", "/api/access", None)[1]["refused"] == {"stale": 2, "none": 1}


def _node(script: str):
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_top_bar_says_which_link_the_page_holds():
    system = (UI / "system.js").read_text(encoding="utf-8")
    body = system[system.index("  const ADMIN_SAYS"):system.index("  refreshAccess();\n")]
    script = """
const results = [];
const badge = {hidden: true, textContent: '', className: '', title: ''};
const document = {documentElement: {dataset: {}}, getElementById: id => id === 'gsdAdmin' ? badge : null};
const api = p => p, headers = () => ({});
let admin = '', answer = null;
const fetch = async () => { if (answer === 'down') throw new Error('down'); return answer };
""" + body + """
(async () => {
  for (const [token, reply] of [['t', {ok: true, json: async () => ({link: 'current'})}],
                                 ['t', {ok: true, json: async () => ({link: 'stale'})}],
                                 ['', {ok: true, json: async () => ({link: 'none'})}],
                                 ['t', 'down']]) {
    admin = token; answer = reply;
    await refreshAccess();
    results.push({admin: document.documentElement.dataset.admin, hidden: badge.hidden, text: badge.textContent,
                  cls: badge.className});
  }
  console.log(JSON.stringify(results));
})();
"""
    current, stale, none, down = _node(script)
    assert current == {"admin": "current", "hidden": False, "text": "admin", "cls": "gsd-admin-link ok"}
    assert stale["admin"] == "stale" and not stale["hidden"] and "earlier run" in stale["text"]
    assert stale["cls"] == "gsd-admin-link warn"
    assert none["admin"] == "none" and none["hidden"]
    assert down["admin"] == "none", "an unreachable API changes nothing the page last knew"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_worker_count_control_is_a_write_the_page_greys_without_this_run_s_link():
    app = (UI / "app.js").read_text(encoding="utf-8")
    body = app[app.index("let workerCountNote=''"):app.index("async function setWorkerCount(")]
    script = """
const host = {innerHTML: ''};
const document = {activeElement: null, getElementById: id => id === 'workerCount' ? host
  : {onclick: null, onkeydown: null}};
const esc = v => String(v ?? '');
""" + body + """
renderWorkerCount({fleet_workers: {most: 16, active_slots: 8, target: 4, reading: 'four asked'}});
console.log(JSON.stringify(host.innerHTML));
"""
    html = _node(script)
    for control in ("id=workerCountInput", "id=workerCountSet", "id=workerCountAuto"):
        tag = html[html.rindex("<", 0, html.index(control)):html.index(">", html.index(control))]
        assert "data-admin-write" in tag, (control, tag)
    css = (UI / "system.css").read_text(encoding="utf-8")
    assert 'html:not([data-admin="current"]) [data-admin-write]{opacity:.45;pointer-events:none}' in css
