from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_every_decision_application_states_its_job_count():
    source = (ROOT / "graph_scale_dynamics/services/controller/main.py").read_text(encoding="utf-8")
    missing = [n.lineno for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
               and getattr(n.func, "id", "") == "_record_decision_application"
               and "jobs_created" not in {k.arg for k in n.keywords}]
    assert not missing, f"decision applications that do not say how many jobs they created: lines {missing}"
