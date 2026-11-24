from __future__ import annotations

import errno
import os
import time
from pathlib import Path

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES
from graph_scale_dynamics.observability import child_diagnostics as D
from graph_scale_dynamics.operations import scratch_relief as R
from graph_scale_dynamics.services.executor import main as executor
from graph_scale_dynamics.services.worker import main as worker
from tests.support.doubles import NullLog

NO_SPACE = OSError(errno.ENOSPC, "No space left on device")


def test_a_child_that_cannot_write_exits_with_its_own_code_wherever_the_write_failed():
    def fails_directly():
        raise OSError(errno.ENOSPC, "No space left on device")

    def fails_writing_its_receipt():
        try:
            raise OSError(errno.ENOSPC, "result")
        except OSError:
            raise OSError(errno.ENOSPC, "receipt")  # noqa: B904

    def fails_otherwise():
        raise ValueError("a real failure")

    assert D.exit_code_of(fails_directly) == D.NO_SPACE_EXIT_CODE
    assert D.exit_code_of(fails_writing_its_receipt) == D.NO_SPACE_EXIT_CODE
    assert D.exit_code_of(lambda: 0) == 0
    with pytest.raises(ValueError):
        D.exit_code_of(fails_otherwise)
    wrapped = RuntimeError("publication failed")
    wrapped.__cause__ = NO_SPACE
    assert D.is_no_space(wrapped) and not D.is_no_space(OSError(errno.EACCES, "denied"))


def test_the_parent_reads_the_code_as_no_space_and_never_counts_it_toward_a_stop(tmp_path):
    receipt = tmp_path / "receipt.json"
    D.write_terminal_receipt(receipt, status="failure", stage="staging_io", exc=NO_SPACE,
                             extra={"error_class": "staging_io:OSError", "retryable": True})
    diagnostics = D.process_diagnostics(returncode=D.NO_SPACE_EXIT_CODE, stdout_path=tmp_path / "out",
                                        stderr_path=tmp_path / "err", receipt_path=receipt)
    assert diagnostics["classification"] == D.NO_SPACE_CLASS, "the exit code wins over a receipt that got written"
    assert D.failure_class(diagnostics) == D.NO_SPACE_CLASS
    assert "no space left" in D.concise_failure(diagnostics)
    assert D.same_reason_exhausted([D.NO_SPACE_CLASS] * 9) is None, "a full filesystem never stops a job"
    assert D.same_reason_exhausted([D.NO_SPACE_CLASS, "no_result", D.NO_SPACE_CLASS, "no_result", "no_result"]) \
        == "no_result", "the job's own reasons still count"
    assert D.NO_SPACE_CLASS in INTERRUPTED_ATTEMPT_CLASSES, "its attempts are not runs in the timing statistics"


class _WorkerRepo:
    def __init__(self):
        self.released, self.closed = [], []

    def record_attempt(self, *args):
        pass

    def release_job(self, job_id, owner, generation, defer_seconds=None):
        self.released.append((job_id, owner, generation))
        return True

    def close_attempt(self, *args, error_class=None):
        self.closed.append((*args, error_class))


JOB = {"job_id": "job-full-scratch", "attempt_number": 1, "lease_generation": 7, "candidate_id": "candidate",
       "campaign_id": "campaign", "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
       "n": 8, "seed": 11}


def test_a_job_file_that_cannot_be_written_hands_the_job_back(monkeypatch, tmp_path):
    repo, blobs = _WorkerRepo(), BlobStore(tmp_path / "blobs")
    real = Path.write_text

    def full(self, *args, **kwargs):
        if self.name == "job.json":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full)
    spawned = []
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    with pytest.raises(OSError) as raised:
        worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    assert raised.value.errno == errno.ENOSPC and not spawned
    assert repo.released == [("job-full-scratch", "executor-1", 7)]
    assert repo.closed and repo.closed[-1][-1] == "supervisor_interrupted"
    assert not any(blobs.staging_root.iterdir()), "its staging directory is cleared"


def test_the_executor_waits_for_room_instead_of_crashing(monkeypatch, tmp_path):
    repo, blobs = _WorkerRepo(), BlobStore(tmp_path / "blobs")
    claims = []
    monkeypatch.setattr(executor.worker, "claim_simulation_for_owner",
                        lambda repo, owner: claims.append(owner) or dict(JOB))

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(executor.worker, "run_one", full)
    monkeypatch.setattr(executor, "scratch_room", lambda path, kind: (True, None))
    assert executor._run_simulation_once(repo, blobs, NullLog(), "executor-1") is False
    assert repo.released == [("job-full-scratch", "executor-1", 7)], "released again: a no-op once run_one has"

    monkeypatch.setattr(executor, "scratch_room", lambda path, kind: (False, "the RAM scratch has 0.0 GiB free"))
    claims.clear()
    assert executor._run_simulation_once(repo, blobs, NullLog(), "executor-1") is False
    assert claims == [], "no claim without room"
    assert executor._analysis_once(repo, blobs, NullLog(), "executor-1") is False


def test_the_claim_reserve_is_a_tenth_of_the_scratch_and_never_more_than_half_of_a_small_one(monkeypatch):
    gib = 1 << 30
    assert R.reserve_bytes(46 * gib, "simulation") == int(0.1 * 46 * gib)
    assert R.reserve_bytes(10 * gib, "simulation") == 2 * gib, "the floor"
    assert R.reserve_bytes(1 * gib, "simulation") == gib // 2, "a small scratch is not closed by the floor"
    assert R.reserve_bytes(46 * gib, "analysis") == R.ANALYSIS_RESERVE_BYTES
    R._ROOM.clear()
    monkeypatch.setattr(R, "usage", lambda path: {"total_bytes": 46 * gib, "used_bytes": 46 * gib,
                                                  "free_bytes": 0, "fraction": 1.0})
    fits, reason = R.room("/scratch-a", kind="simulation")
    assert not fits and "0.0 GiB free of 46.0 GiB" in reason
    monkeypatch.setattr(R, "usage", lambda path: {"total_bytes": 46 * gib, "used_bytes": 20 * gib,
                                                  "free_bytes": 26 * gib, "fraction": 20 / 46})
    assert R.room("/scratch-b", kind="simulation") == (True, None)
    monkeypatch.setattr(R, "usage", lambda path: None)
    assert R.room("/scratch-c", kind="analysis") == (True, None), "an unreadable scratch does not stop the fleet"


def test_logs_of_ended_processes_go_after_six_hours_and_nothing_else(tmp_path):
    old = time.time() - R.DEAD_LOG_KEEP_SECONDS - 60
    dead = 2 ** 22 + 12345
    names = {f"executor-9-{dead}.jsonl": old, f"executor-9-{dead}.jsonl.3": old,
             f"maintenance-{dead + 1}.jsonl": time.time(), f"executor-2-{os.getpid()}.jsonl": old,
             "controller.jsonl": old}
    for name, when in names.items():
        (tmp_path / name).write_text("x" * 100)
        os.utime(tmp_path / name, (when, when))
    result = R.prune_dead_logs(tmp_path)
    assert result["removed"] == 2
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == sorted(["controller.jsonl", f"executor-2-{os.getpid()}.jsonl", f"maintenance-{dead + 1}.jsonl"]), \
        "a live process's log, a recent one and one without a pid stay"


def test_the_relief_says_what_it_found_and_raises_the_alert_it_calls_for():
    gib = 1 << 30
    full = {"total_bytes": 46 * gib, "used_bytes": 46 * gib, "free_bytes": 0, "fraction": 1.0}
    pressed = {"total_bytes": 46 * gib, "used_bytes": 30 * gib, "free_bytes": 16 * gib, "fraction": 30 / 46}
    easy = {"total_bytes": 46 * gib, "used_bytes": 10 * gib, "free_bytes": 36 * gib, "fraction": 10 / 46}
    assert [f["key"] for f in R.findings({"usage": full})] == ["scratch:full"]
    assert [f["key"] for f in R.findings({"usage": full, "after": pressed})] == ["scratch:pressure"]
    assert R.findings({"after": easy}) == [] and R.findings({}) == []
    floor = {"free_bytes": 5 << 30, "keep_free_bytes": R.DISK_KEEP_FREE_BYTES}
    assert [f["key"] for f in R.findings({"after": easy, "disk_floor": floor})] == ["scratch:disk_floor"]
    assert [f["key"] for f in R.findings({"usage": full, "spilled": {"disk_floor": floor}})] == [
        "scratch:disk_floor", "scratch:full"]
    lines = R.render({"usage": full, "after": easy, "logs": {"removed": 3, "bytes": gib},
                      "spilled": {"moved": {"resume_checkpoint": {"items": 812, "bytes": 21 * gib},
                                            "raw_waiting": {"items": 90, "bytes": 15 * gib}}, "refused": {}}},
                     destination="/data/x/var/blobs")
    assert lines[0] == "scratch: 46.0 GiB of 46.0 GiB in use (100%)"
    assert "812 saved chain copies (21.0 GiB)" in lines[2] and "90 results waiting for analysis" in lines[2]
    assert lines[-1].startswith("scratch: now 10.0 GiB (22%)")
    assert R.render_breakdown({"parts": {"resume_checkpoint": 21 * gib, "logs": gib, "staging": 0}}) == \
        "scratch holds: saved chain copies 21.0 GiB, service logs 1.0 GiB"


def test_a_log_that_cannot_write_says_so_once_a_minute(monkeypatch, capsys, tmp_path):
    from graph_scale_dynamics.observability import log as L
    monkeypatch.setenv("GSD_RUNTIME_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("GSD_LOG_SYNCHRONOUS", "1")
    sink = L.Log(tmp_path, "executor-9-4112281")

    def full(batch):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(sink, "_write_batch", full)
    for index in range(50):
        sink.write("heartbeat", index=index)
    first = capsys.readouterr().err.strip().splitlines()
    assert first == ["warning: log write failed for executor-9-4112281: [Errno 28] No space left on device"]
    sink._warned_at -= L.WARNING_INTERVAL_SECONDS + 1
    sink.write("heartbeat", index=51)
    again = capsys.readouterr().err.strip().splitlines()
    assert len(again) == 1 and "(49 more since the last warning)" in again[0]


def test_the_relief_starts_past_the_high_mark_and_goes_on_to_the_low_one(monkeypatch, tmp_path):
    from types import SimpleNamespace
    gib = 1 << 30
    now = {"fraction": 0.5}
    calls = []

    def fake_usage(path):
        return {"total_bytes": 46 * gib, "used_bytes": int(now["fraction"] * 46 * gib),
                "free_bytes": int((1 - now["fraction"]) * 46 * gib), "fraction": now["fraction"]}

    def fake_spill(repo, store, *, target_fraction, budget_bytes, progress=None):
        calls.append(budget_bytes)
        now["fraction"] = max(target_fraction - 0.02, now["fraction"] - 0.1)
        return {"moved_bytes": gib, "after": fake_usage(None), "moved": {}, "refused": {}}

    monkeypatch.setattr(R, "usage", fake_usage)
    monkeypatch.setattr(R, "spill", fake_spill)
    monkeypatch.setattr(R, "prune_dead_logs", lambda path: {"removed": 0, "bytes": 0})
    store = SimpleNamespace(volatile_root=tmp_path, root=tmp_path)
    assert R.relieve(None, store)["spilled"] is None and not calls, "under the high mark nothing moves"
    now["fraction"] = 0.65
    first = R.relieve(None, store)
    assert calls == [R.TICK_BUDGET_BYTES] and first["relieving"], "past it, a tick's budget moves"
    second = R.relieve(None, store, relieving=first["relieving"])
    third = R.relieve(None, store, relieving=second["relieving"])
    assert len(calls) == 3 and second["relieving"] and not third["relieving"], \
        "and it goes on under the high mark until the low one"
    assert now["fraction"] < R.LOW_WATER
    assert R.relieve(None, store, relieving=third["relieving"])["spilled"] is None
    now["fraction"] = 0.55
    assert R.relieve(None, store)["spilled"] is None, "a scratch between the marks, not relieving, is left alone"
    now["fraction"] = 0.45
    R.relieve(None, store, at_start=True)
    assert calls[-1] is None, "a start moves to the low mark at once, with no budget"


def test_a_full_scratch_in_a_row_waits_longer_each_time_and_never_counts():
    full = D.NO_SPACE_CLASS
    assert worker.no_space_in_a_row(["oom_killed", full, full]) == 2
    assert worker.no_space_in_a_row([full, "oom_killed"]) == 0
    assert [worker.no_space_backoff_seconds(k) for k in (0, 1, 2, 3, 7, 20)] == [0.0, 60.0, 120.0, 240.0, 3600.0,
                                                                                3600.0]
    assert D.same_reason_exhausted([full] * 20) is None


class _FullAgainRepo:
    def __init__(self, before: int, wall: float = 60.0):
        self.before, self.finished, self.closed, self.events = before, [], [], []
        rows = [{"error_class": "oom_killed", "wall_seconds": 9e9}]
        rows += [{"error_class": D.NO_SPACE_CLASS, "wall_seconds": wall}] * before

        class _Conn:
            def execute(self, sql, args=()):
                assert "FROM attempts" in sql and args == (JOB["job_id"],)
                return type("Rows", (), {"fetchall": staticmethod(lambda: rows)})()

        self.conn = _Conn()

    def record_attempt(self, *args):
        pass

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id, "status": "active"}

    def job_failure_classes(self, job_id):
        return ["oom_killed"] + [D.NO_SPACE_CLASS] * self.before

    def finish_job(self, job_id, owner, generation, status, *, error=None, spent=True, defer_seconds=None):
        self.finished.append({"status": status, "error": error, "spent": spent, "defer": defer_seconds})
        return True

    def close_attempt(self, *args, error_class=None):
        self.closed.append(error_class)

    def emit(self, topic, payload):
        self.events.append((topic, payload))


class _FullChild:
    pid, returncode = os.getpid(), D.NO_SPACE_EXIT_CODE

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def test_a_job_that_fills_the_scratch_seven_times_in_a_row_stops_and_says_why(monkeypatch, tmp_path):
    from graph_scale_dynamics.operations.failure_repair import seed_is_the_fleets
    full = D.NO_SPACE_CLASS
    assert D.NO_SPACE_STOP == 7
    assert worker.no_space_backoff_seconds(D.NO_SPACE_STOP) == worker.NO_SPACE_BACKOFF_MAX_SECONDS
    assert not worker.no_space_stop([full] * 6, full) and worker.no_space_stop([full] * 7, full).startswith("7 full")
    assert not worker.no_space_stop([full] * 6 + ["oom_killed"], "oom_killed"), "only a full scratch is capped so"
    assert not worker.no_space_stop([full] * 3 + ["preempted_fleet_paused"] + [full] * 4, full), "in a row"
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: _FullChild())
    blobs = BlobStore(tmp_path / "blobs")
    sixth = _FullAgainRepo(before=5)
    worker.run_one(sixth, blobs, NullLog(), "executor-1", dict(JOB))
    assert sixth.finished == [{"status": "queued", "error": sixth.finished[0]["error"], "spent": False,
                               "defer": 1920.0}], "the sixth waits 32 minutes, unspent"
    seventh = _FullAgainRepo(before=6)
    worker.run_one(seventh, blobs, NullLog(), "executor-1", dict(JOB))
    (stopped,) = seventh.finished
    assert stopped["status"] == "failed" and stopped["defer"] is None
    assert f"[stopped: 7 {D.NO_SPACE_STOP_TEXT}; its output does not fit the scratch]" in stopped["error"]
    assert seventh.closed == [full] and seventh.events[0][1]["retry"] is False
    assert not seed_is_the_fleets("failed", stopped["error"], [full] * 7), "not given back at the next start"
    assert seed_is_the_fleets("failed", "no space", [full] * 7), "a full scratch the fleet's own still is"


def test_a_full_scratch_s_tries_are_bounded_by_what_they_cost_as_well(monkeypatch, tmp_path):
    full, day = D.NO_SPACE_CLASS, D.NO_SPACE_STOP_SECONDS
    assert day == 24 * 3600.0 and D.NO_SPACE_COST_FROM == 2 and D.NO_SPACE_STOP == 7, "the seven stays"
    assert not worker.no_space_stop([full], full, 108000.0), "one fill of a whole 1M window: tried again"
    assert not worker.no_space_stop([full] * 2, full, day - 1.0)
    cost = worker.no_space_stop([full] * 2, full, day)
    assert cost.startswith(f"2 {D.NO_SPACE_STOP_TEXT}") and "24 h bound" in cost
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: _FullChild())
    blobs = BlobStore(tmp_path / "blobs")
    deep = _FullAgainRepo(before=1, wall=108000.0)
    worker.run_one(deep, blobs, NullLog(), "executor-1", dict(JOB))
    (stopped,) = deep.finished
    assert stopped["status"] == "failed" and D.NO_SPACE_STOP_TEXT in stopped["error"]
    assert "h of tries" in stopped["error"]
    from graph_scale_dynamics.operations.failure_repair import seed_is_the_fleets
    assert not seed_is_the_fleets("failed", stopped["error"], [full] * 2), "and the next start leaves it stopped"
    cheap = _FullAgainRepo(before=1, wall=60.0)
    worker.run_one(cheap, blobs, NullLog(), "executor-1", dict(JOB))
    assert cheap.finished[0]["status"] == "queued", "two cheap fills wait and try again, as before"
