from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.services.api import campaign_manager as CM

UI = Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "ui"
node = shutil.which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)


class _Repo:
    def __init__(self):
        self.conn = SimpleNamespace(execute=self._execute)

    def _execute(self, sql, *_params):
        if "FROM analysis_queue" in sql and "status='queued'" in sql:
            rows = [{"campaign_id": "1", "c": 512}, {"campaign_id": "3", "c": 7}]
        elif "FROM analysis_queue" in sql and "status='leased'" in sql:
            rows = [{"campaign_id": "1", "c": 16}]
        else:
            rows = []
        return SimpleNamespace(fetchall=lambda: rows)

    def worker_allocation(self):
        return [{"campaign_id": "1", "leased": 0, "queued": 0}, {"campaign_id": "3", "leased": 2, "queued": 40}]


def test_every_campaign_s_analyses_are_read_queued_and_running():
    scan = CM._live_scan(_Repo())
    assert scan["analyses"] == {"1": 16}
    assert scan["analyses_queued"] == {"1": 512, "3": 7}


def _line(row: dict) -> str:
    app = (UI / "app.js").read_text(encoding="utf-8")
    start = app.index("function campaignAnalysesLine(row){")
    end = app.index("\n/*", start) if "\n/*" in app[start:start + 2000] else app.index("\nfunction ", start + 10)
    script = ("const esc=v=>String(v??'');\n" + app[start:end]
              + f"\nconsole.log(JSON.stringify(campaignAnalysesLine({json.dumps(row)})));")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(node is None, reason="node is not installed")
def test_the_row_shows_its_analyses_only_when_it_has_any():
    assert _line({"analyses_running": 0, "analyses_queued": 0}) == ""
    line = _line({"analyses_running": 16, "analyses_queued": 5009})
    assert "analyses 16 running" in line and "5,009 queued" in line
    assert "queued" not in _line({"analyses_running": 2, "analyses_queued": 0})
