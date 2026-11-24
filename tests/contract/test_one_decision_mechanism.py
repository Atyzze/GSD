from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIMITIVES = {"enqueue_simulation_rung", "terminalize_candidate", "set_candidate_state"}
ALLOWED = {
    "graph_scale_dynamics/db/decision_store.py::enqueue_seeds",
    "graph_scale_dynamics/db/decision_store.py::set_law_state",
    "graph_scale_dynamics/services/controller/engine_campaign.py::admit_proposed",
}


def test_only_the_engine_path_starts_continues_or_stops_a_law():
    callers = set()
    for path in sorted(list((ROOT / "graph_scale_dynamics").rglob("*.py")) + [ROOT / "main.py"]
                       + sorted((ROOT / "tools").glob("*.py"))):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        stack = [(ast.parse(path.read_text(encoding="utf-8")), "<module>")]
        while stack:
            node, owner = stack.pop()
            for child in ast.iter_child_nodes(node):
                name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
                if isinstance(child, ast.Call):
                    callee = getattr(child.func, "id", None) or getattr(child.func, "attr", None)
                    if callee in PRIMITIVES:
                        callers.add(f"{rel}::{owner}")
                stack.append((child, name))
    assert callers == ALLOWED, f"added: {sorted(callers - ALLOWED)}; removed: {sorted(ALLOWED - callers)}"


def test_the_controller_refuses_a_campaign_without_the_engine(monkeypatch, tmp_path):
    import json

    from graph_scale_dynamics.services.controller import main as controller
    engine = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    campaigns = [{"campaign_id": "1", "spec": {"name": "no engine"}}, {"campaign_id": "2", "spec": engine}]
    beats, ran = [], []

    class Repo:
        backend = "postgres"

        def __init__(self, db):
            pass

        def acquire_service_lock(self, name):
            return True

        def release_service_lock(self, name):
            pass

        def close(self):
            pass

        def get_flag(self, key, default=""):
            return default

        def active_campaigns(self):
            return campaigns

        def heartbeat(self, service, payload):
            beats.append(payload)

        def fleet_has_work(self, version):
            return False

    monkeypatch.setattr(controller, "Repo", Repo)
    monkeypatch.setattr(controller, "run_engine_campaign", lambda repo, log, campaign: ran.append(
        campaign["campaign_id"]) or {"admitted": 0, "decisions": 0})
    monkeypatch.setattr(controller, "_completion", lambda *args: None)
    assert controller.main(["--db", "unused", "--campaign", "2", "--var", str(tmp_path)]) == 0
    assert ran == ["2"] and beats[-1]["refused_campaigns"] == ["1"]
