from __future__ import annotations

import sys
import time

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.calibration import CalibrationGateError
from graph_scale_dynamics.calibration import table as CT
from graph_scale_dynamics.observability.log import Log


def test_the_gate_never_writes_a_stub_over_a_table_it_cannot_read(monkeypatch, tmp_path):
    from graph_scale_dynamics.services import calibration_gate as G
    torn = tmp_path / "probe_calibration.json"
    torn.write_text('{"cells": {"a": 1}, "torn')
    monkeypatch.setattr(G, "ensure_calibration", lambda *a, **k: {"path": str(torn)})
    with pytest.raises(CalibrationGateError, match="could not be read back"):
        G.ensure_probe_calibration(tmp_path, build_number=658, log=lambda *_: None, dev_mode=False, root=tmp_path)
    assert torn.read_text() == '{"cells": {"a": 1}, "torn'


def test_every_table_write_has_a_temp_file_of_its_own(monkeypatch, tmp_path):
    path = tmp_path / "probe_calibration.json"
    names = []
    real = type(path).replace

    def replace(self, target):
        names.append(self.name)
        return real(self, target)

    monkeypatch.setattr(type(path), "replace", replace)
    CT.write({"cells": {}}, path)
    CT.write({"cells": {"a": 1}}, path)
    assert len(set(names)) == 2 and all(name != "probe_calibration.tmp" for name in names), names
    assert sorted(p.name for p in tmp_path.iterdir()) == ["probe_calibration.json"], "no temp file left behind"


class _Alerts:
    def __init__(self):
        self.written, self.completed = [], []

    def sync_operational_alerts(self, source, findings):
        for finding in findings:
            self.written.append((finding["key"], finding["severity"], finding["category"], finding["message"]))

    def set_campaign_status(self, campaign_id, status):
        self.completed.append((campaign_id, status))

    def emit(self, *args):
        pass

    def get_flag(self, _key, default=""):
        return default


def test_a_campaign_is_checked_for_completion_and_no_calendar_stops_its_laws(monkeypatch):
    from graph_scale_dynamics.services.controller import main as C
    monkeypatch.setattr(C, "campaign_complete", lambda repo, campaign: True)
    repo = _Alerts()
    campaign = {"campaign_id": "7", "created_utc": "2000-01-01T00:00:00Z",
                "spec": {"mode": "bounded", "budgets": {"wall_seconds": 1000}}}
    C._completion(repo, _Log(), campaign)
    assert not repo.written, "however long it has run, no clock stops a law or raises an alert"
    assert repo.completed == [("7", "completed")], "and the completion check ran"


class _Log:
    def write(self, *args, **kwargs):
        pass


class _AnalysisRepo:
    def __init__(self):
        self.released, self.failed, self.closed = [], [], []
        self.conn = None

    def get_flag(self, key, default=None):
        return default

    def release_analysis_claim(self, *args, **kwargs):
        self.released.append(args)
        return True

    def fail_analysis_claim(self, *args, **kwargs):
        self.failed.append(kwargs)
        return {"status": "queued", "retry": True, "attempts": 1, "max_attempts": 8}

    def close_analysis_attempt(self, attempt_id, **kwargs):
        self.closed.append(kwargs)

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_a_fault_on_the_analyzer_s_path_is_the_claim_s_failed_attempt(monkeypatch, tmp_path):
    from graph_scale_dynamics.services.analyzer import main as analyzer

    def broken(repo, campaign_id, now=None):
        raise ValueError("a reading the supervisor cannot parse")

    real_popen = analyzer.subprocess.Popen
    monkeypatch.setattr(analyzer, "analysis_stop_reason", broken)
    monkeypatch.setattr(analyzer, "TICK_SECONDS", 0.2)
    monkeypatch.setattr(analyzer, "hard_process_limit_bytes", lambda spec, **_: 1 << 50)
    monkeypatch.setattr(analyzer.subprocess, "Popen",
                        lambda args, **kw: real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw))
    repo = _AnalysisRepo()
    job = {"result_artifact": "art-1", "analysis_claim_token": "claim-1", "campaign_id": "camp-6",
           "candidate_id": "law-1", "n": 16384, "seed": 0, "job_id": "job-1", "spec": {},
           "memory_reservation_bytes": 1}
    started = time.monotonic()
    committed = analyzer.run_analysis_job(repo, BlobStore(tmp_path / "blobs"), Log(tmp_path, "executor-1"),
                                          "executor-1", job)
    assert committed is False and time.monotonic() - started < 30.0, "returned, not raised to the executor"
    assert repo.failed and repo.failed[0]["error_class"] == analyzer.ANALYZER_FAULT and repo.failed[0]["retryable"]
    assert "ValueError: a reading the supervisor cannot parse" in repo.failed[0]["error"]
    assert repo.released == []
    assert repo.closed and repo.closed[0]["error_class"] == analyzer.ANALYZER_FAULT


def test_a_reopen_gives_back_what_the_close_cancelled(monkeypatch):
    from graph_scale_dynamics.operations import campaign_control as control

    class Repo:
        revived = []

        def campaign(self, cid):
            return {"campaign_id": cid, "status": "closed", "search_seed": 3, "spec": {"mode": "bounded"}}

        def revive_stopped_work(self, cid):
            self.revived.append(cid)
            return {"jobs": 4, "analyses": 1, "rebuilds": 0, "stopped_utc": "2026-10-29T00:00:00Z"}

        def __getattr__(self, name):
            return lambda *a, **k: None

    monkeypatch.setattr(control, "reopen_problems", lambda repo, cid: [])
    outcome = control.reopen(Repo(), "3")
    assert outcome["ok"] and Repo.revived == ["3"] and outcome["revived"]["jobs"] == 4
