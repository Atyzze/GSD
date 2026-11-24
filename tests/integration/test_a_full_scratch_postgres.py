from __future__ import annotations

import gzip
import json
import os
import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

OLD = "2026-09-27T20:00:00Z"
STOPPED_AT = "2026-09-28T01:30:00Z"


def _law(i: int) -> str:
    return f"law-full-{i}".ljust(64, "0")


@pytest.fixture
def world(isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import scratch_relief
    monkeypatch.setattr(scratch_relief, "DISK_KEEP_FREE_BYTES", 0)
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    store = BlobStore(tmp_path / "blobs")
    campaign = str(repo.create_campaign({"name": "full scratch"}, search_seed=5)["campaign_id"])
    yield repo, store, campaign
    repo.close()


def _job(repo, campaign, law, job_id, *, n=16384, seed=0, status="queued", result=None):
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}",
                    n=n, seed=seed, replicate=0, spec={}, priority=n, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status=?,result_artifact=?,updated_utc=? WHERE job_id=?",
                      (status, result, OLD, job_id))


def _body(repo, store, campaign, law, index, storage_class, *, analysis=None):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    digest, size = store.put_json_stream_transient({"index": index, "pad": "x" * (4096 * (index + 1))})
    job = f"job-{storage_class}-{index}"
    _job(repo, campaign, law, job, seed=index, status="done", result=digest)
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (digest, size, "application/json", job, "{}", OLD))
    repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,detail_json,created_utc,"
                      "updated_utc) VALUES(?,?,?,?,?,?)", (digest, storage_class, "transient",
                                                          json.dumps({"storage_tier": "tmpfs"}), OLD, OLD))
    if analysis:
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (campaign, digest, ANALYSIS_VERSION, law, 16384, index, job, analysis, OLD, OLD))
    return digest


def _row(repo, digest):
    return repo.conn.execute("SELECT body_state,detail_json FROM artifact_retention WHERE artifact_hash=?",
                             (digest,)).fetchone()


def test_the_relief_moves_what_waits_to_disk_and_every_reader_still_finds_it(world):
    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    law = _law(0)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    checkpoint = _body(repo, store, campaign, law, 0, "resume_checkpoint")
    waiting = _body(repo, store, campaign, law, 1, "raw_simulation", analysis="queued")
    orphaned = _body(repo, store, campaign, law, 2, "raw_simulation", analysis="cancelled")
    analysed = _body(repo, store, campaign, law, 3, "raw_simulation", analysis="done")
    result = R.spill(repo, store, target_fraction=0.0)
    assert set(result["moved"]) == {"resume_checkpoint", "raw_not_analysed", "raw_waiting"}, result
    for digest in (checkpoint, waiting, orphaned):
        row = _row(repo, digest)
        assert row["body_state"] == "present" and json.loads(row["detail_json"])["storage_tier"] == "durable"
        assert store.verify_durable(digest) and digest not in set(store.iter_transient_digests())
        assert store.get_json(digest, verify=True)["pad"].startswith("x"), "the reader resolves the durable copy"
    assert _row(repo, analysed)["body_state"] == "transient", "an analysed body is retention's, not the relief's"
    again = R.spill(repo, store, target_fraction=0.0)
    assert again["moved"] == {}, "nothing is moved twice"


def test_a_body_leaves_the_ram_only_after_its_move_is_on_disk(world, monkeypatch):
    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    law = _law(0)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    bodies = [_body(repo, store, campaign, law, i, "raw_simulation", analysis="queued") for i in range(2)]
    trail, deleted = [], {}
    execute, delete = repo.conn.execute, store.delete_transient

    def recording(sql, args=()):
        trail.append(" ".join(str(sql).split()))
        return execute(sql, args)

    def deleting(digest):
        deleted[digest] = len(trail)
        return delete(digest)

    monkeypatch.setattr(repo.conn, "execute", recording)
    monkeypatch.setattr(store, "delete_transient", deleting)
    R.spill(repo, store, target_fraction=0.0)
    assert set(bodies) <= set(deleted)
    for digest in bodies:
        last = max(i for i in range(deleted[digest]) if trail[i] == "COMMIT")
        assert trail[last - 1] == "SET LOCAL synchronous_commit = on" and _row(repo, digest)["body_state"] == "present"


def test_nothing_moves_to_a_disk_under_its_floor_and_the_relief_says_so(world, monkeypatch):
    import shutil
    from collections import namedtuple

    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    monkeypatch.setattr(R, "DISK_KEEP_FREE_BYTES", 20 << 30)
    law = _law(0)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    body = _body(repo, store, campaign, law, 0, "raw_simulation", analysis="queued")
    usage = namedtuple("usage", "total used free")
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: (
        usage(100 << 30, 90 << 30, R.DISK_KEEP_FREE_BYTES - 1) if str(path).startswith(str(store.root))
        else real(path)))
    result = R.spill(repo, store, target_fraction=0.0)
    assert result["moved"] == {} and result["refused"] == {"disk_floor": 1}
    assert result["disk_floor"]["keep_free_bytes"] == R.DISK_KEEP_FREE_BYTES
    assert _row(repo, body)["body_state"] == "transient" and body in set(store.iter_transient_digests())
    assert "scratch:disk_floor" in [f["key"] for f in R.findings(dict(R.relieve(repo, store), spilled=result))]


def test_a_saved_state_moves_to_the_disk_root_its_child_reads_and_a_running_ones_stays(world):
    from graph_scale_dynamics.artifact_store.resume_state import load_resume_state, resume_path, save_resume_state
    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    law = _law(1)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    old = time.time() - R.SAVED_STATE_MIN_AGE_SECONDS - 60
    states = {}
    for job, status in (("c" * 64, "queued"), ("d" * 64, "leased")):
        _job(repo, campaign, law, job, n=1048576, status=status)
        states[status] = resume_path(store.volatile_root, job)
        save_resume_state(states[status], {"contract": "one-shot-resume-1", "checkpoint": {}, "history": []},
                          execution_spec_hash="h")
        os.utime(states[status], (old, old))
    result = R.spill(repo, store, target_fraction=0.0)
    assert result["moved"]["saved_state"]["items"] == 1, result
    moved = resume_path(store.root, "c" * 64)
    assert not states["queued"].exists() and moved.exists()
    state, note = load_resume_state(moved, execution_spec_hash="h")
    assert note == "resumed" and state["contract"] == "one-shot-resume-1", "the child's disk fallback reads it"
    with gzip.open(moved, "rt") as handle:
        assert json.load(handle)["execution_spec_hash"] == "h"
    assert states["leased"].exists(), "a running job's state is where its child writes it"


def _attempt(repo, attempt_id, job, number, *, error=None, error_class=None, closed=False):
    repo.record_attempt(attempt_id, job, number, "executor-9-4112281")
    if closed:
        repo.close_attempt(attempt_id, 1, 0, 1.0, error, {}, error_class=error_class)


def _stop(repo, campaign, law, n, rule="failed"):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{time.time_ns():020d}-{law[-6:]}", law, n, None, "stop", rule, f"{rule} at {n}", None, None,
         0, 1, False, "3:mark", "decision-engine-2", "{}", STOPPED_AT))
    repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE campaign_id=? AND candidate_id=?",
                      (campaign, law))


def test_the_repair_gives_back_what_the_crash_loop_took_and_nothing_else(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import scratch_repair as P
    repo, store, campaign = world
    laws = {name: _law(10 + i) for i, name in enumerate(("stopped", "failed_really", "running", "analysis", "other"))}
    for law in laws.values():
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, laws["stopped"], "a0", seed=0, status="lost")
    for k in (1, 2, 3):
        _attempt(repo, f"a0-{k}", "a0", k)
    _job(repo, campaign, laws["stopped"], "a1", seed=1, status="cancelled")
    repo.conn.execute("UPDATE jobs SET updated_utc=? WHERE job_id='a1'", (STOPPED_AT,))
    _job(repo, campaign, laws["stopped"], "a2", seed=2, status="done")
    _stop(repo, campaign, laws["stopped"], 16384)
    _job(repo, campaign, laws["failed_really"], "b0", status="lost")
    _attempt(repo, "b0-1", "b0", 1, error="child terminated by SIGSEGV", error_class="signal:SIGSEGV", closed=True)
    _attempt(repo, "b0-2", "b0", 2)
    _stop(repo, campaign, laws["failed_really"], 16384)
    _job(repo, campaign, laws["running"], "c0", status="lost")
    _attempt(repo, "c0-1", "c0", 1)
    _job(repo, campaign, laws["running"], "c1", seed=1, status="queued")
    repo.conn.execute("UPDATE jobs SET attempts=2 WHERE job_id='c1'")
    _attempt(repo, "c1-1", "c1", 1)
    _attempt(repo, "c1-2", "c1", 2)
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("e" * 64, 1, "application/json", None, "{}", OLD))
    _job(repo, campaign, laws["analysis"], "d0", status="done", result="e" * 64)
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,error,error_class,attempts,created_utc,updated_utc) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, "e" * 64, ANALYSIS_VERSION, laws["analysis"], 16384, 0, "d0", "failed",
                       "child Python exception at staging_io: OSError: [Errno 28] No space left on device",
                       "staging_io:OSError", 3, OLD, OLD))
    _stop(repo, campaign, laws["analysis"], 16384)
    _job(repo, campaign, laws["other"], "e0", status="lost")
    _attempt(repo, "e0-1", "e0", 1)
    _stop(repo, campaign, laws["other"], 16384, rule="too_dense")

    seen = P.survey(repo)
    assert seen["attempts_never_closed"]["count"] == 8
    assert sorted(seen["laws_to_reinstate"]) == sorted([laws["stopped"], laws["analysis"]])

    result = P.repair(repo)
    status = {r["job_id"]: (r["status"], r["attempts"]) for r in repo.conn.execute(
        "SELECT job_id,status,attempts FROM jobs").fetchall()}
    state = {r["candidate_id"]: r["state"] for r in repo.conn.execute(
        "SELECT candidate_id,state FROM campaign_candidates").fetchall()}
    assert status["a0"] == ("queued", 0) and status["a1"] == ("queued", 0) and status["a2"][0] == "done"
    assert state[laws["stopped"]] == "EXTENDING", "reinstated at the rung it was stopped at"
    assert status["b0"][0] == "lost" and state[laws["failed_really"]] == "STOPPED"
    assert status["c0"] == ("queued", 0) and status["c1"] == ("queued", 0) and state[laws["running"]] == "EXTENDING"
    queue = repo.conn.execute("SELECT status,attempts,error FROM analysis_queue WHERE input_artifact=?",
                              ("e" * 64,)).fetchone()
    assert (queue["status"], queue["attempts"], queue["error"]) == ("queued", 0, None)
    assert state[laws["analysis"]] == "EXTENDING"
    assert status["e0"][0] == "lost" and state[laws["other"]] == "STOPPED"
    assert result["laws_reinstated"] == {campaign: 2} and result["attempts_closed"]["attempts"] == 8
    left_open = repo.conn.execute("SELECT COUNT(*) c FROM attempts WHERE finished_utc IS NULL").fetchone()["c"]
    assert left_open == 0
    latest = repo.conn.execute("SELECT rule FROM engine_decisions_latest WHERE candidate_id=?",
                               (laws["stopped"],)).fetchone()["rule"]
    assert latest == "failed", "no decision is written: the stop stays in the record as it was made"
    events = [json.loads(r["payload_json"]) for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic='law_reinstated'").fetchall()]
    assert sorted(e["candidate_id"] for e in events) == sorted([laws["stopped"], laws["analysis"]])
    lines = P.render(result)
    assert any("2 law(s) stopped only for those are running again" in line for line in lines), lines
    assert P.repair(repo)["jobs_requeued"] == 0, "a second start finds nothing left to give back"


def test_a_claim_given_back_for_want_of_space_is_not_spent(world):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    repo, store, campaign = world
    law = _law(30)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, law, "f0", status="leased")
    repo.conn.execute("UPDATE jobs SET attempts=1,lease_owner='w',lease_generation=4 WHERE job_id='f0'")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("f" * 64, 1, "application/json", None, "{}", OLD))
    assert repo.finish_job("f0", "w", 4, "queued", error="no space", spent=False)
    assert repo.conn.execute("SELECT attempts FROM jobs WHERE job_id='f0'").fetchone()["attempts"] == 0
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,lease_owner,claim_token,attempts,created_utc,updated_utc) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, "f" * 64, ANALYSIS_VERSION, law, 16384, 0, "f0", "leased", "w", "t", 3, OLD, OLD))
    outcome = repo.fail_analysis_claim(campaign, "f" * 64, ANALYSIS_VERSION, "w", "t",
                                       error="child could not write", error_class="child_process:no_space_left",
                                       retryable=True)
    row = repo.conn.execute("SELECT status,attempts,next_attempt_utc FROM analysis_queue WHERE input_artifact=?",
                            ("f" * 64,)).fetchone()
    assert outcome["retry"] and row["status"] == "queued" and row["attempts"] == 2, \
        "its third attempt would have failed it for good; it goes back with two"
    assert row["next_attempt_utc"] is not None, "a minute later, not at once"


def test_bodies_no_longer_in_ram_are_walked_past_not_stopped_at(world, monkeypatch):
    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    law = _law(9)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    lost = [_body(repo, store, campaign, law, 40 + i, "resume_checkpoint") for i in range(6)]
    durable = lost[0]
    assert store.spill_transient(durable)
    for digest in lost:
        store.delete_transient(digest)
    real = [_body(repo, store, campaign, law, i, "resume_checkpoint") for i in range(3)]
    result = R.spill(repo, store, target_fraction=0.0, batch=2)
    assert result["moved"]["resume_checkpoint"]["items"] == 3, result
    assert all(_row(repo, d)["body_state"] == "present" for d in real)
    assert result["bodies_not_in_ram"] == {"durable": 1, "lost": 5}
    assert _row(repo, durable)["body_state"] == "present"
    assert all(_row(repo, d)["body_state"] == "transient" for d in lost[1:]), "left for the paths that read them"


def test_a_job_queued_again_for_want_of_space_waits_before_its_next_claim(world):
    repo, store, campaign = world
    law = _law(31)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, law, "f1", status="leased")
    repo.conn.execute("UPDATE jobs SET attempts=1,lease_owner='w',lease_generation=4 WHERE job_id='f1'")
    assert repo.finish_job("f1", "w", 4, "queued", error="no space", spent=False, defer_seconds=120)
    row = repo.conn.execute("SELECT attempts,next_attempt_utc FROM jobs WHERE job_id='f1'").fetchone()
    assert row["attempts"] == 0 and row["next_attempt_utc"] > time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def test_a_job_stopped_for_filling_the_scratch_itself_is_not_given_back_at_the_next_start(world):
    from graph_scale_dynamics.observability.child_diagnostics import NO_SPACE_CLASS, NO_SPACE_STOP_TEXT
    from graph_scale_dynamics.operations import failure_repair as F
    from graph_scale_dynamics.operations import scratch_repair as P
    repo, store, campaign = world
    capped, victim = _law(40), _law(41)
    for law, job in ((capped, "g0"), (victim, "h0")):
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        error = "child could not write: no space left on its filesystem (the RAM scratch); returncode=74"
        if law == capped:
            error += f" [stopped: 7 {NO_SPACE_STOP_TEXT}; its output does not fit the scratch]"
        _job(repo, campaign, law, job, status="failed")
        repo.conn.execute("UPDATE jobs SET error=? WHERE job_id=?", (error, job))
        for k in range(1, 8 if law == capped else 2):
            _attempt(repo, f"{job}-{k}", job, k, error=error, error_class=NO_SPACE_CLASS, closed=True)
        _stop(repo, campaign, law, 16384)
    assert P.survey(repo)["laws_to_reinstate"] == [victim], "a seed the full scratch took is the fleet's"
    P.repair(repo)
    F.repair(repo)
    status = {r["job_id"]: r["status"] for r in repo.conn.execute("SELECT job_id,status FROM jobs").fetchall()}
    state = {r["candidate_id"]: r["state"] for r in repo.conn.execute(
        "SELECT candidate_id,state FROM campaign_candidates").fetchall()}
    assert status["g0"] == "failed" and state[capped] == "STOPPED", "the stop stands"
    assert status["h0"] == "queued" and state[victim] == "EXTENDING"


def test_only_a_full_scratch_that_is_the_seed_s_latest_outcome_is_given_back_and_once_a_rung(world):
    from graph_scale_dynamics.observability.child_diagnostics import NO_SPACE_CLASS
    from graph_scale_dynamics.operations import scratch_repair as P
    repo, store, campaign = world
    since, latest = _law(50), _law(51)
    no_space = "child could not write: no space left on its filesystem (the RAM scratch); returncode=74"
    for law, job in ((since, "k0"), (latest, "m0")):
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        _job(repo, campaign, law, job, status="failed")
        _attempt(repo, f"{job}-1", job, 1, error=no_space, error_class=NO_SPACE_CLASS, closed=True)
        _stop(repo, campaign, law, 16384)
    repo.conn.execute("UPDATE attempts SET started_utc=? WHERE job_id='k0'", (OLD,))
    for k in (2, 3, 4):
        _attempt(repo, f"k0-{k}", "k0", k, error="child terminated by SIGSEGV", error_class="signal:SIGSEGV",
                 closed=True)
    assert P.survey(repo)["laws_to_reinstate"] == [latest]
    assert P.repair(repo)["laws_reinstated"] == {campaign: 1}
    status = {r["job_id"]: r["status"] for r in repo.conn.execute("SELECT job_id,status FROM jobs").fetchall()}
    assert status == {"k0": "failed", "m0": "queued"}, "its own latest failure stands"
    repo.conn.execute("UPDATE jobs SET status='failed' WHERE job_id='m0'")
    _attempt(repo, "m0-2", "m0", 2, error=no_space, error_class=NO_SPACE_CLASS, closed=True)
    _stop(repo, campaign, latest, 16384)
    assert P.survey(repo)["laws_to_reinstate"] == [] and P.repair(repo)["laws_reinstated"] == {}
    state = {r["candidate_id"]: r["state"] for r in repo.conn.execute(
        "SELECT candidate_id,state FROM campaign_candidates").fetchall()}
    assert state[since] == "STOPPED" and state[latest] == "STOPPED"


def test_a_start_keeps_the_saved_state_of_a_seed_its_repair_queues_again(world):
    from graph_scale_dynamics.artifact_store.resume_state import (
        RESUME_PRUNE_MIN_AGE_SECONDS, prune_resume_states, resume_path, save_resume_state)
    from graph_scale_dynamics.operations import scratch_relief as R
    repo, store, campaign = world
    given, kept = _law(60), _law(61)
    old = time.time() - RESUME_PRUNE_MIN_AGE_SECONDS - 60
    states = {}
    for law, job in ((given, "p0"), (kept, "q0")):
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        _job(repo, campaign, law, job, status="lost")
        _attempt(repo, f"{job}-1", job, 1)
        states[job] = resume_path(store.volatile_root, job)
        save_resume_state(states[job], {"contract": "one-shot-resume-1", "checkpoint": {}, "history": []},
                          execution_spec_hash="h")
        os.utime(states[job], (old, old))
    _stop(repo, campaign, kept, 16384, rule="too_dense")
    prune_resume_states(repo.conn, store.volatile_root)
    assert states["p0"].exists() and states["q0"].exists()
    R.at_fleet_start(repo, store, say=lambda line: None)
    status = {r["job_id"]: r["status"] for r in repo.conn.execute("SELECT job_id,status FROM jobs").fetchall()}
    assert status["p0"] == "queued" and states["p0"].exists(), "it resumes from its state"
    assert status["q0"] == "lost" and not states["q0"].exists(), "the start prunes what it did not queue again"


def test_a_full_scratch_s_tries_are_costed_from_their_attempts(world):
    from graph_scale_dynamics.observability.child_diagnostics import NO_SPACE_CLASS
    from graph_scale_dynamics.services.worker.main import no_space_seconds
    repo, store, campaign = world
    law = _law(50)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, law, "k0", n=1048576)
    for number, (cls, wall) in enumerate([("oom_killed", 500.0), (NO_SPACE_CLASS, 40000.0),
                                          (NO_SPACE_CLASS, 50000.0)], start=1):
        repo.record_attempt(f"k0-{number}", "k0", number, "w")
        repo.close_attempt(f"k0-{number}", 74, 0, wall, "no space", {}, error_class=cls)
    assert no_space_seconds(repo, "k0", 1000.0) == 91000.0, "its tries in a row, this one's included, not the OOM's"


def test_a_start_queues_again_at_once_every_seed_the_last_fleet_still_held(world):
    from graph_scale_dynamics.operations import scratch_repair as P
    repo, _, campaign = world
    law = _law(70)
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, law, "held-by-the-dead-fleet", status="leased")
    repo.conn.execute("UPDATE jobs SET lease_owner='executor-3-999',lease_expires_utc='2999-01-01T00:00:00Z',"
                      "attempts=1,memory_reservation_bytes=4096 WHERE job_id='held-by-the-dead-fleet'")
    _attempt(repo, "its-open-attempt", "held-by-the-dead-fleet", 1)
    result = P.repair(repo)
    row = repo.conn.execute("SELECT status,lease_owner,lease_expires_utc,memory_reservation_bytes,attempts FROM jobs "
                            "WHERE job_id='held-by-the-dead-fleet'").fetchone()
    assert (row["status"], row["lease_owner"], row["lease_expires_utc"]) == ("queued", None, None), dict(row)
    assert row["memory_reservation_bytes"] == 0 and row["attempts"] == 0, "the dead fleet's try is not counted"
    attempt = repo.conn.execute("SELECT finished_utc,error_class FROM attempts WHERE attempt_id='its-open-attempt'"
                                ).fetchone()
    assert attempt["finished_utc"] and attempt["error_class"] == "supervisor_interrupted"
    assert result["attempts_closed"]["leases_ended"] == 1
    assert any("queued again at once" in line for line in P.render(result))
