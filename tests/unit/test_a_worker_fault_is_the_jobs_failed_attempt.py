from __future__ import annotations

import errno
from pathlib import Path

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.services.worker import main as worker
from tests.support.doubles import NullLog

JOB = {"job_id": "job-fault", "attempt_number": 1, "lease_generation": 7, "candidate_id": "candidate",
       "campaign_id": "campaign", "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
       "n": 8, "seed": 11}


class _Repo:
    def __init__(self, prior: list[str], status: str = "active"):
        self.prior, self.status = prior, status
        self.released, self.finished, self.closed = [], [], []

    def record_attempt(self, *args):
        pass

    def release_job(self, job_id, owner, generation, defer_seconds=None):
        self.released.append(job_id)
        return True

    def finish_job(self, job_id, owner, generation, status, *, error=None, spent=True, defer_seconds=None):
        self.finished.append((status, spent, error))
        return True

    def job_failure_classes(self, job_id):
        return list(self.prior)

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id, "status": self.status}

    def close_attempt(self, *args, error_class=None):
        self.closed.append(error_class)


def _broken_job_file(monkeypatch, exc: BaseException):
    real = Path.write_text

    def write(self, *args, **kwargs):
        if self.name == "job.json":
            raise exc
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: pytest.fail("no child after the fault"))


@pytest.mark.parametrize(("prior", "status"), [([], "queued"), (["worker_fault"], "queued"),
                                                (["worker_fault", "worker_fault"], "failed")])
def test_a_worker_fault_spends_the_attempt_and_the_third_stops_the_job(monkeypatch, tmp_path, prior, status):
    repo, blobs = _Repo(prior), BlobStore(tmp_path / "blobs")
    _broken_job_file(monkeypatch, ValueError("a bug on the worker's own path"))
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert repo.released == [], "never handed back unspent"
    assert repo.finished and repo.finished[0][:2] == (status, True), repo.finished
    assert "ValueError" in repo.finished[0][2]
    assert repo.closed == [worker.ATTEMPT_CLASS_WORKER_FAULT]


def test_a_closed_campaign_s_faulted_job_is_cancelled(monkeypatch, tmp_path):
    repo, blobs = _Repo([], status="paused"), BlobStore(tmp_path / "blobs")
    _broken_job_file(monkeypatch, KeyError("missing"))
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert repo.finished[0][0] == "cancelled"


def test_the_fleet_s_own_interruptions_still_hand_the_job_back(monkeypatch, tmp_path):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    for i, exc in enumerate((OSError(errno.ENOSPC, "No space left on device"), OSError(errno.EAGAIN, "fork refused"),
                             ValueError("wrapped"),
                             DatabaseOperationalError("the database is away", transient=True))):
        if isinstance(exc, ValueError):
            exc.__cause__ = OSError(errno.ENOSPC, "No space left on device")
        repo, blobs = _Repo([]), BlobStore(tmp_path / f"blobs-{i}")
        _broken_job_file(monkeypatch, exc)
        with pytest.raises(type(exc)):
            worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
        assert repo.released == ["job-fault"] and repo.finished == []
        assert repo.closed == ["supervisor_interrupted"]
