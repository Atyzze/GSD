from __future__ import annotations

import sys
import time

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.observability.log import Log
from graph_scale_dynamics.services.analyzer import main as analyzer


class _Repo:
    def __init__(self):
        self.released = []
        self.closed = []
        self.conn = None

    def get_flag(self, key, default=None):
        return default

    def release_analysis_claim(self, *args, **kwargs):
        self.released.append(args)
        return True

    def close_analysis_attempt(self, attempt_id, **kwargs):
        self.closed.append(kwargs)

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_a_paused_campaigns_analysis_is_aborted_and_its_claim_returned(monkeypatch, tmp_path):
    asked = []

    def stop_reason(repo, campaign_id, now=None):
        asked.append(campaign_id)
        return "campaign paused; its chains have saved"

    real_popen = analyzer.subprocess.Popen
    monkeypatch.setattr(analyzer, "analysis_stop_reason", stop_reason)
    monkeypatch.setattr(analyzer, "TICK_SECONDS", 0.2)
    monkeypatch.setattr(analyzer, "hard_process_limit_bytes", lambda spec, **_: 1 << 50)
    monkeypatch.setattr(analyzer.subprocess, "Popen",
                        lambda args, **kw: real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw))
    repo = _Repo()
    job = {"result_artifact": "art-1", "analysis_claim_token": "claim-1", "campaign_id": "camp-6",
           "candidate_id": "law-1", "n": 16384, "seed": 0, "job_id": "job-1", "spec": {},
           "memory_reservation_bytes": 1}
    started = time.monotonic()
    committed = analyzer.run_analysis_job(repo, BlobStore(tmp_path / "blobs"), Log(tmp_path, "executor-1"),
                                          "executor-1", job)
    assert committed is False
    assert time.monotonic() - started < 10.0, "the pause waited for the probe"
    assert asked == ["camp-6"]
    assert len(repo.released) == 1, "the claim goes back to the queue, not to a failure"
    assert repo.closed and repo.closed[-1]["error_class"] == "preempted"
    assert "chains have saved" in repo.closed[-1]["error"]
