from __future__ import annotations

import http.client
import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def test_serve_stops_the_postgresql_it_started(monkeypatch):
    sys.path.insert(0, str(ROOT))
    import main as M
    order, seen = [], {}
    monkeypatch.setattr(M, "postgres_running", lambda root: order.append("asked") or False)
    monkeypatch.setattr(M, "paths", lambda args: order.append("started") or ("db", Path("b"), Path("v")))
    monkeypatch.setattr(M, "live_fleet", lambda var: None)
    monkeypatch.setattr(M, "live_in_folder", lambda root, *names: None)

    class Record:
        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(M, "on_record", Record)
    monkeypatch.setattr(M, "_serve", lambda *a, **k: seen.update(k) or 0)
    monkeypatch.delenv("GSD_INTEGRATION_TEST", raising=False)
    assert M.cmd_serve(SimpleNamespace()) == 0
    assert order == ["asked", "started"]
    assert seen == {"owns_folder_runtime": True}


def test_the_browser_is_never_given_the_token(tmp_path):
    sys.path.insert(0, str(ROOT))
    import main as M
    (tmp_path / "run").mkdir(mode=0o700)
    url = M.browser_launcher(tmp_path, "http://127.0.0.1:8080/#admin=sekrit")
    page = tmp_path / "run" / "dashboard-open.html"
    assert url.startswith("file://") and "sekrit" not in url
    assert "sekrit" in page.read_text() and stat.S_IMODE(page.stat().st_mode) == 0o600


def test_the_folder_runtime_s_postgresql_is_seen_by_its_name():
    from graph_scale_dynamics.operations import leftovers
    argv = ["postgres", "-D", "/data/projects/GSD/257/main/instance/postgres/data"]
    assert leftovers._named(4242, "gsd-postgres", argv) == ("postgres", "/data/projects/GSD/257/main")
    assert "gsd-postgres" in leftovers.POSTGRES_NAMES


def test_the_backup_s_tools_are_the_folder_s_and_its_password_is_not_on_a_command_line(tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import backup
    monkeypatch.delenv(backup.SYSTEM_BIN_ENV, raising=False)
    tool = tmp_path / backup.FOLDER_BIN / "pg_dump"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    assert backup._command("pg_dump", root=tmp_path) == str(tool)
    target, env = backup._without_password("postgresql://gsd:sekrit@/gsd?host=/tmp/socket")
    assert "sekrit" not in target and env == {"PGPASSWORD": "sekrit"}
    assert backup._without_password("dbname=gsd host=/tmp/socket") == ("dbname=gsd host=/tmp/socket", {})


def test_a_study_bundle_link_carries_the_base_path_once(tmp_path):
    from graph_scale_dynamics.services.web import main as web
    root = tmp_path / "reports" / "live_campaign_1"
    root.mkdir(parents=True)
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.build_handler(
        api_host="127.0.0.1", api_port=9, bind_host="127.0.0.1", allowed_hosts=(), base_path="/research",
        report_root=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("GET", "/research/api/reports/study")
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert body["download_prefix"] == "/reports/study/bundles/"
    finally:
        server.shutdown()
        server.server_close()


def test_an_unpacked_bundle_is_removed_when_its_reader_ends(tmp_path):
    script = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import read_bundle; "
              "d = read_bundle.scratch_dir('gsd_bundle_'); (d / 'x').write_text('x'); print(d)") % (
        str(ROOT), str(ROOT / "tools"))
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True,
                         env=dict(os.environ, TMPDIR=str(tmp_path)))
    left = Path(out.stdout.strip())
    assert left.parent == tmp_path and not left.exists()


def test_a_long_run_s_rows_so_far_are_kept_when_it_fails(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    from partial_rows import kept_on_failure, partial_path
    rows = [{"n": 64}, {"n": 256}]
    where = partial_path(tmp_path / "screen.json", "growth_screen")
    with pytest.raises(KeyboardInterrupt):
        with kept_on_failure(rows, where):
            raise KeyboardInterrupt
    kept = json.loads(where.read_text())
    assert where.name == "screen.json.partial" and kept["complete"] is False and kept["rows"] == rows
