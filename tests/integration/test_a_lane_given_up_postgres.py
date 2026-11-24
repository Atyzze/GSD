from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
TOP = 4194304


class Log:
    def write(self, *args, **kwargs):
        pass


def _law(name: str) -> str:
    return name.ljust(64, "0")


@pytest.fixture
def lane(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
    return isolated_postgres_schema.dsn, campaign_id


def _store(repo, campaign_id):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    return DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})


def _decided(repo, store, campaign_id, name, action, rule, facts, *, state="EXTENDING", seeds=()):
    law = _law(name)
    repo.insert_candidate(law, campaign_id, {"terms": []}, "equilibrium", 1, state)
    store.record_decision(campaign_id, {"law": law, "action": action, "rule": rule, "reason": "r",
                                        "at_n": 1048576, "next_n": TOP, "engine": "decision-engine-2",
                                        "facts": facts})
    for seed, status in seeds:
        repo.insert_job(job_id=f"{name}-{seed}".ljust(64, "j"), campaign_id=campaign_id, candidate_id=law,
                        kind="simulate", stage=f"rung_n{TOP}", n=TOP, seed=seed, replicate=0, spec={},
                        priority=TOP, requested_by="decider", sealed=False)
        repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, f"{name}-{seed}".ljust(64, "j")))
    return law


def test_the_waiters_go_in_their_own_reading_first_then_audit_traffic_then_known_answers(lane):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = lane
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        family = _decided(repo, store, campaign_id, "family", "hold", "deep_lane_full",
                          {"lane": {"rank": 2, "law_score": 99.0}}, state="HELD")
        audit = _decided(repo, store, campaign_id, "audit", "hold", "deep_lane_full",
                         {"lane": {"rank": 1, "law_score": 98.0}}, state="HELD")
        low = _decided(repo, store, campaign_id, "merit-low", "hold", "deep_lane_full",
                       {"lane": {"rank": 0, "law_score": 10.0}}, state="HELD")
        high = _decided(repo, store, campaign_id, "merit-high", "hold", "deep_lane_full",
                        {"lane": {"rank": 0, "law_score": 50.0}}, state="HELD")
        assert store.laws_waiting_for_the_lane(campaign_id, TOP, 10) == [high, low, audit, family]
        assert store.laws_waiting_for_the_lane(campaign_id, TOP, 10, merit_only=True) == [high, low]


def test_the_dimension_rule_s_tiers_wait_after_the_starts_own_reading_and_before_audit_traffic(lane):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = lane
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        audit = _decided(repo, store, campaign_id, "audit", "hold", "deep_lane_full",
                         {"lane": {"rank": 1, "law_score": 98.0}}, state="HELD")
        third = _decided(repo, store, campaign_id, "tier-3", "hold", "deep_lane_full",
                         {"lane": {"rank": 0, "law_score": 90.0, "tier": 3}}, state="HELD")
        first = _decided(repo, store, campaign_id, "tier-1", "hold", "deep_lane_full",
                         {"lane": {"rank": 0, "law_score": 5.0, "tier": 1}}, state="HELD")
        old = _decided(repo, store, campaign_id, "old-rules", "hold", "deep_lane_full",
                       {"lane": {"rank": 0, "law_score": 1.0}}, state="HELD")
        assert store.laws_waiting_for_the_lane(campaign_id, TOP, 10) == [old, first, third, audit]


def test_a_lane_given_up_parks_its_seeds_stops_the_running_one_and_wakes_them_on_resume(lane):
    from graph_scale_dynamics.db.lane_yield import lane_yield_reason, release_defer_seconds
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import (
        ATTEMPT_CLASS_LANE_YIELD, INTERRUPTED_ATTEMPT_CLASSES, LANE_YIELD_REASON)
    from graph_scale_dynamics.operations.campaign_control import pause_attempt_class
    dsn, campaign_id = lane
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        law = _decided(repo, store, campaign_id, "g6214", "run_next", "d_s_settled",
                       {"salted": ["no_finite_dimension"]}, seeds=[(0, "queued"), (1, "queued"), (2, "done")])
        running = repo.claim_job("executor-lane", ("simulate",))
        assert running is not None and running["candidate_id"] == law
        assert lane_yield_reason(repo, running) is None, "in its lane: keep going"
        store.record_decision(campaign_id, {"law": law, "action": "hold", "rule": "deep_lane_full", "reason": "r",
                                            "at_n": 1048576, "next_n": TOP, "engine": "decision-engine-2",
                                            "facts": {"yielded": {"to": "someone", "at_n": TOP}}})
        assert store.park_lane_seeds(campaign_id, law, TOP) == {"parked": 1, "stopping": 1}
        assert repo.claim_job("executor-other", ("simulate",)) is None, "a parked seed is claimed by nobody"
        reason = lane_yield_reason(repo, running)
        assert reason == LANE_YIELD_REASON and pause_attempt_class(reason) == ATTEMPT_CLASS_LANE_YIELD
        assert ATTEMPT_CLASS_LANE_YIELD in INTERRUPTED_ATTEMPT_CLASSES
        assert repo.release_job(running["job_id"], "executor-lane", int(running["lease_generation"]),
                                defer_seconds=release_defer_seconds(reason))
        assert repo.claim_job("executor-other", ("simulate",)) is None
        assert store.parked_rung(campaign_id, law) == TOP
        assert store.wake_lane_seeds(campaign_id, law, TOP) == 2
        assert store.parked_rung(campaign_id, law) is None
        assert repo.claim_job("executor-other", ("simulate",)) is not None, "woken, it runs again"


def test_a_seed_parked_after_its_law_took_the_lane_back_is_woken(lane):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = lane
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        law = _decided(repo, store, campaign_id, "raced", "run_next", "lane_resumed", {"resumed": {"at_n": TOP}},
                       seeds=[(0, "queued")])
        other = _decided(repo, store, campaign_id, "waiting", "hold", "deep_lane_full", {"yielded": {"at_n": TOP}},
                         state="HELD", seeds=[(0, "queued")])
        store.park_lane_seeds(campaign_id, law, TOP)
        store.park_lane_seeds(campaign_id, other, TOP)
        assert store.wake_stray_seeds(campaign_id) == 1
        assert store.parked_rung(campaign_id, law) is None and store.parked_rung(campaign_id, other) == TOP


def test_the_lane_counts_the_laws_with_work_at_it_and_never_a_finished_one(lane):
    from graph_scale_dynamics.db.lane_yield import PARKED_FROM
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = lane
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        _decided(repo, store, campaign_id, "bought", "run_next", "d_s_settled", {})
        _decided(repo, store, campaign_id, "finished", "run_next", "d_s_settled", {}, state="DONE")
        _decided(repo, store, campaign_id, "reinstated", "hold", "unsettled", {}, state="HELD", seeds=[(0, "queued")])
        _decided(repo, store, campaign_id, "running", "hold", "unsettled", {}, state="HELD", seeds=[(0, "leased")])
        parked = _decided(repo, store, campaign_id, "parked", "hold", "deep_lane_full", {}, state="HELD",
                          seeds=[(0, "queued")])
        repo.conn.execute("UPDATE jobs SET next_attempt_utc=? WHERE candidate_id=?", (PARKED_FROM, parked))
        _decided(repo, store, campaign_id, "ran", "hold", "unsettled", {}, state="HELD", seeds=[(0, "done")])
        assert store.laws_in_flight_at(campaign_id, TOP) == 3, "bought, reinstated and running; not the finished law"
