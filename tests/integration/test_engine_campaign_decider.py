from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
CANDIDATE = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
from graph_scale_dynamics.dsl import dsl  # noqa: E402
LAW = dsl.fingerprint(CANDIDATE)


class Log:
    def write(self, *args, **kwargs):
        pass


@pytest.fixture
def engine_campaign(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    return isolated_postgres_schema.dsn, campaign_id


def _probe_done_jobs(repo, campaign_id):
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    now = utc_now()
    for job in repo.conn.execute("SELECT job_id,n,seed FROM jobs WHERE campaign_id=? AND status='done'",
                                 (campaign_id,)).fetchall():
        artifact = f"artifact-{job['job_id']}"
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                          "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job["job_id"], "{}", now))
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (campaign_id, artifact, ANALYSIS_VERSION, LAW, job["n"], job["seed"], job["job_id"],
                           "done", now, now))


def _store(repo, campaign_id):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    return DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})


def test_a_new_law_is_started_at_64_with_three_seeds_and_the_window_as_their_deadline(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.decider import decide_pass
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        assert store.laws_awaiting_decision(campaign_id) == [LAW]
        tally = decide_pass(store, campaign_id, store.policy)
        assert tally[("run_next", "start")] == 1
        jobs = repo.conn.execute("SELECT n,seed,priority,spec_json,status FROM jobs WHERE campaign_id=? "
                                 "AND candidate_id=? ORDER BY seed", (campaign_id, LAW)).fetchall()
        assert [(j["n"], j["status"]) for j in jobs] == [(64, "queued")] * 3
        assert all(j["priority"] == 10 * 10_000_000 + 64 for j in jobs)
        assert all(json.loads(j["spec_json"])["execution"]["one_shot"]["work_budget"] == store.policy.work_budget(64)
                   for j in jobs)
        assert all('"timeout_seconds"' not in j["spec_json"] for j in jobs), "no clock watches a seed"
        row = repo.conn.execute("SELECT action,rule,jobs_created,rows_changed FROM engine_decisions "
                                "WHERE campaign_id=? AND candidate_id=?", (campaign_id, LAW)).fetchone()
        assert (row["action"], row["rule"], row["jobs_created"]) == ("run_next", "start", 3)
        assert store.laws_awaiting_decision(campaign_id) == [], "a law with queued work is not reconsidered"


def test_a_law_waits_for_its_probes_then_is_reconsidered_exactly_once(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.decider import decide_pass
    dsn, campaign_id = engine_campaign
    count = lambda repo: repo.conn.execute("SELECT COUNT(*) c FROM engine_decisions WHERE campaign_id=?",
                                           (campaign_id,)).fetchone()["c"]
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        decide_pass(store, campaign_id, store.policy)
        repo.conn.execute("UPDATE jobs SET status='done', updated_utc='2999-01-01T00:00:00Z' WHERE campaign_id=?",
                          (campaign_id,))
        assert _store(repo, campaign_id).laws_awaiting_decision(campaign_id) == [], "seeds done, probes not yet"
        _probe_done_jobs(repo, campaign_id)
        store = _store(repo, campaign_id)
        assert store.laws_awaiting_decision(campaign_id) == [LAW]
        decide_pass(store, campaign_id, store.policy)
        assert count(repo) == 2
        created = repo.conn.execute("SELECT jobs_created FROM engine_decisions WHERE campaign_id=? "
                                    "ORDER BY decision_id DESC LIMIT 1", (campaign_id,)).fetchone()
        assert created["jobs_created"] == 0, "done seeds are not queued again"
        assert _store(repo, campaign_id).laws_awaiting_decision(campaign_id) == []


def test_a_stop_is_terminal_and_holds_wait_for_an_empty_queue(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import TERMINAL_CANDIDATE_STATES
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        store.record_decision(campaign_id, {"law": LAW, "action": "hold", "rule": "unsettled", "reason": "r",
                                            "at_n": 4096, "next_n": 16384, "engine": "decision-engine-1"})
        assert [h["law"] for h in store.held_laws(campaign_id)] == [LAW]
        assert store.queue_depth(campaign_id) == 0
        assert store.set_law_state(campaign_id, LAW, "STOPPED", rule="too_dense", next_n=None) == 1
        state = repo.conn.execute("SELECT state FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                                  (campaign_id, LAW)).fetchone()["state"]
        assert state == "STOPPED" and state in TERMINAL_CANDIDATE_STATES
        assert store.held_laws(campaign_id) == []


def test_a_law_in_the_held_state_is_found_and_released(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.decider import decide_pass
    from graph_scale_dynamics.decisions.engine import policy_fingerprint
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        store.record_decision(campaign_id, {"law": LAW, "action": "hold", "rule": "unsettled", "reason": "r",
                                            "at_n": 4096, "next_n": 16384, "engine": "decision-engine-2"})
        assert store.set_law_state(campaign_id, LAW, "HELD", rule="unsettled", next_n=16384) == 1
        assert [h["law"] for h in store.held_laws(campaign_id)] == [LAW]
        assert store.queue_depth(campaign_id) == 0
        store.record_decision_rules_fingerprint(campaign_id, policy_fingerprint(store.policy))
        decide_pass(store, campaign_id, store.policy)
        latest = repo.conn.execute("SELECT action, rule FROM engine_decisions_latest WHERE campaign_id=? "
                                   "AND candidate_id=?", (campaign_id, LAW)).fetchone()
        assert (latest["action"], latest["rule"]) == ("run_next", "hold_released")


def test_a_permanently_failed_seed_stops_the_law_instead_of_stranding_it(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.decider import decide_pass
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        decide_pass(store, campaign_id, store.policy)
        repo.conn.execute("UPDATE jobs SET status='done', updated_utc='2999-01-01T00:00:00Z' WHERE campaign_id=? AND seed<>1",
                          (campaign_id,))
        repo.conn.execute("UPDATE jobs SET status='failed', updated_utc='2999-01-01T00:00:01Z' WHERE campaign_id=? AND seed=1",
                          (campaign_id,))
        _probe_done_jobs(repo, campaign_id)
        store = _store(repo, campaign_id)
        tally = decide_pass(store, campaign_id, store.policy)
        assert tally[("stop", "failed")] == 1, tally
        state = repo.conn.execute("SELECT state FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                                  (campaign_id, LAW)).fetchone()["state"]
        assert state == "STOPPED"


def test_holds_past_the_limit_do_not_hide_a_law_that_awaits_its_decision(engine_campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import utc_now
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        repo.conn.execute("DELETE FROM campaign_candidates WHERE campaign_id=?", (campaign_id,))
        for index, prefix in enumerate("abcde"):
            law = prefix * 64
            repo.insert_candidate(law, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
            repo.conn.execute(
                "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
                "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, f"0000000000000000{index:03d}-a", law, 4096, 16384, "hold", "unsettled", "held",
                 None, None, 0, 0, False, "0:", "decision-engine-2", "{}", utc_now()))
        newcomer = "f" * 64
        repo.insert_candidate(newcomer, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        assert store.laws_awaiting_decision(campaign_id, limit=3) == [newcomer]
        assert store.laws_awaiting_decision(campaign_id) == [newcomer]


def test_the_decision_backlog_counts_the_laws_awaiting_and_dates_the_oldest(engine_campaign):
    from graph_scale_dynamics.db.decision_store import decision_backlog
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.operations.lifecycle_recovery import DECISION_WAIT_ALERT_SECONDS, decision_backlog_alerts
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        repo.conn.execute("DELETE FROM campaign_candidates WHERE campaign_id=?", (campaign_id,))
        for index, (prefix, updated) in enumerate((("a", "2026-09-17T01:00:00Z"), ("b", "2026-09-17T03:00:00Z"))):
            repo.insert_candidate(prefix * 64, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
            repo.conn.execute("UPDATE campaign_candidates SET updated_utc=? WHERE campaign_id=? AND candidate_id=?",
                              (updated, campaign_id, prefix * 64))
        held = "c" * 64
        repo.insert_candidate(held, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        repo.conn.execute(
            "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,priority,"
            "queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (campaign_id, "00000000000000000001-a", held, 4096, 16384, "hold", "unsettled", "held", None, None, 0, 0,
             False, "0:", "decision-engine-2", "{}", "2026-09-17T00:00:00Z"))
        backlog = decision_backlog(repo.conn, campaign_id)
        assert backlog == {"awaiting": 2, "oldest_since_utc": "2026-09-17T01:00:00Z"}, backlog
        waited = lambda stamp: DECISION_WAIT_ALERT_SECONDS + 1 if stamp == "2026-09-17T01:00:00Z" else 0.0
        alerts = decision_backlog_alerts(backlog, paused=False, age_seconds=waited)
        assert [a["code"] for a in alerts] == ["DECISIONS_BEHIND"] and alerts[0]["awaiting"] == 2
        assert decision_backlog_alerts(backlog, paused=True, age_seconds=waited) == [], "the controller waits with a pause"
        assert decision_backlog_alerts(backlog, paused=False, age_seconds=lambda s: 30.0) == []


def test_the_lane_is_counted_and_its_waiting_laws_ranked_on_the_real_schema(engine_campaign):
    import json as _json
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)

        def decided(law, index, action, rule, next_n, score=None):
            facts = {"lane": {"rank": 0, "law_score": score}} if score is not None or rule == "deep_lane_full" else {}
            repo.conn.execute(
                "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
                "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, f"00000000000000001{index:03d}-a", law, 262144, next_n, action, rule, rule, None, None,
                 0, 0, False, "0:", "decision-engine-2", _json.dumps(facts), "2026-09-17T00:00:00Z"))

        decided("a" * 64, 1, "run_next", "d_s_settled", 1048576)
        decided("b" * 64, 2, "run_next", "d_s_settled", 1048576)
        decided("b" * 64, 3, "done", "ladder_complete", None)
        decided("c" * 64, 4, "run_next", "d_s_settled", 262144)
        decided("d" * 64, 5, "hold", "deep_lane_full", 1048576, score=12.0)
        decided("e" * 64, 6, "hold", "deep_lane_full", 1048576, score=40.0)
        decided("f" * 64, 7, "hold", "deep_lane_full", 1048576)
        decided("0" * 64, 8, "hold", "no_plateau", 1048576, score=99.0)
        decided("9" * 64, 9, "hold", "deep_lane_full", 1048576, score=80.0)
        for law, state in (("d" * 64, "HELD"), ("e" * 64, "HELD"), ("f" * 64, "HELD"), ("9" * 64, "STOPPED")):
            repo.insert_candidate(law, campaign_id, CANDIDATE, "equilibrium", 1, state)
        assert store.laws_in_flight_at(campaign_id, 1048576) == 1
        assert store.laws_waiting_for_the_lane(campaign_id, 1048576, limit=5) == ["e" * 64, "d" * 64, "f" * 64]
        assert store.laws_waiting_for_the_lane(campaign_id, 1048576, limit=1) == ["e" * 64]
        assert store.laws_waiting_for_the_lane(campaign_id, 1048576, limit=0) == []
        assert store.law_standing("f" * 64, None) == {"control_family": None, "law_score": None}
