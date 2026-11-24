from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def _decision(rule, action="run_next", facts=None):
    from graph_scale_dynamics.decisions import engine as E
    return E.Decision(law="a" * 64, action=action, rule=rule, reason=rule, at_n=16384, next_n=65536,
                      facts=dict(facts or {}, gate={"read": True}))


def test_a_chain_the_gate_passes_is_read_before_one_it_audits(monkeypatch):
    from graph_scale_dynamics.decisions import starts_rule as FS
    from types import SimpleNamespace
    rungs = {"cubic": [SimpleNamespace(n=16384, chain="cubic")], "empty": [SimpleNamespace(n=16384, chain="empty")]}
    answers = {"cubic": _decision("gate_audit"), "empty": _decision("d_s_settled")}
    monkeypatch.setattr(FS.E, "_gate", lambda law, chain, policy, decision, context: answers[chain[0].chain])
    decided = FS._gated("a" * 64, _decision("d_s_settled"), FS.E.Policy(), rungs, {}, first=("cubic",))
    assert decided.rule == "d_s_settled" and decided.facts["gate"]["chain"] == "empty"
    answers["empty"] = _decision("no_finite_dimension", action="stop")
    assert FS._gated("a" * 64, _decision("d_s_settled"), FS.E.Policy(), rungs, {}, first=("cubic",)).rule == "gate_audit"


def _rungs(budget: int):
    from graph_scale_dynamics.decisions.engine import Rung, Seed
    seeds = tuple(Seed(termination="budget", work_units=budget, work_budget=budget) for _ in range(3))
    return [Rung(n=n, mean_degree=3.0, probes={}, seeds_measured=3) for n in (64, 256, 1024, 4096)] + [
        Rung(n=16384, mean_degree=3.0, probes={}, seeds_measured=3, seeds=seeds)]


def test_a_buy_s_budget_is_read_from_its_seeds_record(monkeypatch):
    from graph_scale_dynamics.decisions import depth
    from graph_scale_dynamics.decisions.engine import Policy
    policy = Policy.from_spec(SURVEY)
    own = policy.work_budget(16384)
    monkeypatch.setattr(depth, "_merit_rule", lambda rungs, policy, starts_reading: "starts_shape")
    assert depth.bought_on_merit(_rungs(own), policy) is None
    assert depth.bought_on_merit(_rungs(own * 2), policy) == "starts_shape"


class _Conn:
    def __init__(self):
        self.seen = []

    def execute(self, sql, params=()):
        self.seen.append((sql, params))

        class Row:
            def fetchone(self):
                return {"c": 0}
        return Row()


def test_only_the_memory_backoff_counts_as_a_memory_deferral():
    from graph_scale_dynamics.scheduling import memory as M
    conn = _Conn()
    M.memory_deferred_simulations(conn)
    sql, params = conn.seen[0]
    assert "next_attempt_utc<=?" in sql and len(params) == 2
    assert params[1] < "2999", "the parked seeds' far future is left out"


def test_a_claim_is_compared_with_the_reading_its_budget_came_from(monkeypatch):
    from graph_scale_dynamics.scheduling import memory as M
    monkeypatch.setattr(M, "recorded_lease_reservations", lambda conn: {"total": 10 << 30})
    monkeypatch.setattr(M, "host_memory_launch_guard", lambda snapshot=None: {"allowed": True, "total_bytes": 64 << 30,
                                                                              "min_available_bytes": 10 << 30})
    monkeypatch.setattr(M, "launch_ramp_state", lambda conn, snapshot=None: {"allowed": True})

    class Cursor:
        rowcount = 1

    class Conn:
        def execute(self, *a):
            return Cursor()

    verdict = M.admit_recorded_claim(Conn(), kind="simulation", reservation_bytes=2 << 30, budget_bytes=8 << 30,
                                     job_id="j", owner="o", lease_generation=1, reserved_bytes=4 << 30)
    assert verdict["proposed_total"] == 6 << 30 and verdict["within_budget"]


def test_the_cores_are_the_ones_the_fleet_may_use(tmp_path):
    from graph_scale_dynamics.scheduling.cpu import cores_of
    for cpu, (package, core) in enumerate([(0, 0), (0, 0), (0, 1), (0, 1), (1, 0), (1, 0)]):
        topology = tmp_path / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "physical_package_id").write_text(f"{package}\n")
        (topology / "core_id").write_text(f"{core}\n")
    assert cores_of([0, 1, 2, 3], sysfs=tmp_path) == 2
    assert cores_of([0, 1, 2, 3, 4, 5], sysfs=tmp_path) == 3
    assert cores_of([7], sysfs=tmp_path) is None


def test_a_ladder_rung_with_no_budget_is_refused():
    from graph_scale_dynamics.scheduling.limits import validate_limits
    spec = json.loads(json.dumps(SURVEY))
    assert not [p for p in validate_limits(spec) if "work_budgets" in p]
    budgets = spec["engine"]["policy"]["work_budgets"]
    spec["engine"]["policy"]["work_budgets"] = [w for w in budgets if int(w[0]) != 65536]
    assert any("65,536" in p for p in validate_limits(spec))


def test_a_blind_campaign_s_proposer_sets_its_pool_and_nothing_else():
    from graph_scale_dynamics.scheduling.search_policy import kind_of
    spec = json.loads(json.dumps(SURVEY))
    spec["proposer"] = {"pool_min": 32, "cartography": {"enabled": True}}
    problems = kind_of(spec).validate(spec["search_policy"], spec)
    assert any("cartography" in p for p in problems)


def test_a_launch_that_fails_is_a_crash_and_backs_off():
    from graph_scale_dynamics.operations.service_restart import _launched

    def broken(record):
        raise OSError("no such file")

    side = {"module": "graph_scale_dynamics.services.reporter", "critical": False, "crashes": []}
    assert _launched(broken, side, 100.0) is False and side["retry_at"] > 100.0
    own = {"module": "graph_scale_dynamics.services.worker", "critical": True, "crashes": [99.0] * 5}
    with pytest.raises(RuntimeError, match="crash loop"):
        _launched(broken, own, 100.0)
