from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

GB = 10 ** 9
GIB = 1 << 30
HOST = 98_746_621_952
DEEP = 1_048_576
HOLD_ASK = 23_915_715_524
OLD = "2026-11-09T07:00:00Z"
STATE_JOB = "e" * 64


@pytest.fixture
def folder(isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import scratch_relief
    from graph_scale_dynamics.scheduling import memory as M
    monkeypatch.setattr(scratch_relief, "DISK_KEEP_FREE_BYTES", 0)
    monkeypatch.setattr(M, "memory_pressure_snapshot",
                        lambda: {"available": False, "some_avg10": None, "full_avg10": None})
    monkeypatch.delenv("GSD_HOST_MEMORY_FLOOR_BYTES", raising=False)
    M.reset_prediction_caches()
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    store = BlobStore(tmp_path / "blobs")
    campaign = str(repo.create_campaign({"name": "a held seed"}, search_seed=7)["campaign_id"])
    law = "law-held-seed".ljust(64, "0")
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    _job(repo, campaign, law, "deep", n=DEEP, status="queued")
    yield repo, store, campaign, law
    repo.close()
    M.reset_prediction_caches()


def _job(repo, campaign, law, job_id, *, n, status, seed=0, result=None):
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}", n=n,
                    seed=seed, replicate=0, spec={}, priority=200_000_000 + n, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status=?,result_artifact=? WHERE job_id=?", (status, result, job_id))


def _body(repo, store, campaign, law, index, storage_class, *, analysis=None, n=262144):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    payload = {"index": index, "pad": os.urandom(4096 * (index + 1)).hex()}
    digest, size = store.put_json_stream_transient(payload)
    job = f"job-{storage_class}-{index}"
    _job(repo, campaign, law, job, n=n, seed=index, status="done", result=digest)
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (digest, size, "application/json", job, "{}", OLD))
    repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,detail_json,created_utc,"
                      "updated_utc) VALUES(?,?,?,?,?,?)", (digest, storage_class, "transient",
                                                          json.dumps({"storage_tier": "tmpfs"}), OLD, OLD))
    if analysis:
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (campaign, digest, ANALYSIS_VERSION, law, n, index, job, analysis, OLD, OLD))
    return digest, payload


def _in_ram(store) -> int:
    held = sum(p.stat().st_size for p in Path(store.transient_root).rglob("*") if p.is_file())
    resume = Path(store.volatile_root) / "resume"
    return held + (sum(p.stat().st_size for p in resume.glob("*.json.gz")) if resume.is_dir() else 0)


def _host(monkeypatch, available: int) -> None:
    from graph_scale_dynamics.scheduling import memory as M
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=HOST, available=int(available)))


def test_under_a_hold_the_scratch_at_52_percent_gives_way_and_every_reader_finds_its_file_on_disk(folder,
                                                                                                    monkeypatch):
    from graph_scale_dynamics.artifact_store.resume_state import load_resume_state, resume_path, save_resume_state
    from graph_scale_dynamics.operations import compute_ecology as E
    from graph_scale_dynamics.operations import scratch_relief as R
    from graph_scale_dynamics.scheduling import memory_hold as H
    repo, store, campaign, law = folder
    assert R.tmpfs(store), "the store's RAM tier is a tmpfs here, as on the host"
    checkpoint, kept = _body(repo, store, campaign, law, 0, "resume_checkpoint")
    waiting, payload = _body(repo, store, campaign, law, 1, "raw_simulation", analysis="queued", n=DEEP)
    orphan, unread = _body(repo, store, campaign, law, 2, "raw_simulation")
    analysed, _ = _body(repo, store, campaign, law, 3, "raw_simulation", analysis="done")
    _job(repo, campaign, law, STATE_JOB, n=DEEP, status="queued")
    state_path = resume_path(store.volatile_root, STATE_JOB)
    save_resume_state(state_path, {"contract": "one-shot-resume-1", "checkpoint": {}, "history": []},
                      execution_spec_hash="h")
    old = time.time() - R.SAVED_STATE_MIN_AGE_SECONDS - 60
    os.utime(state_path, (old, old))
    analysed_bytes = Path(store._transient_path(analysed)).stat().st_size
    movable = _in_ram(store) - analysed_bytes
    size = int(movable / (0.524 - R.LOW_WATER))
    offset = int(R.LOW_WATER * size) - analysed_bytes - 1

    def usage(path):
        used = offset + _in_ram(store)
        return {"total_bytes": size, "used_bytes": used, "free_bytes": size - used, "fraction": used / size}

    monkeypatch.setattr(R, "usage", usage)
    assert round(usage(None)["fraction"], 3) == 0.524
    assert R.relieve(repo, store)["spilled"] is None, "748: at 52% nothing moves, held seed or not"
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=HOLD_ASK)["new"]
    short = R.shortage(repo.conn)
    assert short["why"] == "a hold for a 1,048,576 seed asking 22.3 GiB"
    relief = R.relieve(repo, store, pressed=short["why"])
    moved = relief["spilled"]["moved"]
    assert {k: v["items"] for k, v in moved.items()} == {"resume_checkpoint": 1, "raw_waiting": 1,
                                                         "raw_not_analysed": 1, "saved_state": 1}, moved
    assert usage(None)["fraction"] <= R.LOW_WATER and not relief["relieving"]
    for digest, body in ((checkpoint, kept), (waiting, payload), (orphan, unread)):
        row = repo.artifact_retention(digest)
        assert row["body_state"] == "present" and row["detail"]["storage_tier"] == "durable"
        assert digest not in set(store.iter_transient_digests()) and store.verify_durable(digest)
        assert store.get_json(digest, verify=True) == body, "a checkpoint or result is read from its disk copy"
    assert repo.artifact_retention(analysed)["body_state"] == "transient", "an analysed body stays retention's"
    state, note = load_resume_state(resume_path(store.root, STATE_JOB), execution_spec_hash="h")
    assert note == "resumed" and not state_path.exists(), "a resume finds its saved state on disk"
    from graph_scale_dynamics.services.analyzer.main import claim_analysis_for_owner
    claimed = claim_analysis_for_owner(repo, "executor-1-1")
    assert claimed["result_artifact"] == waiting
    assert repo.artifact_retention(waiting)["body_state"] != "transient", "so the analyzer replays nothing"
    published = R.publish(repo, store, relief)
    assert published["movable_bytes"] == 0 and published["doing"].startswith("moved ")
    assert "because admission is short (a hold for a 1,048,576 seed asking 22.3 GiB)" in published["doing"]
    _host(monkeypatch, 30_231_543_808)
    reach = H.reach(repo.conn)
    assert reach["scratch_read"] and reach["reach_bytes"] == 30_231_543_808 - 10 * GIB < HOLD_ASK
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=HOLD_ASK,
                   reach=lambda: H.reach(repo.conn)) is None
    row = H.read(repo.conn)
    assert (row["state"], row["ended"]) == ("ended", "cannot fit")
    ended = [json.loads(r["payload_json"]) for r in repo.conn.execute(
        "SELECT payload_json FROM events WHERE topic='memory_hold_ended' ORDER BY event_id").fetchall()]
    assert [(e["why"], e["reach_bytes"]) for e in ended] == [("cannot fit", reach["reach_bytes"])]
    said = E.room_reading(E.memory_room(repo.conn, {"available_bytes": 30_231_543_808, "floor_bytes": 10 * GIB}))
    assert "A 1,048,576 seed asks 22.3 GiB; with the RAM scratch spilled and nothing running, this host gives at " \
           "most 18.2 GiB" in said, said


def test_a_claimable_analysis_is_admitted_beside_a_hold_and_a_simulation_still_leaves_the_room(folder,
                                                                                                monkeypatch):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.scheduling import memory_hold as H
    from graph_scale_dynamics.services.analyzer.main import claim_analysis_for_owner
    repo, store, campaign, law = folder
    raw, _ = _body(repo, store, campaign, law, 1, "raw_simulation", analysis="queued", n=DEEP)
    _job(repo, campaign, law, "other-deep", n=DEEP, status="queued")
    _host(monkeypatch, 10 * GIB + int(21.1 * GB))
    assert H.start(repo.conn, job_id="deep", campaign_id=campaign, n=DEEP, requested_bytes=HOLD_ASK)["new"]
    claimed = claim_analysis_for_owner(repo, "executor-1-1")
    assert claimed["result_artifact"] == raw
    ask = M._deterministic_fallback_peak_bytes({}, DEEP, "analysis")
    verdict = M.locked_admission(repo, kind="analysis", reservation_bytes=ask,
                                 hard_single_job_bytes=M.hard_process_limit_bytes({}, n=DEEP),
                                 campaign_id=claimed["campaign_id"], artifact=raw, analysis_version=ANALYSIS_VERSION,
                                 owner="executor-1-1", claim_token=claimed["analysis_claim_token"])
    assert verdict["within_budget"] and verdict["held_bytes"] == 0, "748: budget 0 beside a 23.9 GB hold"
    assert round(verdict["budget"] / GB, 1) == 21.1
    assert repo.conn.execute("SELECT memory_reservation_bytes b FROM analysis_queue WHERE input_artifact=?",
                             (raw,)).fetchone()["b"] == ask
    sim = repo.claim_job("executor-2-1", ("simulate",), job_id="other-deep")
    refused = M.locked_admission(repo, kind="simulation", reservation_bytes=int(6.6 * GB), job_id="other-deep",
                                 owner="executor-2-1", lease_generation=int(sim["lease_generation"]))
    assert refused["refusal"] == "transient_memory_floor" and refused["held_bytes"] == HOLD_ASK
    assert H.active(repo.conn)["job_id"] == "deep", "the hold stands for its seed"
