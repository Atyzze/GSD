from __future__ import annotations

import pytest

from graph_scale_dynamics.domain.cadence import idle_backoff, ticks
from graph_scale_dynamics.operations import artifact_retention
from graph_scale_dynamics.services.controller import main as controller


def test_idle_backoff_doubles_to_its_ceiling_and_work_resets_it():
    rest, seen = 0.5, []
    for _ in range(7):
        rest = idle_backoff(rest, False, floor=0.5, ceiling=ticks(4))
        seen.append(rest)
    assert seen == [1.0, 2.0, 4.0, 8.0, 16.0, 16.0, 16.0]
    assert idle_backoff(rest, True, floor=0.5, ceiling=ticks(4)) == 0.5
    assert idle_backoff(0.01, False, floor=1.0, ceiling=8.0) == 1.0


class _FakeRepo:
    backend = "fake"

    def __init__(self, passes_before_exit: int):
        self.waits: list[float] = []
        self.heartbeats: list[dict] = []
        self._remaining = passes_before_exit

    def acquire_service_lock(self, name):
        return True

    def release_service_lock(self, name):
        pass

    def close(self):
        pass

    def get_flag(self, key, default=None):
        return default

    def active_campaigns(self):
        return [{"campaign_id": "c1", "spec": {}}]

    def heartbeat(self, service, payload):
        self.heartbeats.append(payload)

    def fleet_has_work(self, version):
        self._remaining -= 1
        return self._remaining > 0

    def wait_for_work(self, timeout, relevant=None):
        self.waits.append(float(timeout))
        return False


def _run(monkeypatch, tmp_path, results):
    passes = iter(results)
    repo = _FakeRepo(len(results))
    monkeypatch.setattr(controller, "Repo", lambda dsn: repo)
    monkeypatch.setattr(controller, "is_engine_campaign", lambda spec: True)
    monkeypatch.setattr(controller, "run_engine_campaign", lambda repo, log, campaign: next(passes))
    monkeypatch.setattr(controller, "_completion", lambda *a, **k: None)
    assert controller.main(["--db", "fake", "--campaign", "c1", "--var", str(tmp_path)]) == 0
    return repo


IDLE = {"admitted": 0, "decisions": {}}
BUSY = {"admitted": 0, "decisions": {"run_next:rung_complete": 1}}


def _backoff(results):
    floor, ceiling = FLOOR, controller.IDLE_REST_CEILING_SECONDS
    rest, out = floor, []
    for result in results[:-1]:
        worked = bool(result["admitted"]) or bool(result["decisions"])
        rest = floor if worked else min(ceiling, max(floor, rest * 2))
        out.append(rest)
    return out


FLOOR = ticks(1)


def test_the_controller_rests_longer_while_its_passes_decide_nothing(monkeypatch, tmp_path):
    results = [IDLE] * 7 + [BUSY, IDLE, IDLE]
    repo = _run(monkeypatch, tmp_path, results)
    assert repo.waits == _backoff(results)
    assert repo.waits[0] > FLOOR and max(repo.waits) == controller.IDLE_REST_CEILING_SECONDS
    assert repo.waits[7] == FLOOR, "a pass that decided something puts the rest back at the floor"
    assert [beat["rest_seconds"] for beat in repo.heartbeats][:3] == repo.waits[:3]
    assert all("pass_seconds" in beat for beat in repo.heartbeats), (
        "the heartbeat says how long a pass took, so the next measurement can read it")


def test_an_admission_counts_as_work(monkeypatch, tmp_path):
    results = [IDLE, IDLE, {"admitted": 2, "decisions": {}}, IDLE]
    repo = _run(monkeypatch, tmp_path, results)
    assert repo.waits == _backoff(results) and repo.waits[-1] == FLOOR


def test_the_heartbeat_says_why_the_rest_did_not_hold(monkeypatch, tmp_path):
    repo = _run(monkeypatch, tmp_path, [IDLE, BUSY, IDLE, IDLE])
    last = repo.heartbeats[-1]
    assert last["passes_total"] == 4 and last["passes_idle"] == 3
    assert last["wakes"] == {"notified": 0, "rest_ran_out": 3}
    assert last["last_working_pass"]["passes"] == {"c1": BUSY}


@pytest.mark.parametrize("sweep", [True, False])
def test_the_retention_tick_runs_the_checkpoint_sweep_only_when_asked(monkeypatch, sweep):
    calls = []

    def fake_checkpoints(repo, store, *, limit):
        calls.append(limit)
        return {"checkpoint_bodies_evicted": 0, "bytes_released": 0}

    monkeypatch.setattr(artifact_retention, "_raw_rows", lambda *a, **k: [])
    monkeypatch.setattr(artifact_retention, "_evict_completed_transient_rows", lambda *a, **k: {"evicted": 0})
    monkeypatch.setattr(artifact_retention, "evict_stale_checkpoints", fake_checkpoints)
    monkeypatch.setattr(artifact_retention, "cleanup_evicted_files", lambda *a, **k: {"evicted_files_cleaned": 0})
    monkeypatch.setattr(artifact_retention, "cleanup_transient_files", lambda *a, **k: {"removed": 0})
    result = artifact_retention.online_retention_tick(None, None, cursor={}, checkpoints=sweep)
    if sweep:
        assert calls == [16] and "seconds" in result["checkpoint_cleanup"]
    else:
        assert calls == [] and result["checkpoint_cleanup"] == {"skipped": True}


def test_only_a_finished_unit_of_work_or_the_pause_wakes_the_controller():
    import json
    wake = controller.decision_relevant
    assert wake(json.dumps({"table": "jobs", "op": "UPDATE", "status": "done"}))
    assert wake(json.dumps({"table": "analysis_queue", "op": "UPDATE", "status": "failed"}))
    assert wake(json.dumps({"kind": "control", "key": "paused", "value": "1"}))
    assert not wake(json.dumps({"table": "control", "op": "UPDATE"}))
    assert not wake(json.dumps({"table": "jobs", "op": "INSERT", "status": "queued"}))
    assert not wake(json.dumps({"table": "analysis_queue", "op": "PRIORITY", "status": "queued"}))
    assert wake("not json"), "an unreadable notification wakes rather than being missed"
