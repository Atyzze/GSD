from __future__ import annotations

import json
from pathlib import Path

from graph_scale_dynamics.observability import live_panel as L

ROOT = Path(__file__).resolve().parents[2]


def test_a_note_saved_before_the_attempt_is_the_time_before_it():
    note = {"seconds_spent": 18000.0, "saved_utc": "2026-11-15T12:00:00Z", "chunks": 4}
    assert L.spent_before(note, "2026-11-15T12:30:00Z") == 18000.0


def test_a_note_the_running_attempt_saved_takes_its_own_time_off():
    note = {"seconds_spent": 18600.0, "saved_utc": "2026-11-15T12:40:00Z", "chunks": 5}
    assert L.spent_before(note, "2026-11-15T12:30:00Z") == 18000.0


def test_no_note_or_nothing_spent_is_no_resume():
    assert L.spent_before(None, "2026-11-15T12:30:00Z") is None
    assert L.spent_before({"seconds_spent": 0.0, "saved_utc": "2026-11-15T12:00:00Z"}, None) is None


def test_the_live_row_counts_the_time_before_and_the_page_shows_it(monkeypatch, tmp_path):
    from graph_scale_dynamics.artifact_store import resume_state as R
    monkeypatch.setattr(L, "RESUME_ROOT", tmp_path)
    monkeypatch.setattr(L, "_resume_root", lambda root: Path(root))
    path = R.resume_path(tmp_path, "job-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    R.resume_note_path(path).write_text(json.dumps({"seconds_spent": 600.0, "chunks": 2, "in_chunk": True,
                                                    "saved_utc": "2026-11-15T12:00:00Z"}))
    row = L.lane_and_budget({"job_id": "job-1", "n": 262144, "started_utc": "2026-11-15T12:05:00Z", "spec": {}},
                            {64, 256, 1024, 4096})
    assert row["resumed_seconds"] == 600.0 and row["resumed_chunks"] == 2
    from datetime import datetime, timedelta, timezone

    from graph_scale_dynamics.services.api.overview import _running_row
    started = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    shown = _running_row({"n": 262144, "seed": 0, "sealed": False, "lease_owner": "w", "started_utc": started,
                          "spec_json": "{}"}, {"resumed_seconds": 600.0}, {}, {}, [], {})
    assert 29 <= shown["since_s"] <= 40 and shown["elapsed_s"] == round(shown["since_s"] + 600.0, 1), (
        "the typical multiple and the time left count the time before the resume")
    page = _page_elapsed([{"kind": "graph", "job": {"since_s": 30, "resumed_seconds": 600}},
                          {"kind": "probe", "job": {"since_s": 30, "resumed_seconds": 600}},
                          {"kind": "graph", "job": {"since_s": 30}}], now=12_000, payload_at=10_000)
    assert page == [632, 32, 32], "the page counts a resumed seed's time before, and a probe's never"


def _page_elapsed(leases: list, *, now: int, payload_at: int) -> list:
    import shutil
    import subprocess
    app = (ROOT / "graph_scale_dynamics" / "resources" / "ui" / "app.js").read_text(encoding="utf-8")
    start, end = app.index("function liveResumed(lease){"), app.index("function liveElapsedHtml(lease){")
    script = app[start:end] + f"console.log(JSON.stringify({json.dumps(leases)}.map(l => "
    script += f"liveElapsedSeconds(l, {now}, {payload_at}))));"
    node = shutil.which("node")
    assert node, "node runs the page's own code here, as the dashboard's checks do"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)
