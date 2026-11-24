from __future__ import annotations

import random

import numpy as np
import pytest

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.services.proposer import blind
from tests.unit.test_a_campaign_s_laws_are_its_seed_s import BUDGET, GRID, WHITELIST, _identity

GIB = 1 << 30


def _draw(need: int, seed: int = 2026) -> list[str]:
    laws = blind.blind_batch(random.Random(0), need, WHITELIST, GRID, set(), set(), fingerprint=dsl.fingerprint,
                             physical_identity=_identity, complexity_budget=BUDGET,
                             streams=lambda i: blind.law_stream(seed, i))
    return [dsl.fingerprint(law) for law in laws]


def test_a_grid_valid_a_few_percent_of_the_time_still_tops_a_campaign_up(monkeypatch):
    real, calls = blind.blind_law, [0]

    def scarce(rng, *args, **kwargs):
        calls[0] += 1
        if calls[0] % 4:
            for _ in range(5):
                rng.random()
            raise blind.GridError("no valid law in 200 draws; the grid cannot define a sparse phase")
        return real(rng, *args, **kwargs)

    monkeypatch.setattr(blind, "blind_law", scarce)
    first = _draw(6)
    assert len(first) == len(set(first)) == 6
    calls[0] = 0
    assert _draw(6) == first, "and the stream goes on deterministically"


def test_a_grid_with_no_valid_law_ends_its_batch_and_never_spins(monkeypatch):
    def never(rng, *args, **kwargs):
        raise blind.GridError("no valid law in 200 draws")

    monkeypatch.setattr(blind, "blind_law", never)
    assert _draw(3) == []


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, event, **fields):
        self.lines.append((event, fields))


class _Conn:
    rolled_back = 0

    def rollback_if_open(self):
        _Conn.rolled_back += 1


class _Repo:
    conn = _Conn()


def test_one_campaign_s_failure_is_logged_and_the_rest_are_served(monkeypatch):
    from graph_scale_dynamics.services.proposer import main as P
    served = []

    def top_up(repo, log, campaign):
        if campaign["campaign_id"] == "7":
            raise blind.GridError("no valid law in 200 draws; the grid cannot define a sparse phase")
        served.append(campaign["campaign_id"])
        return {"open": 3}

    monkeypatch.setattr(P, "top_up", top_up)
    log = _Log()
    windows = P.serve_campaigns(_Repo(), log, [{"campaign_id": "6"}, {"campaign_id": "7"}, {"campaign_id": "8"}])
    assert served == ["6", "8"]
    assert windows["6"] == windows["8"] == {"open": 3} and "error" in windows["7"]
    assert [fields["campaign"] for event, fields in log.lines if event == "top_up_failed"] == ["7"]
    assert _Conn.rolled_back >= 1, "the failed campaign's transaction is not left open under the next"


def test_the_database_s_own_fault_is_still_the_loop_s(monkeypatch):
    from graph_scale_dynamics.services.proposer import main as P

    def top_up(repo, log, campaign):
        raise P.DatabaseOperationalError("server closed the connection")

    monkeypatch.setattr(P, "top_up", top_up)
    with pytest.raises(P.DatabaseOperationalError):
        P.serve_campaigns(_Repo(), _Log(), [{"campaign_id": "6"}])


def test_a_let_through_s_stop_is_its_spend_however_the_share_moved():
    from tests.unit.test_the_gate_tree import row
    from graph_scale_dynamics.research import gate_tree as T
    record = {"S": [row(4096, "run_next", "base_block", salted=["too_dense"]), row(16384, "stop", "too_dense")],
              "W": [row(4096, "run_next", "base_block"), row(16384, "stop", "too_dense")]}
    tree = T.build_gate_tree(record)
    gate = next(g for g in tree["gates"] if g["gate"] == "too_dense")
    assert (gate["withheld"], gate["salt_spent"]) == (1, 1)


def test_a_law_s_own_peak_is_never_priced_below_its_rung_s_p95(monkeypatch):
    from graph_scale_dynamics.scheduling import memory as M
    n = 1048576
    monkeypatch.setattr(M, "_observed_peak_profile", lambda conn, kind: {n: {"memory_metric": "pss"}})
    monkeypatch.setattr(M, "_observed_candidate_peak_profile", lambda conn, kind, c, law: {n: {"memory_metric": "pss"}})
    monkeypatch.setattr(M, "projected_candidate_edges", lambda *a: None)
    monkeypatch.setattr(M, "sane_peak_prediction_bytes", lambda *a, **k: (23 * GIB, None, None))
    monkeypatch.setattr(M, "_measured_quantile", lambda conn, kind, target, q: 1 * GIB)
    got = M.predicted_claim_peak_bytes(None, kind="simulation", campaign_id="6", candidate_id="law", n=n, spec={})
    assert got >= 23 * GIB, f"the rung's p95 replaced the law's own 23 GiB: {got / GIB:.1f} GiB"
    monkeypatch.setattr(M, "_observed_candidate_peak_profile", lambda conn, kind, c, law: {})
    got = M.predicted_claim_peak_bytes(None, kind="simulation", campaign_id="6", candidate_id="law", n=n, spec={})
    assert got == int(np.ceil(GIB * M.EXPECTED_PEAK_SLACK)), "a law with no peak of its own there takes the rung's"


def test_an_analysis_given_back_is_capped_at_its_own_stop(monkeypatch):
    from graph_scale_dynamics.scheduling import memory as M
    monkeypatch.setattr(M, "hard_process_limit_bytes", lambda spec, **_: 12 * GIB)
    assert M.settled_reservation_bytes({}, 1048576, "analysis", 20 * GIB, floor_bytes=1) == 12 * GIB
    assert M.settled_reservation_bytes({}, 1048576, "analysis", 20 * GIB, floor_bytes=1,
                                       hard_cap_bytes=40 * GIB) >= 20 * GIB


def test_the_bandwidth_collector_is_started_owned(monkeypatch):
    from graph_scale_dynamics.observability import membw_dashboard as D
    from graph_scale_dynamics.operations.process_ownership import OWNER_PID_ENV
    seen = {}

    class Started:
        pid = 4242

        def poll(self):
            return None

    def popen(cmd, **kwargs):
        seen.update(kwargs["env"])
        return Started()

    monkeypatch.setattr(D.sys, "platform", "linux")
    monkeypatch.setattr(D.shutil, "which", lambda name: "/usr/bin/perf")
    monkeypatch.setattr(D, "find_existing_umc_perf_owner", lambda *a: None)
    monkeypatch.setattr(D.subprocess, "Popen", popen)
    monitor = D.MemoryBandwidthMonitor()
    try:
        assert monitor._start_private_locked()
    finally:
        monitor.process = None
        monitor._cleanup_private_locked()
    assert seen.get(OWNER_PID_ENV)


def test_the_bandwidth_collector_dies_with_its_owner(monkeypatch):
    from graph_scale_dynamics.observability import membw_tool
    from graph_scale_dynamics.operations import process_ownership
    called = []
    monkeypatch.setattr(process_ownership, "die_with_owner", lambda *a: called.append(True) or "unowned")
    monkeypatch.setattr(membw_tool.sys, "argv", ["membw_tool", "--help"])
    with pytest.raises(SystemExit):
        membw_tool.main()
    assert called, "the collector's entry point arms the parent-death signal"
