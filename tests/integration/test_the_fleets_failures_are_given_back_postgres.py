from __future__ import annotations

import json
import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

OLD = "2026-09-28T09:00:00Z"
STOPPED_AT = "2026-09-28T10:00:00Z"


def _law(i: int) -> str:
    return f"law-fleet-{i}".ljust(64, "0")


@pytest.fixture
def world(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "the fleet's failures"}, search_seed=7)["campaign_id"])
    yield repo, campaign
    repo.close()


def _job(repo, campaign, law, job_id, *, n=65536, seed=0, status="queued", error=None, priority=None, stage=None):
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate",
                    stage=stage or f"rung_n{n}", n=n, seed=seed, replicate=0, spec={},
                    priority=n if priority is None else priority, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status=?,error=?,updated_utc=? WHERE job_id=?", (status, error, OLD, job_id))


def _failures(repo, job, classes):
    for number, cls in enumerate(classes, start=1):
        attempt = f"{job}-{number}"
        repo.record_attempt(attempt, job, number, "executor-9-541")
        repo.close_attempt(attempt, 1, 0, 1.0, f"ended: {cls}", {}, error_class=cls)


def _stop(repo, campaign, law, n, rule="failed"):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{time.time_ns():020d}-{law[-6:]}", law, n, None, "stop", rule, f"{rule} at {n}", None, None,
         0, 1, False, "3:mark", "decision-engine-2", "{}", STOPPED_AT))
    repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE campaign_id=? AND candidate_id=?",
                      (campaign, law))


def _stopped(reason: str) -> str:
    return f"child failed [stopped: 4 attempts, third failure with reason '{reason}']"


def test_the_fleets_failures_are_given_back_once_per_rung_and_the_laws_own_are_not(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    repo, campaign = world
    names = ("interrupted", "storage", "own", "memory", "analysis", "running", "again", "other")
    laws = {name: _law(i) for i, name in enumerate(names)}
    for name, law in laws.items():
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, laws["interrupted"], "a0", status="failed", error=_stopped("supervisor_interrupted"))
    _failures(repo, "a0", ["supervisor_interrupted"] * 3 + ["exception:ValueError"])
    _job(repo, campaign, laws["interrupted"], "a1", seed=1, status="cancelled")
    repo.conn.execute("UPDATE jobs SET updated_utc=? WHERE job_id='a1'", (STOPPED_AT,))
    _stop(repo, campaign, laws["interrupted"], 65536)
    _job(repo, campaign, laws["storage"], "b0", status="failed", error=_stopped("no_result"))
    _failures(repo, "b0", ["no_result"] * 3)
    _stop(repo, campaign, laws["storage"], 65536)
    _job(repo, campaign, laws["own"], "c0", status="failed", error=_stopped("exception:ValueError"))
    _failures(repo, "c0", ["exception:ValueError"] * 3)
    _stop(repo, campaign, laws["own"], 65536)
    _job(repo, campaign, laws["memory"], "d0", status="failed", error="child stopped at the single-job ceiling")
    _failures(repo, "d0", ["memory_hard_stop"])
    _stop(repo, campaign, laws["memory"], 65536)
    _job(repo, campaign, laws["analysis"], "e0", status="done")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("e" * 64, 1, "application/json", None, "{}", OLD))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,error,error_class,attempts,created_utc,updated_utc) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, "e" * 64, ANALYSIS_VERSION, laws["analysis"], 65536, 0, "e0", "failed",
                       "child process failure", "child_process:missing_success_receipt", 3, OLD, OLD))
    _stop(repo, campaign, laws["analysis"], 65536)
    _job(repo, campaign, laws["running"], "f0", status="lost", error="lost after 3 expired leases")
    _failures(repo, "f0", ["supervisor_interrupted"] * 3)
    _job(repo, campaign, laws["again"], "g0", status="failed", error=_stopped("no_result"))
    _failures(repo, "g0", ["no_result"] * 3)
    _stop(repo, campaign, laws["again"], 65536)
    repo.conn.execute("INSERT INTO events(topic,payload_json,created_utc) VALUES(?,?,?)",
                      ("law_reinstated", json.dumps({"campaign_id": campaign, "candidate_id": laws["again"],
                                                     "at_n": 65536, "contract": F.FAILURE_REPAIR_CONTRACT}), OLD))
    _job(repo, campaign, laws["other"], "h0", status="failed", error=_stopped("no_result"))
    _failures(repo, "h0", ["no_result"] * 3)
    _stop(repo, campaign, laws["other"], 65536, rule="too_dense")

    seen = F.survey(repo)
    assert sorted(e["law"] for e in seen["reinstate"]) == sorted(
        laws[k][:10] for k in ("interrupted", "storage", "analysis"))

    result = F.repair(repo)
    status = {r["job_id"]: r["status"] for r in repo.conn.execute("SELECT job_id,status FROM jobs").fetchall()}
    state = {r["candidate_id"]: r["state"] for r in repo.conn.execute(
        "SELECT candidate_id,state FROM campaign_candidates").fetchall()}
    for name in ("interrupted", "storage", "analysis"):
        assert state[laws[name]] == "EXTENDING", f"{name}: running again at the rung it was stopped at"
    assert status["a0"] == "queued" and status["a1"] == "queued", "its seed and the work its stop cancelled"
    assert status["b0"] == "queued"
    analysis = repo.conn.execute("SELECT status FROM analysis_queue WHERE input_artifact=?", ("e" * 64,)).fetchone()
    assert analysis["status"] == "queued"
    for name, job in (("own", "c0"), ("memory", "d0"), ("again", "g0")):
        assert state[laws[name]] == "STOPPED" and status[job] == "failed", name
    assert status["f0"] == "queued" and state[laws["running"]] == "EXTENDING", "in play: its seed queued again"
    assert status["h0"] == "failed" and state[laws["other"]] == "STOPPED"
    events = [json.loads(r["payload_json"]) for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic='law_reinstated'").fetchall()]
    ours = sorted(e["candidate_id"] for e in events if e.get("contract") == F.FAILURE_REPAIR_CONTRACT
                  and "reason" in e)
    assert ours == sorted(laws[k] for k in ("interrupted", "storage", "analysis"))
    latest = repo.conn.execute("SELECT rule FROM engine_decisions_latest WHERE candidate_id=?",
                               (laws["storage"],)).fetchone()["rule"]
    assert latest == "failed", "no decision is written: the stop stays in the record as it was made"
    lines = F.render(result)
    assert any("3 law(s) stopped `failed` for those alone are running again" in line for line in lines), lines
    assert any("1 law(s) failed again where they were given back" in line for line in lines), lines
    assert any("2 law(s) stay stopped `failed` for failures of their own" in line
               and "exception:ValueError" in line and "memory_hard_stop" in line for line in lines), lines

    repo.conn.execute("UPDATE jobs SET status='failed',error=? WHERE job_id='b0'", (_stopped("no_result"),))
    _stop(repo, campaign, laws["storage"], 65536)
    again = F.repair(repo)
    assert laws["storage"][:10] in [e["law"] for e in again["laws_again"]], "once per rung"
    assert again["laws_reinstated"] == []


def _failed_analysis(repo, campaign, law, artifact, version, error_class):
    _job(repo, campaign, law, f"{artifact[:4]}-job", status="done")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", OLD))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,error,error_class,attempts,created_utc,updated_utc) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, artifact, version, law, 65536, 0, f"{artifact[:4]}-job", "failed", "failed",
                       error_class, 3, OLD, OLD))
    _stop(repo, campaign, law, 65536)


def test_analyses_are_read_under_their_campaigns_contract_and_a_dead_worker_is_the_fleets(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION as CURRENT_ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    repo, current = world
    legacy_version = "analysis-5.1.0"
    legacy = str(repo.create_campaign({"name": "resumed on its own contract", "analysis_version": legacy_version},
                                      search_seed=8)["campaign_id"])
    assert repo.campaign_analysis_contract(legacy) == legacy_version
    laws = {name: f"{i}{name}".ljust(64, "0") for i, name in enumerate(("died", "other_contract", "deterministic"))}
    for name, campaign in (("died", legacy), ("other_contract", legacy), ("deterministic", current)):
        repo.insert_candidate(laws[name], campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, legacy, laws["died"], "1" * 64, legacy_version, "lease_expired")
    _failed_analysis(repo, legacy, laws["other_contract"], "2" * 64, CURRENT_ANALYSIS_VERSION,
                     "child_process:missing_success_receipt")
    _failed_analysis(repo, current, laws["deterministic"], "3" * 64, CURRENT_ANALYSIS_VERSION,
                     "analysis_exception:OSError")
    seen = F.survey(repo)
    assert [e["law"] for e in seen["reinstate"]] == [laws["died"][:10]], seen
    assert [e["law"] for e in seen["left"]] == [laws["deterministic"][:10]], "the same input fails the same way"
    named = {e["law"] for key in ("running", "reinstate", "again", "left") for e in seen[key]}
    assert laws["other_contract"][:10] not in named, "not its campaign's contract: nothing it is decided on"


def test_a_base_block_rung_run_again_is_given_the_base_blocks_rank_at_the_start(world):
    from graph_scale_dynamics.db.decision_store import queue_priority
    from graph_scale_dynamics.decisions.decider import QUEUE_ORDER
    from graph_scale_dynamics.operations import queue_ranks
    repo, campaign = world
    law = _law(20)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    second = queue_priority(QUEUE_ORDER[2], 4096)
    _job(repo, campaign, law, "longer-0", n=4096, priority=second, stage="longer_n4096_x32")
    _job(repo, campaign, law, "longer-1", n=4096, seed=1, priority=second, stage="longer_n4096_x32", status="done")
    _job(repo, campaign, law, "bought-0", n=16384, priority=queue_priority(QUEUE_ORDER[2], 16384))
    _job(repo, campaign, law, "base-0", n=1024, priority=queue_priority(QUEUE_ORDER["base"], 1024))
    result = queue_ranks.repair(repo)
    ranks = {r["job_id"]: int(r["priority"]) for r in repo.conn.execute("SELECT job_id,priority FROM jobs").fetchall()}
    assert ranks["longer-0"] == queue_priority(QUEUE_ORDER["base"], 4096), "a base-block rung waits at its rank"
    assert ranks["longer-1"] == second, "a seed already run keeps its record"
    assert ranks["bought-0"] == queue_priority(QUEUE_ORDER[2], 16384), "above the base block nothing moves"
    assert ranks["base-0"] == queue_priority(QUEUE_ORDER["base"], 1024)
    assert result["moved"] == {campaign: 1}
    assert queue_ranks.render(result) == [f"queue: 1 seed(s) of base-block rungs run again now wait at the base "
                                          f"block's rank (campaign {campaign}: 1)"]
    assert queue_ranks.repair(repo)["moved"] == {}, "a second start finds nothing to move"


def test_an_analysis_stopped_at_the_memory_ceiling_is_given_back_once_with_the_deepest_ceiling(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    from graph_scale_dynamics.operations import memory_giveback as M
    from graph_scale_dynamics.scheduling.memory import given_back_limit_bytes, process_stop_bytes
    repo, campaign = world
    law = _law(30)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, campaign, law, "m" * 64, ANALYSIS_VERSION, M.MEMORY_CEILING_CLASS)
    result = F.repair(repo)
    assert result["memory_given_back"] == 1 and [e["law"] for e in result["laws_reinstated"]] == [law[:10]]
    row = repo.conn.execute("SELECT status,error_class FROM analysis_queue WHERE input_artifact=?",
                            ("m" * 64,)).fetchone()
    assert (row["status"], row["error_class"]) == ("queued", M.GIVEN_BACK_CLASS)
    assert any("given back once" in line for line in F.render(result))

    repo.conn.execute("UPDATE analysis_queue SET status='leased' WHERE input_artifact=?", ("m" * 64,))
    job = {"campaign_id": campaign, "n": 65536, "spec": {}, "memory_reservation_bytes": 1024 ** 3}
    limit, kind = M.analysis_stop_bytes(repo, job, "m" * 64)
    assert limit == given_back_limit_bytes() and kind.startswith("given back")
    assert M.analysis_stop_bytes(repo, job, "n" * 64) == process_stop_bytes({}, 65536, 1024 ** 3), \
        "any other analysis stops as before"

    repo.conn.execute("UPDATE analysis_queue SET status='failed',error_class=? WHERE input_artifact=?",
                      (M.MEMORY_CEILING_CLASS, "m" * 64))
    _stop(repo, campaign, law, 65536)
    again = F.repair(repo)
    assert again["memory_given_back"] == 0 and again["laws_reinstated"] == []
    assert [e["own"] for e in again["laws_left"]] == [[M.MEMORY_CEILING_CLASS]]


def test_the_engine_counts_a_laws_failed_analyses_under_its_campaigns_contract(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION as CURRENT_ANALYSIS_VERSION
    repo, _ = world
    legacy_version = "analysis-5.1.0"
    legacy = str(repo.create_campaign({"name": "its own contract", "analysis_version": legacy_version},
                                      search_seed=9)["campaign_id"])
    counted, ignored = _law(40), _law(41)
    for law in (counted, ignored):
        repo.insert_candidate(law, legacy, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, legacy, counted, "p" * 64, legacy_version, "exception:ValueError")
    _failed_analysis(repo, legacy, ignored, "q" * 64, CURRENT_ANALYSIS_VERSION, "exception:ValueError")

    class _Log:
        def write(self, *_args, **_kwargs):
            pass

    store = DecisionStore(repo, _Log(), repo.campaign(legacy))
    assert store.analysis_contract(legacy) == legacy_version
    assert store.law_evidence(legacy, counted)["failed_analyses"] == {65536: 1}
    assert "failed_analyses" not in store.law_evidence(legacy, ignored)


def _attempt(repo, campaign, artifact, version, number, error_class, started):
    repo.conn.execute("INSERT INTO analysis_attempts(analysis_attempt_id,campaign_id,input_artifact,analysis_version,"
                      "attempt_number,started_utc,finished_utc,error,error_class) VALUES(?,?,?,?,?,?,?,?,?)",
                      (f"{artifact[:6]}-{number}", campaign, artifact, version, number, started, started,
                       error_class, error_class))


def test_a_giveback_that_lost_its_room_is_rescued_once(world):
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    from graph_scale_dynamics.operations import memory_giveback as M
    repo, campaign = world
    law, kept = _law(50), _law(51)
    for each in (law, kept):
        repo.insert_candidate(each, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, campaign, law, "r" * 64, ANALYSIS_VERSION, M.MEMORY_CEILING_CLASS)
    _failed_analysis(repo, campaign, kept, "k" * 64, ANALYSIS_VERSION, M.MEMORY_CEILING_CLASS)
    first = F.repair(repo)
    assert first["memory_given_back"] == 2 and len(first["laws_reinstated"]) == 2
    later = utc_now()
    _attempt(repo, campaign, "r" * 64, ANALYSIS_VERSION, 1, "analysis_exception", later)
    _attempt(repo, campaign, "r" * 64, ANALYSIS_VERSION, 2, M.MEMORY_CEILING_CLASS, later)
    _attempt(repo, campaign, "k" * 64, ANALYSIS_VERSION, 1, M.MEMORY_CEILING_CLASS, later)
    for artifact, each in (("r" * 64, law), ("k" * 64, kept)):
        repo.conn.execute("UPDATE analysis_queue SET status='failed',error_class=? WHERE input_artifact=?",
                          (M.MEMORY_CEILING_CLASS, artifact))
        _stop(repo, campaign, each, 65536)
    second = F.repair(repo)
    assert [e["law"] for e in second["laws_reinstated"]] == [law[:10]], second
    assert [e["law"] for e in second["laws_left"]] == [kept[:10]], "with its room, the stop was the law's"
    kinds = [json.loads(r["payload_json"]).get("kind") for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic=? ORDER BY created_utc", (M.EVENT_TOPIC,)).fetchall()]
    assert kinds.count(M.KIND_RESCUE) == 1

    _attempt(repo, campaign, "r" * 64, ANALYSIS_VERSION, 3, "analysis_exception", utc_now())
    repo.conn.execute("UPDATE analysis_queue SET status='failed',error_class=? WHERE input_artifact=?",
                      (M.MEMORY_CEILING_CLASS, "r" * 64))
    _stop(repo, campaign, law, 65536)
    third = F.repair(repo)
    assert third["laws_reinstated"] == [] and law[:10] in [e["law"] for e in third["laws_left"]]


def test_an_analysis_given_back_and_claimed_as_the_analyzer_claims_it_keeps_its_room(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    from graph_scale_dynamics.operations import memory_giveback as M
    repo, campaign = world
    law = _law(60)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, campaign, law, "w" * 64, ANALYSIS_VERSION, M.MEMORY_CEILING_CLASS)
    result = F.repair(repo)
    assert result["memory_given_back"] == 1
    row = repo.conn.execute("SELECT status,error_class,attempts,max_attempts FROM analysis_queue WHERE input_artifact=?",
                            ("w" * 64,)).fetchone()
    repo.conn.execute("UPDATE campaigns SET status='active',workers_target=1 WHERE campaign_id=?", (campaign,))
    job = repo.claim_analysis_job("analyzer-625", ANALYSIS_VERSION, campaign_id=campaign)
    assert job is not None, dict(row)
    assert job["result_artifact"] == "w" * 64
    assert M.is_given_back(repo, job, job["result_artifact"]), dict(row)


def test_a_simulation_given_back_keeps_its_room_when_it_is_run_again(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import failure_repair as F
    from graph_scale_dynamics.operations import memory_giveback as M
    repo, campaign = world
    law = _law(70)
    lost, replay = "x" * 64, "y" * 64
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _failed_analysis(repo, campaign, law, lost, ANALYSIS_VERSION, M.MEMORY_CEILING_CLASS)
    assert F.repair(repo)["memory_given_back"] == 1
    repo.conn.execute("UPDATE analysis_queue SET status='failed',error='TRANSIENT_RAW_LOST: producer replay queued' "
                      "WHERE input_artifact=?", (lost,))
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (replay, 1, "application/json", None, "{}", OLD))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,attempts,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, replay, ANALYSIS_VERSION, law, 65536, 0, f"{lost[:4]}-job", "queued", 0, OLD, OLD))
    repo.conn.execute("UPDATE campaigns SET status='active',workers_target=1 WHERE campaign_id=?", (campaign,))
    repo.conn.execute("UPDATE campaign_candidates SET state='EXTENDING' WHERE campaign_id=? AND candidate_id=?",
                      (campaign, law))
    job = repo.claim_analysis_job("analyzer-625", ANALYSIS_VERSION, campaign_id=campaign)
    assert job is not None and job["result_artifact"] == replay
    assert M.is_given_back(repo, job, replay), "the seed's room"

    repo.conn.execute("UPDATE analysis_queue SET status='failed',error_class=?,error=?,attempts=3 "
                      "WHERE input_artifact=?", (M.MEMORY_CEILING_CLASS, "memory ceiling", replay))
    _stop(repo, campaign, law, 65536)
    given = F.repair(repo)
    assert [e["law"] for e in given["laws_reinstated"]] == [law[:10]], given
    contracts = [json.loads(r["payload_json"])["contract"] for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic='law_reinstated' ORDER BY created_utc").fetchall()]
    assert contracts[-1] == F.REPLAY_CONTRACT
    kinds = [json.loads(r["payload_json"]).get("kind") for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic=? ORDER BY created_utc", (M.EVENT_TOPIC,)).fetchall()]
    assert kinds[-1] == M.KIND_REPLAYED

    repo.conn.execute("UPDATE analysis_queue SET status='failed',error_class=?,error=? WHERE input_artifact=?",
                      (M.MEMORY_CEILING_CLASS, "memory ceiling", replay))
    _stop(repo, campaign, law, 65536)
    after = F.repair(repo)
    assert after["laws_reinstated"] == [] and law[:10] in [e["law"] for e in after["laws_left"]], after

    longer = "z" * 64
    _job(repo, campaign, law, "longer-job", status="done", stage="longer_n65536_x2")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (longer, 1, "application/json", None, "{}", OLD))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,attempts,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, longer, ANALYSIS_VERSION, law, 65536, 0, "longer-job", "leased", 1, OLD, OLD))
    other = repo.conn.execute("SELECT * FROM jobs WHERE job_id='longer-job'").fetchone()
    assert not M.is_given_back(repo, dict(other), longer), "a longer chain of the same seed is not the lost job's"
    own = {"campaign_id": campaign, "input_artifact": replay, "producer_job": f"{lost[:4]}-job",
           "error_class": "analysis_exception"}
    assert not M.is_replay_due(repo, own, {})
