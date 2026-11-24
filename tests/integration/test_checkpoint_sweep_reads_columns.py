from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.operations.artifact_retention import _checkpoint_eviction_candidates

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "sweep-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}]}


def _run(repo, law, job, *, sweeps=1, locality=None, status="done", resume=None):
    execution = {"one_shot": True, "sweeps_multiplier": sweeps}
    if locality is not None:
        execution["proposal_locality"] = locality
    if resume is not None:
        execution["resume_artifact"] = resume
    repo.insert_job(job_id=job, campaign_id="camp", candidate_id=law, kind="simulate", stage="base", n=64,
                    seed=0, replicate=0, spec={"candidate_spec": LAW, "execution": execution}, priority=10,
                    sealed=False, requested_by="sweep-contract")
    if status == "done":
        raw, cp = f"raw-{job}", f"cp-{job}"
        for artifact in (cp, raw):
            repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,created_utc) "
                              "VALUES(?,?,?,?)", (artifact, 100, "application/gzip", "t"))
        repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,created_utc,"
                          "updated_utc) VALUES(?,?,?,?,?)", (cp, "resume_checkpoint", "present", "t", "t"))
        repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,"
                          "checkpoint_artifact,created_utc,updated_utc) VALUES(?,?,?,?,?,?)",
                          (raw, "raw_simulation", "present", cp, "t", "t"))
        repo.conn.execute("UPDATE jobs SET status='done',result_artifact=? WHERE job_id=?", (raw, job))
        return cp


def test_which_checkpoints_the_sweep_may_take(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        for law, state in (("law-stopped", "STOPPED"), ("law-longer", "BASE_BLOCK_RUNNING"),
                           ("law-alone", "BASE_BLOCK_RUNNING"), ("law-other-sampler", "BASE_BLOCK_RUNNING"),
                           ("law-resumed", "BASE_BLOCK_RUNNING")):
            repo.insert_candidate(law, "camp", LAW, "equilibrium", 1, state)
        stopped = _run(repo, "law-stopped", "j-stopped")
        superseded = _run(repo, "law-longer", "j-short")
        _run(repo, "law-longer", "j-long", sweeps=2)
        alone = _run(repo, "law-alone", "j-alone")
        other = _run(repo, "law-other-sampler", "j-plain")
        _run(repo, "law-other-sampler", "j-audit", sweeps=2, locality="0.5")
        resumed = _run(repo, "law-resumed", "j-resumed-old")
        _run(repo, "law-resumed", "j-resumed-new", sweeps=2)
        _run(repo, "law-resumed", "j-resumer", status="queued", resume=resumed)
        taken = {row["artifact_hash"] for row in _checkpoint_eviction_candidates(repo, limit=100)}
        assert stopped in taken and superseded in taken
        assert alone not in taken, "an active law's only checkpoint is its continuation"
        assert other not in taken, "a run under another sampler does not supersede it"
        assert resumed not in taken, "a queued job still resumes from it"
        row = repo.conn.execute("SELECT exec_sweeps_multiplier,exec_proposal_locality,exec_resume_artifact "
                                "FROM jobs WHERE job_id='j-resumer'").fetchone()
        assert (row["exec_sweeps_multiplier"], row["exec_proposal_locality"], row["exec_resume_artifact"]) == (
            1, "0", resumed)
    finally:
        repo.close()
