from __future__ import annotations

import os
from pathlib import Path

import pytest

from graph_scale_dynamics.artifact_store.blobstore import BlobStore
from graph_scale_dynamics.artifact_store.resume_state import STOP_FILE_NAME
from graph_scale_dynamics.db.repo import FENCE_OUTRANKS
from graph_scale_dynamics.observability import oom_evidence as O
from graph_scale_dynamics.services.worker import main as worker
from tests.support.doubles import NullLog

JOB = {"job_id": "job-oom", "attempt_number": 1, "lease_generation": 7, "candidate_id": "candidate",
       "campaign_id": "campaign", "spec": {"candidate_spec": {}, "engine_version": "engine", "execution": {}},
       "n": 8, "seed": 11, "memory_reservation_bytes": 1 << 30}


class _Repo:
    def __init__(self, paused: bool = True):
        self.paused, self.closed, self.released = paused, [], []
        self.conn = None

    def record_attempt(self, *args):
        pass

    def get_flag(self, key, default=None):
        return "1" if (key == "paused" and self.paused) else default

    def preempt_reason(self, job):
        return None

    def release_job(self, *args, **kwargs):
        self.released.append(args)
        return False

    def close_attempt(self, attempt_id, code, peak, wall, error, resource, error_class=None):
        self.closed.append({"code": code, "error_class": error_class, "resource": resource})

    def emit(self, *args):
        pass


class _SavingChild:
    def __init__(self, staging: Path, outcome: int, on_end=None):
        self.pid, self.returncode, self.staging, self.outcome, self.on_end = os.getpid(), None, staging, outcome, on_end

    def poll(self):
        if self.returncode is None and (self.staging / STOP_FILE_NAME).exists():
            self.returncode = self.outcome
            if self.on_end:
                self.on_end()
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def host(monkeypatch, tmp_path):
    vmstat, events = tmp_path / "vmstat", tmp_path / "memory.events"
    vmstat.write_text("nr_free_pages 10\noom_kill 3\n")
    events.write_text("low 0\nhigh 0\nmax 2\noom 1\noom_kill 1\n")
    monkeypatch.setattr(O, "VMSTAT", vmstat)
    monkeypatch.setattr(O, "_cgroup_events", lambda pid: events)
    monkeypatch.setattr(O, "kernel_record", lambda pid, since_usec=None: None)
    monkeypatch.setattr(worker, "lane_yield_reason", lambda repo, job: None)
    monkeypatch.setattr(worker, "memory_shed_reason", lambda *a, **k: None)

    def oom_kill():
        cgroup = int(events.read_text().split("oom_kill ")[1]) + 1
        host_ = int(vmstat.read_text().split("oom_kill ")[1]) + 1
        vmstat.write_text(f"nr_free_pages 10\noom_kill {host_}\n")
        events.write_text(f"low 0\nhigh 0\nmax 3\noom 2\noom_kill {cgroup}\n")

    return oom_kill


def _run(monkeypatch, tmp_path, repo, outcome, on_end, **kwargs):
    blobs = BlobStore(tmp_path / "blobs")
    made = []

    def popen(args, **kw):
        made.append(_SavingChild(Path(args[-3]).parent, outcome, on_end))
        return made[-1]

    monkeypatch.setattr(worker.subprocess, "Popen", popen)
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB), **kwargs)
    (closed,) = repo.closed
    return closed


def _names_the_child(monkeypatch):
    def record(pid, since_usec=None):
        assert since_usec is not None, "a record is read only from the child's start"
        return f"Out of memory: Killed process {pid} (python3)" if pid == os.getpid() else None
    monkeypatch.setattr(O, "kernel_record", record)


def test_a_child_the_kernel_names_as_killed_for_memory_while_a_pause_stopped_it_is_an_oom(host, monkeypatch,
                                                                                          tmp_path):
    _names_the_child(monkeypatch)
    closed = _run(monkeypatch, tmp_path, _Repo(), -9, host)
    assert closed["error_class"] == O.OOM_CLASS and O.OOM_CLASS not in FENCE_OUTRANKS, (
        "an OOM, which the pause's label does not outrank")
    evidence = closed["resource"]["oom_evidence"]
    assert evidence["oom"] and evidence["decided_by"] == "kernel record"
    assert evidence["kernel_record"].startswith(f"Out of memory: Killed process {os.getpid()}")


def test_its_own_cgroup_s_counter_decides_and_during_a_shutdown_s_save_too(host, monkeypatch, tmp_path):
    monkeypatch.setattr(O, "_own_cgroup", lambda pid, events: True)
    closed = _run(monkeypatch, tmp_path, _Repo(paused=False), -9, host, stop_requested=lambda: True)
    assert closed["error_class"] == O.OOM_CLASS
    assert closed["resource"]["oom_evidence"]["decided_by"] == "its own cgroup's counter"


def test_an_oom_elsewhere_does_not_make_an_externally_killed_child_an_oom(host, monkeypatch, tmp_path):
    killed = _run(monkeypatch, tmp_path, _Repo(), -9, host)
    assert killed["error_class"] == worker.pause_attempt_class("fleet stopped") in FENCE_OUTRANKS
    evidence = killed["resource"]["oom_evidence"]
    assert evidence["oom"] is False and evidence["counters_rose"] == {"cgroup": 1, "host": 1}
    assert evidence["own_cgroup"] is False and evidence["decided_by"] == "none"
    saved = _run(monkeypatch, tmp_path, _Repo(), 75, host)
    assert saved["error_class"] == worker.pause_attempt_class("fleet stopped")
    assert "oom_evidence" not in saved["resource"], "a chain that saved is an interruption with nothing to read"


def test_a_rise_before_the_child_was_last_seen_alive_is_not_its_own(host, monkeypatch, tmp_path):
    monkeypatch.setattr(O, "_own_cgroup", lambda pid, events: True)
    blobs = BlobStore(tmp_path / "blobs")

    class _Survives(_SavingChild):
        polls = 0

        def poll(self):
            _Survives.polls += 1
            if _Survives.polls == 1:
                host()
            return super().poll()

    monkeypatch.setattr(worker.subprocess, "Popen", lambda args, **kw: _Survives(Path(args[-3]).parent, -9, None))
    repo = _Repo()
    worker.run_one(repo, blobs, NullLog(), "executor-1", dict(JOB))
    (closed,) = repo.closed
    assert closed["error_class"] == worker.pause_attempt_class("fleet stopped")
    assert closed["resource"]["oom_evidence"]["counters_rose"] == {}


def test_the_peak_decides_only_where_the_counters_do_not_say_no_oom_happened():
    before = {"cgroup_events": None, "cgroup": None, "host": None}
    assert O.judge(before, pid=None, returncode=-9, ended_on_its_own=False) is None, "the worker's own kill"
    assert O.judge(before, pid=None, returncode=-15, ended_on_its_own=True) is None, "not a SIGKILL"
    over = dict(pid=None, returncode=-9, ended_on_its_own=True, peak_rss_bytes=3 << 30, reservation_bytes=2 << 30)
    unreadable = O.judge(before, **over)
    assert unreadable["oom"] and unreadable["decided_by"] == "peak over reservation"
    within = O.judge(before, **dict(over, peak_rss_bytes=1 << 30))
    assert not within["oom"]
    assert O.attempt_class("preempted_fleet_paused", within) == "preempted_fleet_paused"
    assert O.attempt_class("preempted_fleet_paused", unreadable) == O.OOM_CLASS


def test_the_peak_with_counters_still_is_not_an_oom_and_with_a_rise_is(monkeypatch, tmp_path):
    vmstat = tmp_path / "vmstat"
    vmstat.write_text("oom_kill 5\n")
    monkeypatch.setattr(O, "VMSTAT", vmstat)
    monkeypatch.setattr(O, "kernel_record", lambda pid, since_usec=None: None)
    before = {"cgroup_events": None, "cgroup": None, "host": 5, "started_usec": 1}
    over = dict(pid=1, returncode=-9, ended_on_its_own=True, peak_rss_bytes=3 << 30, reservation_bytes=2 << 30)
    assert not O.judge(dict(before), **over)["oom"], "no OOM kill anywhere while it ran: not an OOM"
    vmstat.write_text("oom_kill 6\n")
    assert O.judge(dict(before), **over)["decided_by"] == "peak over reservation"


def test_the_kernel_s_record_names_the_child_and_only_since_it_started(monkeypatch):
    lines = [b"3,1,10,-;Out of memory: Killed process 4242 (python3) total-vm:1kB\n",
             b"6,2,15,-;systemd: started\n",
             b"3,3,20,-;oom-kill:constraint=CONSTRAINT_NONE,task=python3,pid=4242,uid=1000\n"]
    reads = iter(())

    def read(fd, size):
        try:
            return next(reads)
        except StopIteration:
            raise BlockingIOError from None

    monkeypatch.setattr(O.os, "open", lambda path, flags: 99)
    monkeypatch.setattr(O.os, "read", read)
    monkeypatch.setattr(O.os, "close", lambda fd: None)
    reads = iter(lines)
    assert O.kernel_record(4242, since_usec=0).startswith("oom-kill:constraint")
    reads = iter(lines)
    assert O.kernel_record(4242, since_usec=16).startswith("oom-kill:constraint"), "the record after its start"
    reads = iter(lines[:2])
    assert O.kernel_record(4242, since_usec=16) is None, "a record before it started names another with its pid"
    reads = iter(lines)
    assert O.kernel_record(4243, since_usec=0) is None
