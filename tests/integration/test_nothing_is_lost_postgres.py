from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "nothing-lost-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def _campaign(dsn: str) -> Repo:
    init_db(dsn)
    repo = Repo(dsn)
    repo.insert_campaign("camp-a", SPEC, content_hash(SPEC))
    for law, state in (("law-live", "BASE_BLOCK_RUNNING"), ("law-stopped", "STOPPED")):
        repo.insert_candidate(law, "camp-a", LAW, "metropolis", 1, state)
        repo.insert_job(job_id=f"job-{law}", campaign_id="camp-a", candidate_id=law, kind="simulate", stage="base",
                        n=64, seed=0, replicate=0, spec={"candidate_spec": LAW}, priority=10, sealed=False,
                        requested_by="nothing-lost")
    return repo


def _status(repo: Repo, job: str) -> str:
    return repo.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job,)).fetchone()["status"]


def test_a_reopen_gives_the_live_laws_back_the_work_the_close_cancelled(isolated_postgres_schema):
    repo = _campaign(isolated_postgres_schema.dsn)
    try:
        repo.conn.execute("UPDATE jobs SET status='cancelled',updated_utc='2026-01-01T00:00:00Z' "
                          "WHERE job_id='job-law-stopped'")
        assert repo.stop_campaign_work("camp-a")["jobs_cancelled"] == 1
        assert _status(repo, "job-law-live") == "cancelled"
        revived = repo.revive_stopped_work("camp-a")
        assert revived["jobs"] == 1 and _status(repo, "job-law-live") == "queued", "the live law's rung runs again"
        assert _status(repo, "job-law-stopped") == "cancelled", "a law the engine stopped stays stopped"
        assert repo.revive_stopped_work("camp-a")["jobs"] == 0, "and nothing twice"
    finally:
        repo.close()


def test_an_archived_run_s_chain_record_is_never_garbage(isolated_postgres_schema):
    from graph_scale_dynamics.operations import artifact_gc as G
    from graph_scale_dynamics.operations.campaign_archive import CHAIN_RECORD_KEY
    repo = _campaign(isolated_postgres_schema.dsn)
    try:
        record = "r" * 64
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)",
                          (record, 10, "application/x-xz", "job-law-live", "{}", "2026-10-01T00:00:00Z"))

        def garbage() -> set:
            return {str(r["artifact_hash"]) for r in repo.conn.execute(
                f"SELECT a.artifact_hash FROM artifacts a WHERE {G._UNREFERENCED}").fetchall()}

        assert record in garbage(), "nothing references it: what the archive's cascade left until 658"
        repo.conn.execute("INSERT INTO campaign_archives(campaign_id,archive_version,state,source_status,spec_json,"
                          "spec_hash,created_utc) VALUES(?,?,?,?,?,?,?)",
                          ("camp-a", "campaign-archive-v1", "complete", "closed", json.dumps(SPEC), content_hash(SPEC),
                           "2026-10-01T00:00:00Z"))
        repo.conn.execute(
            "INSERT INTO campaign_archive_runs(campaign_id,job_id,candidate_id,n,seed,replicate,source_artifact,"
            "source_size_bytes,verified,compact_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("camp-a", "job-law-live", "law-live", 64, 0, 0, "s" * 64, 1, 1,
             json.dumps({"schema": "compact-simulation-evidence-v1", CHAIN_RECORD_KEY: record}),
             "2026-10-01T00:00:00Z"))
        assert record not in garbage(), "the archive keeps every seed's chain record, as it promises"
    finally:
        repo.close()


def test_an_archive_with_an_error_retires_nothing_even_when_asked_to_run_to_the_end(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.operations.campaign_archive import archive_campaign
    repo = _campaign(isolated_postgres_schema.dsn)
    try:
        repo.conn.execute("UPDATE jobs SET status='done',result_artifact=? WHERE job_id='job-law-live'", ("m" * 64,))
        with pytest.raises(RuntimeError, match="archive verification failed.*errors=1"):
            archive_campaign(repo, BlobStore(tmp_path / "blobs"), "camp-a", allow_incomplete=True)
        assert repo.conn.execute("SELECT COUNT(*) c FROM campaign_candidates WHERE campaign_id='camp-a'"
                                 ).fetchone()["c"] == 2, "every live row is where it was"
        assert repo.conn.execute("SELECT state FROM campaign_archives WHERE campaign_id='camp-a'"
                                 ).fetchone()["state"] == "incomplete"
    finally:
        repo.close()


def test_retention_waits_while_a_backup_holds_the_maintenance_lock(isolated_postgres_schema):
    from graph_scale_dynamics.operations.maintenance import exclusive_maintenance, unless_maintenance
    init_db(isolated_postgres_schema.dsn)
    backup, retention = Repo(isolated_postgres_schema.dsn), Repo(isolated_postgres_schema.dsn)
    try:
        with exclusive_maintenance(backup):
            with unless_maintenance(retention) as free:
                assert not free, "retention waits out the backup"
        with unless_maintenance(retention) as free:
            assert free
        with unless_maintenance(retention) as free:
            assert free, "and lets the lock go each time"
    finally:
        backup.close()
        retention.close()
