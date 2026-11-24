from __future__ import annotations

import ast
from pathlib import Path

import main as M

ROOT = Path(__file__).resolve().parents[2]
SIDE = ("telemetry", "maintenance", "proposer", "web")


class _Repo:
    def __init__(self):
        self.alerts = []

    def sync_operational_alerts(self, source, findings):
        self.alerts.append((source, [f["key"] for f in findings]))


def _crash_loop(record: dict, start: float = 100.0):
    return [M._service_crash_disposition(record, start + i) for i in range(6)]


def test_a_side_service_s_crash_loop_backs_off_and_is_alerted_until_it_starts_again():
    record = {"module": "graph_scale_dynamics.services.maintenance.main", "critical": False, "crashes": [],
              "proc": None}
    other = {"module": "graph_scale_dynamics.services.controller.main", "critical": True, "crashes": [], "proc": None}
    outcomes = _crash_loop(record)
    assert [kind for kind, _ in outcomes[:5]] == ["restart"] * 5
    assert outcomes[5] == ("backoff", 60.0), "never fatal: the fleet is not drained"
    repo = _Repo()
    M._back_off(repo, [other, record], record, 105.0 + 60.0)
    assert record["retry_at"] == 165.0
    assert repo.alerts == [("supervisor", ["crash_loop:graph_scale_dynamics.services.maintenance.main"])]
    M._back_off(repo, [other, record], record, None)
    assert record["retry_at"] is None and repo.alerts[-1] == ("supervisor", [])
    assert M._service_crash_disposition(record, 170.0)[0] == "restart", "a minute later its window is empty"


def test_the_fleet_s_own_services_still_fail_fast():
    record = {"module": "graph_scale_dynamics.services.executor.main", "critical": True, "crashes": []}
    assert _crash_loop(record)[5] == ("fatal", None)


def test_telemetry_maintenance_the_proposer_and_the_web_server_are_side_services():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    spawned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "spawn" and node.args:
            module = getattr(node.args[0], "value", "")
            critical = next((k.value.value for k in node.keywords if k.arg == "critical"), True)
            spawned[module.split(".")[-2]] = critical
    assert {name: spawned[name] for name in SIDE} == dict.fromkeys(SIDE, False)
    assert spawned["controller"] and spawned["executor"] and spawned["api"]
