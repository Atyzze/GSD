from __future__ import annotations

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.decisions.engine import PARKING_RULES, STOP, Policy, Rung, Seed, decide
from graph_scale_dynamics.services.api.landscape_worker import reading_lost_at

POLICY = Policy()
LAW = G.unsalted_law("law-", POLICY.audit_fraction)


def rung(n, d_s=None, se=0.05):
    return Rung(n=n, mean_degree=2.5, connected_fraction=1.0, probes={"d_s": (d_s, se)} if d_s is not None else {},
                chains_disagreed=False, seeds_measured=3, seeds=tuple(Seed("ceiling", 1.0) for _ in range(3)))


SETTLED = [rung(64, 1.0), rung(256, 1.5), rung(1024, 2.0), rung(4096, 2.40), rung(16384, 2.60), rung(65536, 2.62)]


def test_a_settled_d_s_that_stops_reading_parks_at_the_rung_that_last_read():
    d = decide(LAW, SETTLED + [rung(262144)], POLICY)
    assert (d.action, d.rule, d.next_n) == (STOP, "reading_lost", None), d
    assert "no reading at N=262144" in d.reason and "N=65536" in d.reason
    assert d.rule in PARKING_RULES, "a lost reading parks; it is not a verdict on the law"


def test_parking_buys_no_rung_whatever_the_lane_looks_like():
    for in_flight in ({1048576: 0, 4194304: 0}, {1048576: 4, 4194304: 0}):
        d = decide(LAW, SETTLED + [rung(262144)], POLICY, deep_lane_in_flight=in_flight)
        assert (d.action, d.rule) == (STOP, "reading_lost"), (in_flight, d)


def test_a_park_is_a_park_and_not_a_stop():
    from graph_scale_dynamics.decisions.decider import _terminal_state
    from graph_scale_dynamics.domain.model import CandidateState
    parked = decide(LAW, SETTLED + [rung(262144)], POLICY)
    assert _terminal_state(parked) == CandidateState.PARKED.value
    dense = decide(LAW, [rung(64), rung(256)], POLICY)
    if dense.action == STOP:
        assert _terminal_state(dense) == CandidateState.STOPPED.value


def test_a_reading_that_returns_is_never_counted_as_a_refusal():
    d = decide(LAW, SETTLED + [rung(262144), rung(1048576, 2.63)], POLICY)
    assert d.action != STOP, d


def test_a_d_s_that_never_settled_is_not_a_lost_reading():
    moving = [rung(64, 1.0), rung(256, 1.8), rung(1024, 2.6), rung(4096, 3.4), rung(16384)]
    d = decide(LAW, moving, POLICY)
    assert (d.action, d.rule) == (STOP, "unsettled_twice"), d
    assert (decide(LAW, moving, Policy(second_rung=False)).rule) == "unsettled"


def test_the_landscape_sees_a_lost_reading_at_the_top_rung():
    rows = [{"n": 64, "d_s": 1.0}, {"n": 65536, "d_s": 2.62}, {"n": 262144, "d_s": None}]
    assert reading_lost_at({"rungs": rows}) == 262144
    assert reading_lost_at({"rungs": rows[:2]}) is None, "reading at the top rung"
    assert reading_lost_at({"rungs": [{"n": 64, "d_s": None}]}) is None, "never read: nothing was lost"


def test_the_extension_reservation_claims_the_deepest_job_first():
    from graph_scale_dynamics.services.worker import main as worker
    calls = []

    class Repo:
        conn = None

        def worker_allocation(self, **_):
            return {}

        def leased_count(self, **kw):
            return 0

        def claim_job(self, owner, kinds, **kw):
            calls.append(kw)
            return None

    worker.claim_simulation_for_owner(Repo(), "executor-1-1")
    deepest = [(c.get("min_n"), c.get("order")) for c in calls if c.get("order") == "deepest"]
    assert deepest == [(worker.LANE_MIN_N, "deepest"), (worker.EXTENSION_MIN_N, "deepest")], calls
