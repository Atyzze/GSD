from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law-retention".ljust(64, "0")
OLD, NEW = "2026-09-01T00:00:00Z", "2026-09-18T00:00:00Z"


@pytest.fixture
def world(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    store = BlobStore(tmp_path / "blobs")
    campaign = str(repo.create_campaign({"name": "retention"}, search_seed=3)["campaign_id"])
    repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    yield repo, store, campaign
    repo.close()


def _analysed_body(repo, store, campaign, index, *, raw=None, compact=True, checkpoint_state="evicted",
                   updated=NEW):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    job = f"job-{index:04d}"
    if raw is None:
        raw, size = store.put_json_stream_transient({"index": index, "pad": "x" * 2048})
    else:
        size = 1
    compact_digest = store.put_json({"compact": index})[0] if compact else "d" + f"{index:063x}"
    checkpoint = "c" + f"{index:063x}"
    repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage="rung_n64",
                    n=64, seed=index, replicate=0, spec={}, priority=64, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (raw, job))
    for digest, length in ((raw, size), (compact_digest, 1), (checkpoint, 1)):
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)", (digest, length, "application/json", job, "{}", OLD))
    repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,created_utc,updated_utc) "
                      "VALUES(?,?,?,?,?)", (checkpoint, "resume_checkpoint", checkpoint_state, OLD, OLD))
    repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,checkpoint_artifact,"
                      "compact_artifact,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?)",
                      (raw, "raw_simulation", "transient", checkpoint, compact_digest, OLD, updated))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (campaign, raw, ANALYSIS_VERSION, LAW, 64, index, job, "done", OLD, OLD))
    repo.conn.execute("INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,"
                      "input_artifact,metrics_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                      (campaign, f"analysis-{index:04d}", LAW, 64, index, ANALYSIS_VERSION, raw, "{}", OLD))
    return raw


def _state(repo, digest):
    return repo.conn.execute("SELECT body_state FROM artifact_retention WHERE artifact_hash=?",
                             (digest,)).fetchone()["body_state"]


def test_an_evicted_checkpoint_no_longer_holds_its_raw_body(world):
    from graph_scale_dynamics.operations.artifact_retention import online_retention_tick
    repo, store, campaign = world
    bodies = [_analysed_body(repo, store, campaign, i) for i in range(3)]
    assert set(bodies) <= set(store.iter_transient_digests()), "three bodies on tmpfs before the tick"
    tick = online_retention_tick(repo, store, cursor={})
    assert tick["transient_completed_cleanup"]["evicted"] == 3, tick
    assert [_state(repo, d) for d in bodies] == ["evicted"] * 3
    assert not set(bodies) & set(store.iter_transient_digests()), "their tmpfs files are gone"


def test_a_body_that_cannot_be_evicted_does_not_block_the_ones_behind_it(world):
    from graph_scale_dynamics.operations.artifact_retention import online_retention_tick
    repo, store, campaign = world
    for i in range(20):
        _analysed_body(repo, store, campaign, i, raw=f"{i:064x}", compact=False, updated=OLD)
    free = [_analysed_body(repo, store, campaign, 100 + i) for i in range(5)]
    cursor: dict = {}
    refused = 0
    for _ in range(3):
        tick = online_retention_tick(repo, store, cursor=cursor)
        refused += sum(tick["transient_completed_cleanup"]["refused"].values())
    assert [_state(repo, d) for d in free] == ["evicted"] * 5
    assert refused >= 20, "the refused bodies are still tried, once per cycle, and counted"
    assert _state(repo, f"{0:064x}") == "transient", "a body that may not go stays"


def test_a_body_is_deleted_only_after_its_eviction_is_on_disk(world, monkeypatch):
    from graph_scale_dynamics.operations.artifact_retention import online_retention_tick
    repo, store, campaign = world
    bodies = [_analysed_body(repo, store, campaign, i) for i in range(2)]
    setting = repo.conn.execute("SHOW synchronous_commit").fetchone()["synchronous_commit"]
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
    online_retention_tick(repo, store, cursor={})
    assert [_state(repo, d) for d in bodies] == ["evicted"] * 2 and set(bodies) <= set(deleted)
    for digest in bodies:
        last = max(i for i in range(deleted[digest]) if trail[i] == "COMMIT")
        assert trail[last - 1] == "SET LOCAL synchronous_commit = on", "its eviction reached the disk first"
    monkeypatch.undo()
    assert repo.conn.execute("SHOW synchronous_commit").fetchone()["synchronous_commit"] == setting, (
        "the setting is the transaction's own")
