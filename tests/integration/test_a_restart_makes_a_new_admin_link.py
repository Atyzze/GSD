from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tests.integration.slice_driver import rr

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.integration, pytest.mark.postgres]
UP_WITHIN_SECONDS = 600
DOWN_WITHIN_SECONDS = 300


def _free_pair() -> int:
    for _ in range(200):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port >= 65535:
            continue
        with socket.socket() as second:
            try:
                second.bind(("127.0.0.1", port + 1))
            except OSError:
                continue
        return port
    raise AssertionError("no two free ports side by side")


def _ask(port: int, method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["X-GSD-Admin-Token"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = conn.getresponse()
        raw = response.read()
    finally:
        conn.close()
    try:
        return response.status, json.loads(raw or b"{}")
    except ValueError:
        return response.status, {}


def _writes(port: int, token: str) -> int:
    return _ask(port, "POST", "/api/campaigns/manage", token, {"action": "no_such_action"})[0]


def _token(var: Path) -> str:
    return (var / "run" / "dashboard-admin").read_text(encoding="utf-8").strip().split("#admin=", 1)[1]


def _start(var: Path, schema: str, port: int) -> subprocess.Popen:
    env = dict(os.environ, GSD_INTEGRATION_TEST="1", GSD_TEST_SCHEMA=schema)
    log = (var / "fleet.log").open("ab")
    return subprocess.Popen([sys.executable, "main.py", "--var", str(var), "run", "--workers", "1", "--no-browser",
                             "--port", str(port), "--bind", "127.0.0.1", "--no-power-telemetry"],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)


def _up(var: Path, fleet: subprocess.Popen, port: int, before: set[str]) -> str:
    deadline = time.monotonic() + UP_WITHIN_SECONDS
    while time.monotonic() < deadline:
        assert fleet.poll() is None, (var / "fleet.log").read_text(errors="replace")[-3000:]
        try:
            token = _token(var)
            if token not in before and _writes(port, token) not in (502, 503, 504):
                return token
        except (OSError, IndexError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise AssertionError("the dashboard never came up: " + (var / "fleet.log").read_text(errors="replace")[-3000:])


def _stopped(fleet: subprocess.Popen, how: int, port: int) -> None:
    fleet.send_signal(how)
    fleet.wait(timeout=DOWN_WITHIN_SECONDS)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            _writes(port, "")
        except OSError:
            return
        time.sleep(0.5)
    raise AssertionError(f"something still answers on {port} after the fleet stopped")


def test_every_start_makes_a_new_admin_link_and_the_old_one_stops_working(isolated_postgres_schema):
    var = ROOT / f".pytest_admin_link_var_{uuid.uuid4().hex[:8]}"
    schema = isolated_postgres_schema.schema
    database = f"folder-schema:{schema}"
    port = _free_pair()
    fleet = None
    try:
        assert rr("init", var=var, database=database).returncode == 0
        spec_path = var / "custom.json"
        spec_path.write_text((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
        started = rr("campaign", "start", "--spec", str(spec_path), "--allow-unvalidated-analyzer",
                     "--reason", "admin link test", var=var, database=database)
        assert started.returncode == 0, started.stdout[-2000:]
        campaign = re.search(r"^Campaign (\S+) created", started.stdout, re.MULTILINE).group(1)
        assert rr("campaign", "use", campaign, var=var, database=database).returncode == 0

        seen: set[str] = set()
        for stop in (signal.SIGINT, signal.SIGKILL, None):
            fleet = _start(var, schema, port)
            token = _up(var, fleet, port, seen)
            assert _writes(port, token) == 400
            assert _ask(port, "GET", "/api/access", token)[1]["link"] == "current"
            for old in seen:
                status, answer = _ask(port, "POST", "/api/campaigns/manage", old, {"action": "no_such_action"})
                assert status == 403 and "not this run's" in answer.get("hint", ""), (status, answer)
                assert _ask(port, "GET", "/api/access", old)[1]["link"] == "stale"
            assert _writes(port, "") == 403
            seen.add(token)
            if stop is not None:
                _stopped(fleet, stop, port)
        assert len(seen) == 3
        _stopped(fleet, signal.SIGINT, port)
        fleet = None
    finally:
        if fleet is not None and fleet.poll() is None:
            fleet.kill()
            fleet.wait(timeout=60)
        shutil.rmtree(var, ignore_errors=True)
