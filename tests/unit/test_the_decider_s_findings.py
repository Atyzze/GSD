from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from graph_scale_dynamics.db import decision_store as S
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.db.repo_candidates import CandidateStore
from graph_scale_dynamics.db.repo_jobs import JobStore
from graph_scale_dynamics.db.repo_records import RecordStore
from graph_scale_dynamics.decisions import decider as D
from graph_scale_dynamics.decisions.engine import HOLD, RUN_NEXT, STOP, Decision, Policy
from graph_scale_dynamics.dsl.dsl import fingerprint

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
LAW_SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
LAW = fingerprint(LAW_SPEC)
CAMPAIGN = "c"
CONTRACT = "analysis-test"
N = int(Policy.from_spec(SPEC).base_sizes[-1])
NOW = "2026-10-31T12:00:00Z"
PAST = "2026-10-31T11:00:00Z"

TABLES = """
CREATE TABLE campaigns (campaign_id text PRIMARY KEY, status text DEFAULT 'active', workers_target integer);
CREATE TABLE campaign_candidates (campaign_id text, candidate_id text, state text, state_reason text,
    created_utc text, updated_utc text, PRIMARY KEY (campaign_id, candidate_id));
CREATE TABLE campaign_graph_counter (campaign_id text PRIMARY KEY, next_ordinal integer DEFAULT 1);
CREATE TABLE jobs (job_id text PRIMARY KEY, campaign_id text, candidate_id text, kind text, stage text, n integer,
    seed integer, replicate integer DEFAULT 0, graph_ordinal integer, spec_json text, priority integer DEFAULT 100,
    status text DEFAULT 'queued', sealed integer DEFAULT 0, lease_owner text, lease_expires_utc text,
    attempts integer DEFAULT 0, lease_generation integer DEFAULT 0, result_artifact text, error text,
    requested_by text, created_utc text, updated_utc text, memory_reservation_bytes integer DEFAULT 0,
    next_attempt_utc text);
CREATE TABLE attempts (attempt_id text PRIMARY KEY, job_id text, number integer, started_utc text,
    finished_utc text, error_class text, exit_code integer, error text);
CREATE TABLE analysis_queue (campaign_id text, input_artifact text, analysis_version text, candidate_id text,
    n integer, seed integer, producer_job text, priority integer DEFAULT 100, status text DEFAULT 'queued',
    lease_owner text, claim_token text, lease_expires_utc text, error text, created_utc text, updated_utc text,
    attempts integer DEFAULT 0, max_attempts integer DEFAULT 3, next_attempt_utc text, error_class text,
    memory_reservation_bytes integer DEFAULT 0, PRIMARY KEY (campaign_id, input_artifact, analysis_version));
CREATE TABLE candidate_evidence_rebuilds (campaign_id text, candidate_id text, analysis_version text,
    status text, attempts integer DEFAULT 0, max_attempts integer DEFAULT 3, lease_owner text, claim_token text,
    lease_expires_utc text, next_attempt_utc text, error text, updated_utc text);
CREATE TABLE events (event_id integer PRIMARY KEY, topic text, payload_json text, created_utc text);
CREATE TABLE rung_summaries (campaign_id text, candidate_id text, analysis_version text, n integer);
CREATE TABLE engine_decisions (campaign_id text, decision_id text, candidate_id text, at_n integer, next_n integer,
    action text, rule text, reason text, priority integer, queue_order integer, jobs_created integer,
    rows_changed integer, released_hold boolean, jobs_seen text, engine text, facts_json text, created_utc text,
    inputs_json text, context_json text, PRIMARY KEY (campaign_id, decision_id));
CREATE TABLE engine_decisions_latest (campaign_id text, candidate_id text, decision_id text, at_n integer,
    next_n integer, action text, rule text, reason text, priority integer, jobs_created integer, jobs_seen text,
    facts_json text, created_utc text, PRIMARY KEY (campaign_id, candidate_id));
-- The schema's trigger (`gsd_track_latest_engine_decision`): the latest row moves only to a larger id.
CREATE TRIGGER latest AFTER INSERT ON engine_decisions BEGIN
  INSERT INTO engine_decisions_latest(campaign_id,candidate_id,decision_id,at_n,next_n,action,rule,reason,priority,
    jobs_created,jobs_seen,facts_json,created_utc)
  VALUES(NEW.campaign_id,NEW.candidate_id,NEW.decision_id,NEW.at_n,NEW.next_n,NEW.action,NEW.rule,NEW.reason,
    NEW.priority,NEW.jobs_created,NEW.jobs_seen,NEW.facts_json,NEW.created_utc)
  ON CONFLICT (campaign_id,candidate_id) DO UPDATE SET decision_id=excluded.decision_id,action=excluded.action,
    rule=excluded.rule,next_n=excluded.next_n,jobs_seen=excluded.jobs_seen
  WHERE engine_decisions_latest.decision_id < excluded.decision_id;
END;
"""


class _Conn:
    def __init__(self):
        self.raw = sqlite3.connect(":memory:", isolation_level=None)
        self.raw.row_factory = sqlite3.Row
        self.raw.executescript(TABLES)

    @property
    def in_transaction(self) -> bool:
        return self.raw.in_transaction

    def rollback_if_open(self) -> bool:
        if not self.raw.in_transaction:
            return False
        self.raw.execute("ROLLBACK")
        return True

    def execute(self, sql, args=()):
        sql = re.sub(r"\s+FOR UPDATE(\s+OF\s+\w+)?(\s+SKIP LOCKED)?", "", sql)
        sql = sql.replace("::text", "").replace("::bigint", "").replace("GREATEST(", "MAX(")
        return _Result(self.raw.execute(sql, tuple(args)))


class _Result:
    def __init__(self, cursor):
        self.rows = cursor.fetchall()
        self.rowcount = cursor.rowcount if cursor.rowcount != -1 else len(self.rows)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class _Repo(CandidateStore, JobStore):
    begin_transaction = Repo.begin_transaction
    _write = Repo._write
    _next_graph_ordinal = Repo._next_graph_ordinal
    jobs = RecordStore.jobs

    def __init__(self):
        self.conn = _Conn()

    def emit(self, topic, payload):
        self.conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                          (topic, json.dumps(payload), NOW))

    def candidate(self, candidate_id, campaign_id=None):
        return {"candidate_id": LAW, "spec": LAW_SPEC}

    def campaign_analysis_contract(self, campaign_id):
        return CONTRACT

    def get_flag(self, name, default=""):
        return default

    def set_flag(self, name, value):
        pass

    def state(self, law=LAW):
        return self.conn.execute("SELECT state FROM campaign_candidates WHERE candidate_id=?", (law,)).fetchone()[0]

    def job_status(self, seed):
        return self.conn.execute("SELECT status FROM jobs WHERE seed=? AND n=?", (seed, N)).fetchone()[0]


class _Log:
    def write(self, *args, **kwargs):
        pass


def _store(state="EXTENDING", law=LAW):
    repo = _Repo()
    repo.conn.execute("INSERT INTO campaigns(campaign_id) VALUES(?)", (CAMPAIGN,))
    repo.conn.execute("INSERT INTO campaign_candidates VALUES(?,?,?,?,?,?)", (CAMPAIGN, law, state, "", NOW, NOW))
    return S.DecisionStore(repo, _Log(), {"campaign_id": CAMPAIGN, "spec": SPEC}), repo


def _rung_with_one_seed_cancelled(store, repo):
    policy = store.policy
    assert store.enqueue_seeds(CAMPAIGN, LAW, N, seeds=policy.seeds, work_budget=policy.work_budget(N),
                               queue_order=D.QUEUE_ORDER["base"]) == policy.seeds
    repo.conn.execute("UPDATE jobs SET status='done' WHERE seed IN (0,1)")
    repo.conn.execute("UPDATE jobs SET status='cancelled' WHERE seed=2")


def _complete_rung():
    return Decision(law=LAW, action=RUN_NEXT, rule="complete_rung", reason="the rung has 2 of 3 seeds", at_n=N,
                    next_n=N)


def test_a_rung_bought_for_a_seed_whose_job_was_cancelled_queues_that_job_again():
    store, repo = _store()
    _rung_with_one_seed_cancelled(store, repo)
    effect = D.apply(store, CAMPAIGN, _complete_rung(), store.policy)
    assert effect["jobs_created"] == 1, "the cancelled seed is queued again and counted"
    assert [repo.job_status(seed) for seed in (0, 1, 2)] == ["done", "done", "queued"]
    priority = repo.conn.execute("SELECT priority FROM jobs WHERE seed=2").fetchone()[0]
    assert priority == S.queue_priority(D.QUEUE_ORDER["base"], N), "at the decision's own place in the queue"


def test_a_live_law_whose_seed_ran_and_whose_analysis_was_cancelled_waits_for_that_analysis_queued_again():
    store, repo = _store()
    for seed, status in ((0, "done"), (1, "done"), (2, "cancelled")):
        repo.conn.execute("INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,status) "
                          "VALUES(?,?,?,'simulate','rung',?,?,'done')", (f"j{seed}", CAMPAIGN, LAW, N, seed))
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status,attempts,error_class) VALUES(?,?,?,?,?,?,?,?,3,'candidate_terminal')",
                          (CAMPAIGN, f"a{seed}", CONTRACT, LAW, N, seed, f"j{seed}", status))
    evidence = store.law_evidence(CAMPAIGN, LAW)
    assert evidence == {"pending": True, "pending_reasons": [S.CANCELLED_ANALYSIS_REQUEUED]}, "not decided without it"
    row = repo.conn.execute("SELECT status,attempts,error_class FROM analysis_queue WHERE seed=2").fetchone()
    assert tuple(row) == ("queued", 0, None), "queued again with a fresh budget, as the scratch repair does"
    assert store.requeue_cancelled_analyses(CAMPAIGN, LAW) == 0, "once"


def test_a_cancelled_analysis_another_run_of_the_seed_supersedes_or_a_parked_law_s_is_left():
    store, repo = _store()
    for job, status in (("j0", "cancelled"), ("j0b", "done")):
        repo.conn.execute("INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,status) "
                          "VALUES(?,?,?,'simulate','rung',?,0,'done')", (job, CAMPAIGN, LAW, N))
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status) VALUES(?,?,?,?,?,0,?,?)",
                          (CAMPAIGN, job, CONTRACT, LAW, N, job, status))
    assert store.requeue_cancelled_analyses(CAMPAIGN, LAW) == 0, "superseded"
    repo.conn.execute("DELETE FROM analysis_queue WHERE status='done'")
    repo.conn.execute("UPDATE campaign_candidates SET state='PARKED'")
    assert store.requeue_cancelled_analyses(CAMPAIGN, LAW) == 0, "a parked law's"
    repo.conn.execute("UPDATE campaign_candidates SET state='EXTENDING'")
    assert store.requeue_cancelled_analyses(CAMPAIGN, LAW) == 1, "a live law's, alone"


def test_a_clock_stepped_back_still_makes_the_new_decision_the_law_s_latest(monkeypatch):
    store, repo = _store()
    clock = iter([2_000_000_000_000_000_000, 1_000_000_000_000_000_000])
    monkeypatch.setattr(S.time, "time_ns", lambda: next(clock))
    store.record_decision(CAMPAIGN, Decision(law=LAW, action=HOLD, rule="first", reason="r", at_n=N,
                                             next_n=N).as_dict())
    store.record_decision(CAMPAIGN, Decision(law=LAW, action=STOP, rule="second", reason="r", at_n=N,
                                             next_n=None).as_dict())
    latest = repo.conn.execute("SELECT rule, decision_id FROM engine_decisions_latest").fetchone()
    assert latest["rule"] == "second"
    assert re.fullmatch(r"\d{20}-[0-9a-f]{8}", latest["decision_id"]), "the format is kept"
    assert latest["decision_id"].startswith("02000000000000000001-")


def test_the_lane_s_queue_offers_its_room_to_live_laws_only(monkeypatch):
    store, repo = _store(law="live")
    repo.conn.execute("INSERT INTO campaign_candidates VALUES(?,?,?,?,?,?)",
                      (CAMPAIGN, "dead", "STOPPED", "", NOW, NOW))
    for law, stamp in (("dead", "1"), ("live", "2")):
        repo.conn.execute("INSERT INTO engine_decisions_latest VALUES(?,?,?,?,?,'hold','deep_lane_full','r',1,0,'',"
                          "'{}',?)", (CAMPAIGN, law, stamp, N, N, NOW))
    monkeypatch.setattr(S, "lane_rank_sql", lambda alias: "COALESCE(NULL,0)")
    monkeypatch.setattr(S, "lane_score_sql", lambda alias: "NULL")
    monkeypatch.setattr(S, "lane_tier_sql", lambda alias: "NULL")
    assert store.laws_waiting_for_the_lane(CAMPAIGN, N, limit=4) == ["live"]


@pytest.mark.parametrize("terminal", ["STOPPED", "DONE", "QUARANTINE", "PARKED"])
def test_a_running_or_held_state_is_never_written_over_a_terminal_one(terminal):
    store, repo = _store(state=terminal)
    for state in ("HELD", "EXTENDING", "BASE_BLOCK_RUNNING"):
        assert store.set_law_state(CAMPAIGN, LAW, state, rule="r", next_n=N) == 0
        assert repo.state() == terminal
    assert store.law_refuses_running(CAMPAIGN, LAW) == terminal


def test_only_the_602_re_decision_raises_a_parked_law():
    store, repo = _store(state="PARKED")
    assert store.law_refuses_running(CAMPAIGN, LAW, parked_ok=True) is None
    assert store.set_law_state(CAMPAIGN, LAW, "EXTENDING", rule="r", next_n=N, parked_ok=True) == 1
    assert repo.state() == "EXTENDING"
    assert store.set_law_state(CAMPAIGN, LAW, "EXTENDING", rule="r", next_n=N) == 0, "a state already held: no move"


def test_a_rung_bought_whose_seeds_all_ran_is_decided_again_at_once_not_left_without_work():
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    store, repo = _store()
    _rung_with_one_seed_cancelled(store, repo)
    repo.conn.execute("UPDATE jobs SET status='done' WHERE seed=2")
    unread = D._apply_and_record(store, CAMPAIGN, _complete_rung(), store.policy, {"released_hold": False})
    assert unread["made_no_work"] == D.MADE_NO_WORK, "nothing read at that size yet: deciding again sees nothing new"
    repo.conn.execute("DELETE FROM events")
    repo.conn.execute("DELETE FROM engine_decisions")
    repo.conn.execute("DELETE FROM engine_decisions_latest")
    repo.conn.execute("INSERT INTO rung_summaries VALUES(?,?,?,?)", (CAMPAIGN, LAW, ANALYSIS_VERSION, N))
    effect = D._apply_and_record(store, CAMPAIGN, _complete_rung(), store.policy, {"released_hold": False})
    assert effect["jobs_created"] == 0 and effect["made_no_work"] == D.DECIDE_AGAIN
    seen = repo.conn.execute("SELECT jobs_seen FROM engine_decisions_latest").fetchone()[0]
    assert seen.startswith(S.REDECIDE_MARK), "recorded with the buy, in its transaction: the next pass decides it"
    assert not repo.conn.execute("SELECT 1 FROM events WHERE topic='buy_made_no_work'").fetchall()
    again = D._apply_and_record(store, CAMPAIGN, _complete_rung(), store.policy, {"released_hold": False})
    assert again["made_no_work"] == D.MADE_NO_WORK, "the same buy twice with no work is said, not looped on"
    assert repo.conn.execute("SELECT COUNT(*) FROM events WHERE topic='buy_made_no_work'").fetchone()[0] == 1
    assert not repo.conn.execute("SELECT jobs_seen FROM engine_decisions_latest").fetchone()[0].startswith(
        S.REDECIDE_MARK)


def test_a_rung_bought_with_work_in_flight_is_recorded_as_it_was():
    store, repo = _store()
    _rung_with_one_seed_cancelled(store, repo)
    repo.conn.execute("UPDATE jobs SET status='queued' WHERE seed=2")
    effect = D._apply_and_record(store, CAMPAIGN, _complete_rung(), store.policy, {"released_hold": False})
    assert effect["jobs_created"] == 0 and "made_no_work" not in effect


def test_a_rung_bought_for_a_law_stopped_since_its_reading_makes_nothing_and_is_not_recorded():
    store, repo = _store()
    _rung_with_one_seed_cancelled(store, repo)
    repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED'")
    effect = D._apply_and_record(store, CAMPAIGN, _complete_rung(), store.policy, {"released_hold": False})
    assert effect["refused"] == "STOPPED" and effect["jobs_created"] == 0
    assert repo.state() == "STOPPED" and repo.job_status(2) == "cancelled", "checked before enqueueing"
    assert repo.conn.execute("SELECT COUNT(*) FROM engine_decisions").fetchone()[0] == 0


def test_a_pass_does_not_resurrect_a_law_that_waited_for_the_lane_and_stopped():
    class Store:
        def __init__(self):
            self.calls = []

        def laws_in_flight_at(self, campaign_id, n):
            return 0

        def laws_waiting_for_the_lane(self, campaign_id, n, limit, merit_only=False):
            return [] if merit_only else ["dead"]

        def law_refuses_running(self, campaign_id, law, parked_ok=False):
            return "STOPPED"

        def law_evidence(self, campaign_id, law):
            return {"entries": {}, "phenotype": None}

        def __getattr__(self, name):
            if name in ("parked_rung", "wake_lane_seeds", "latest_decision", "audit_laws_in_flight_at",
                        "one_transaction"):
                raise AttributeError(name)
            return lambda *args, **kwargs: (self.calls.append(name), 0 if name == "queue_depth" else [])[1]

    store = Store()
    tally = D.decide_pass(store, CAMPAIGN, Policy.from_spec(SPEC))
    assert tally[("refused", "STOPPED")] == 1
    assert not {"enqueue_seeds", "set_law_state", "record_decision"} & set(store.calls), store.calls


def test_a_stop_whose_record_fails_is_rolled_back_with_it():
    store, repo = _store()
    repo.conn.execute("INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,status) "
                      "VALUES('q',?,?,'simulate','rung',?,0,'queued')", (CAMPAIGN, LAW, N))

    def broken(campaign_id, row):
        raise RuntimeError("the record did not land")

    store.record_decision = broken
    stop = Decision(law=LAW, action=STOP, rule="too_dense", reason="r", at_n=N, next_n=None)
    with pytest.raises(RuntimeError):
        D._apply_and_record(store, CAMPAIGN, stop, store.policy, {"released_hold": False})
    assert repo.state() == "EXTENDING" and repo.job_status(0) == "queued", "neither landed"
    assert not repo.conn.in_transaction


def test_a_stop_and_its_record_land_together():
    store, repo = _store()
    stop = Decision(law=LAW, action=STOP, rule="too_dense", reason="r", at_n=N, next_n=None)
    effect = D._apply_and_record(store, CAMPAIGN, stop, store.policy, {"released_hold": False})
    assert effect["rows_changed"] == 1 and repo.state() == "STOPPED"
    assert repo.conn.execute("SELECT rule FROM engine_decisions_latest").fetchone()[0] == "too_dense"
    assert not repo.conn.in_transaction


def test_terminalize_outside_a_transaction_still_commits_its_own():
    _, repo = _store()
    assert repo.terminalize_candidate(CAMPAIGN, LAW, "STOPPED", "r")["state_changed"] == 1
    assert not repo.conn.in_transaction and repo.state() == "STOPPED"


def test_a_pass_whose_record_fails_leaves_the_law_to_the_next_pass():
    store, repo = _store(state="BASE_BLOCK_RUNNING")
    store.laws_awaiting_decision = lambda campaign_id: [LAW]
    store.law_evidence = lambda campaign_id, law: {"entries": {}, "phenotype": None}
    store.seed_rows = lambda campaign_id, law: {}
    store.laws_in_flight_at = lambda campaign_id, n: 0
    store.laws_waiting_for_the_lane = lambda *args, **kwargs: []
    store.wake_stray_seeds = lambda campaign_id: 0

    def broken(campaign_id, row):
        raise RuntimeError("the record did not land")

    store.record_decision = broken
    tally = D.decide_pass(store, CAMPAIGN, store.policy)
    assert tally[("failed", "RuntimeError")] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0, "the start's jobs went with it"
    S._FAILING.pop((CAMPAIGN, LAW), None)


def _leased(repo, *, attempts, closed, open_):
    repo.conn.execute("INSERT INTO jobs(job_id,campaign_id,candidate_id,kind,stage,n,seed,status,attempts,lease_owner,"
                      "lease_expires_utc,lease_generation) VALUES('j',?,?,'simulate','rung',?,0,'leased',?,'w',?,1)",
                      (CAMPAIGN, LAW, N, attempts, PAST))
    for number in range(closed + open_):
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,started_utc,finished_utc,error_class) "
                          "VALUES(?,?,?,?,?,?)",
                          (f"a{number}", "j", number + 1, PAST, PAST if number < closed else None, None))


def test_a_seed_whose_worker_vanished_runs_again_however_often_and_is_never_lost():
    from graph_scale_dynamics.domain.model import ATTEMPT_CLASS_WORKER_VANISHED, INTERRUPTED_ATTEMPT_CLASSES
    _, repo = _store()
    _leased(repo, attempts=1, closed=0, open_=1)
    waits = []
    for times in range(1, 9):
        assert repo.reclaim_expired() == 1
        status, after = repo.conn.execute("SELECT status,next_attempt_utc FROM jobs").fetchone()
        assert status == "queued" and after is not None, (times, status)
        assert not repo.conn.execute("SELECT 1 FROM attempts WHERE finished_utc IS NULL").fetchall()
        closed = [r[0] for r in repo.conn.execute("SELECT error_class FROM attempts")]
        assert closed == [ATTEMPT_CLASS_WORKER_VANISHED] * times, closed
        payload = json.loads(repo.conn.execute("SELECT payload_json FROM events WHERE topic='worker_vanished' "
                                               "ORDER BY event_id DESC").fetchone()[0])
        assert payload["times"] == times
        waits.append(payload["wait_seconds"])
        repo.conn.execute("UPDATE jobs SET status='leased',lease_owner='w',lease_expires_utc=?,"
                          "lease_generation=lease_generation+1", (PAST,))
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,started_utc) VALUES(?,?,?,?)",
                          (f"b{times}", "j", 1 + times, PAST))
    assert waits == [60.0, 120.0, 240.0, 480.0, 960.0, 1920.0, 3600.0, 3600.0], waits
    assert ATTEMPT_CLASS_WORKER_VANISHED in INTERRUPTED_ATTEMPT_CLASSES, "the fleet's, never the law's"
    assert Counter(r[0] for r in repo.conn.execute("SELECT topic FROM events")) == {"worker_vanished": 8}
    assert not repo.conn.execute("SELECT 1 FROM jobs WHERE status='lost'").fetchall()


def test_a_law_is_never_charged_for_a_seed_its_worker_lost(monkeypatch):
    store, repo = _store()
    _leased(repo, attempts=1, closed=0, open_=1)
    repo.conn.execute("UPDATE jobs SET status='lost'")
    monkeypatch.setattr(S, "evidence_pending_reasons", lambda conn, *a: ["simulation failed or lost"])
    found = store.law_evidence(CAMPAIGN, LAW)
    assert "failed_seeds" not in found and found["pending"], "a lost seed of an older fleet waits, it is not failed"
    repo.conn.execute("UPDATE jobs SET status='failed'")
    assert store.law_evidence(CAMPAIGN, LAW)["failed_seeds"] == {N: 1}, "a seed that failed is the law's"


def test_a_law_stopped_on_evidence_it_cannot_read_names_the_largest_n_it_has_a_graph_at():
    from graph_scale_dynamics.decisions.engine import STOP, Policy, decide
    from graph_scale_dynamics.decisions.replay import replay
    decision = decide("x" * 64, [], Policy(), evidence_failed="its rebuild failed for good", graphs_to_n=4096)
    assert (decision.action, decision.rule, decision.at_n) == (STOP, "failed", 4096)
    inputs = D.decision_inputs("x" * 64, [], Policy(), evidence_failed="its rebuild failed for good",
                               graphs_to_n=4096)
    assert inputs["graphs_to_n"] == 4096 and replay(inputs).at_n == 4096, "the replay names the same N"
    older = dict(inputs)
    older.pop("graphs_to_n")
    assert replay(older).at_n is None, "a decision recorded before 787 replays as it was made"
