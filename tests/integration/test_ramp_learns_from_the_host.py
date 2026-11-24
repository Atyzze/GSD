from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import main
from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.scheduling import memory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "ramp-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
GIB = 1024 ** 3


class _Meter:
    def __init__(self):
        self.next = None

    def sample(self):
        return self.next


def test_a_step_is_learned_from_and_the_lesson_is_kept(isolated_postgres_schema, monkeypatch):
    dsn = isolated_postgres_schema.dsn
    init_db(dsn)
    repo = Repo(dsn)
    monkeypatch.setattr(memory, "system_memory", lambda: SimpleNamespace(available=60 * GIB, total=92 * GIB))
    monkeypatch.setattr(memory, "host_memory_launch_guard", lambda snapshot=None: {"allowed": True, "reasons": []})
    monkeypatch.setattr(memory, "host_available_floor_bytes", lambda total: 10 * GIB)
    monkeypatch.setattr(repo, "scheduler_snapshot", lambda: {"queued_simulations": 40, "analysis_backlog": 0})
    monkeypatch.setattr(main, "cpu_topology", lambda: (16, 32))
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        repo.insert_candidate("law-1", "camp", LAW, "metropolis", 1, "BASE_BLOCK_RUNNING")
        for seed in range(40):
            repo.insert_job(job_id=f"job-{seed}", campaign_id="camp", candidate_id="law-1",
                            kind="simulate", stage="base", n=64, seed=seed, replicate=0,
                            spec={"candidate_spec": LAW}, priority=10, sealed=False,
                            requested_by="ramp-contract")
        for _ in range(2):
            assert repo.claim_job("executor-ramp", ("simulate",), campaigns=("camp",)) is not None
        repo.set_flag("compute_active_slots", "2")
        spawned = []
        meter = _Meter()
        state = {"meter": meter, "spawned": 2, "stepped_at": time.monotonic() - 100, "limiter": None}

        meter.next = 8.0
        main._concurrency_ramp_tick(repo, state=state, baseline=1, ceiling=64, spawn_executor=spawned.append)
        raised = int(repo.get_flag("compute_active_slots"))
        assert raised > 2 + 2, "a learned step is sized from the host, not a fixed two"
        assert spawned == list(range(2, raised))

        for _ in range(raised - 2):
            assert repo.claim_job("executor-ramp", ("simulate",), campaigns=("camp",)) is not None
        state["stepped_at"] = time.monotonic() - 100
        meter.next = 8.0 + (raised - 2) * 3.5
        main._concurrency_ramp_tick(repo, state=state, baseline=1, ceiling=64, spawn_executor=spawned.append)
        kept = json.loads(repo.get_flag(main.RAMP_SLOPE_FLAG))
        assert kept["cpu_per_slot"] == pytest.approx(3.5) and kept["samples"] == 1
        assert main._learned_slope(repo).value == pytest.approx(3.5), "the next start climbs on it"
        monkeypatch.setattr(main, "cpu_topology", lambda: (32, 64))
        assert main._learned_slope(repo).value == pytest.approx(100.0 / 64), (
            "a lesson from another host is not applied")
    finally:
        repo.close()
