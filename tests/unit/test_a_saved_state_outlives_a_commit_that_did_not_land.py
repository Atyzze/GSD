from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_scale_dynamics.artifact_store import resume_state as R
from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.db.connection import DatabaseOperationalError
from graph_scale_dynamics.scaleflow.one_shot import RESUME_CONTRACT
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.services.worker import main as worker
from tests.support.doubles import NullLog

ROOT = Path(__file__).resolve().parents[2]
STATE = {"contract": RESUME_CONTRACT, "checkpoint": {"n": 64}, "multiplier": 2, "consecutive": 1,
         "history": [{"multiplier": 1}], "seconds_spent": 30.0, "attempts": 1}
JOB = {"job_id": "a" * 64, "attempt_number": 1, "lease_generation": 7, "candidate_id": "candidate",
       "campaign_id": "campaign", "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
       "n": 8, "seed": 11}
MANIFEST = {"artifact_manifest_contract": "simulation-artifact-manifest-v1", "raw_digest": "r" * 64, "raw_size": 10,
            "compact_digest": "c" * 64, "compact_size": 5, "checkpoint_digest": "k" * 64, "checkpoint_size": 7}


def _away():
    return DatabaseOperationalError("PostgreSQL operation failed [57P01]: terminating connection", transient=True,
                                    sqlstate="57P01")


def test_the_child_keeps_its_state_after_it_publishes(tmp_path, monkeypatch):
    from graph_scale_dynamics.domain.version import ROOT as PKG_ROOT, environment_fingerprint, source_fingerprint
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.services.worker import child

    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    job_id = "f" * 64
    job = {"job_id": job_id, "candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION, "publish_blob_root": str(tmp_path),
           "resume_root": str(tmp_path / "ram"), "disk_resume_root": str(tmp_path),
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": one_shot_policy(campaign)}}
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    monkeypatch.setattr(child, "publish_envelope_artifacts", lambda *a, **k: {"artifacts": {}})
    ram, disk = R.resume_path(tmp_path / "ram", job_id), R.resume_path(tmp_path, job_id)
    seen: dict = {}

    def run_child():
        job_file, out_file = tmp_path / "job.json", tmp_path / "out.json"
        job_file.write_text(json.dumps(job))
        out_file.unlink(missing_ok=True)
        assert child._run([str(job_file), str(out_file)]) == 0 and out_file.is_file(), "the child published"

    def saves_then_completes(*_args, **kwargs):
        kwargs["on_chunk"](dict(STATE))
        return {"rung_terminal": {"reason": "completed"}}

    def completes_at_once(*_args, **kwargs):
        seen.update(kwargs)
        return {"rung_terminal": {"reason": "completed"}}

    monkeypatch.setattr(child, "run_one_shot", saves_then_completes)
    run_child()
    assert ram.is_file() and R.resume_note_path(ram).is_file(), "the state waits for the worker's commit"
    disk.parent.mkdir(parents=True, exist_ok=True)
    ram.replace(disk)
    R.resume_note_path(ram).replace(R.resume_note_path(disk))
    monkeypatch.setattr(child, "run_one_shot", completes_at_once)
    run_child()
    assert seen["resume"]["multiplier"] == 2, "the disk copy was resumed"
    assert disk.is_file(), "the disk copy a rung resumed from also waits for the commit"


class _Child:
    def __init__(self, args):
        job_file, out_file, receipt = (Path(a) for a in args[-3:])
        out_file.write_text(json.dumps(MANIFEST))
        receipt.write_text(json.dumps({"status": "success", "stage": "simulation_child"}))
        self.pid, self.returncode = os.getpid(), 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


class _Repo:
    backend = "postgresql"

    def __init__(self, commit, *, durable_fails: bool = False):
        self.commit, self.durable_fails = commit, durable_fails
        self.events, self.durable, self.closed, self.released = [], 0, [], []
        self.conn = SimpleNamespace(rollback_if_open=lambda: False)

    def record_attempt(self, *args):
        pass

    def commit_job_result(self, **_kwargs):
        if isinstance(self.commit, BaseException):
            raise self.commit
        return self.commit

    def renew_lease(self, *args, **kwargs):
        return True

    def begin_transaction(self, attempts: int = 8):
        if self.durable_fails:
            raise _away()

    def emit(self, topic, payload):
        self.events.append(topic)

    def commit_durably(self):
        self.durable += 1

    def release_job(self, *args, **kwargs):
        self.released.append(args[0])
        return True

    def close_attempt(self, *args, error_class=None, **kwargs):
        self.closed.append(error_class)


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setattr(worker.subprocess, "Popen", lambda args, **kwargs: _Child(args))
    monkeypatch.setenv("GSD_RESULT_COMMIT_WAIT_SECONDS", "0.3")
    blobs = BlobStore(tmp_path / "blobs")
    ram, disk = R.resume_path(blobs.volatile_root, JOB["job_id"]), R.resume_path(blobs.root, JOB["job_id"])
    R.save_resume_state(ram, STATE, execution_spec_hash="h")
    R.save_resume_state(disk, STATE, execution_spec_hash="h")
    yield blobs, ram, disk
    for path in (ram, disk):
        R.discard_resume_state(path)


def _kept(ram: Path, disk: Path) -> bool:
    return ram.is_file() and disk.is_file()


def test_a_commit_the_lease_no_longer_allows_keeps_the_state_for_the_next_holder(saved):
    blobs, ram, disk = saved
    repo = _Repo(False)
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert repo.closed == [worker.ATTEMPT_CLASS_LEASE_LOST] and repo.events == []
    assert _kept(ram, disk), "a fenced commit leaves the chain for the attempt that holds the job now"


def test_a_database_away_past_the_commit_wait_keeps_the_state_for_the_retry(saved):
    blobs, ram, disk = saved
    repo = _Repo(_away())
    started = time.monotonic()
    with pytest.raises(DatabaseOperationalError, match="could not be published"):
        worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert time.monotonic() - started < 30
    assert repo.released == [JOB["job_id"]] and repo.closed == [worker.ATTEMPT_CLASS_SUPERVISOR_INTERRUPTED]
    assert _kept(ram, disk), "the requeued job resumes where its chain stood, not from zero"


def test_a_commit_that_landed_but_was_not_yet_made_durable_keeps_the_state(saved):
    blobs, ram, disk = saved
    repo = _Repo(True, durable_fails=True)
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert repo.durable == 0 and _kept(ram, disk), "the prune lets it go once the job is done and the file old"


def test_a_committed_job_s_state_and_its_disk_copy_go_once_the_commit_is_on_disk(saved):
    blobs, ram, disk = saved
    repo = _Repo(True)
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert repo.events == ["job_done"] and repo.durable == 1
    assert not ram.exists() and not disk.exists()
    assert not R.resume_note_path(ram).exists() and not R.resume_note_path(disk).exists()


def test_the_prune_still_collects_a_done_job_s_state_and_keeps_a_queued_one(tmp_path):
    done, queued = "d" * 64, "q" * 64
    for job_id in (done, queued):
        R.save_resume_state(R.resume_path(tmp_path, job_id), STATE, execution_spec_hash="h")
    conn = SimpleNamespace(execute=lambda _sql, params: SimpleNamespace(
        fetchall=lambda: [{"job_id": queued}] if queued in params else []))
    pruned = R.prune_resume_states(conn, tmp_path, now=time.time() + R.RESUME_PRUNE_MIN_AGE_SECONDS + 1)
    assert pruned["removed"] == 1
    assert not R.resume_path(tmp_path, done).exists() and R.resume_path(tmp_path, queued).exists()
