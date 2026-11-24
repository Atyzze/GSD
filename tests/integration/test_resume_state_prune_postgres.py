from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law-resume".ljust(64, "0")


def test_states_of_finished_jobs_are_removed_and_live_ones_kept(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.artifact_store.resume_state import (
        RESUME_PRUNE_MIN_AGE_SECONDS, prune_resume_states, resume_path, save_resume_state)
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "resume"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        old = time.time() - RESUME_PRUNE_MIN_AGE_SECONDS - 60
        paths = {}
        for index, status in enumerate(("queued", "leased", "done", "failed", "cancelled", "lost")):
            job_id = f"{index:x}".rjust(64, "c")
            repo.insert_job(job_id=job_id, campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                            stage="rung_n1048576", n=1048576, seed=index, replicate=0, spec={}, priority=1,
                            requested_by="test", sealed=False)
            repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
            paths[status] = resume_path(tmp_path, job_id)
            save_resume_state(paths[status], {"contract": "one-shot-resume-1", "checkpoint": {}, "history": []},
                              execution_spec_hash="h")
            os.utime(paths[status], (old, old))
        orphan = resume_path(tmp_path, "d" * 64)
        save_resume_state(orphan, {"contract": "one-shot-resume-1"}, execution_spec_hash="h")
        stray = orphan.with_name(orphan.name + ".123.tmp")
        stray.write_bytes(b"partial")
        for path in (orphan, stray):
            os.utime(path, (old, old))
        young = resume_path(tmp_path, "e" * 64)
        save_resume_state(young, {"contract": "one-shot-resume-1"}, execution_spec_hash="h")

        result = prune_resume_states(repo.conn, tmp_path)
        assert result["removed"] == 3 and result["bytes_removed"] > 0, result
        assert all(paths[s].exists() for s in ("queued", "leased", "failed", "lost", "cancelled")) and young.exists()
        assert not paths["done"].exists()
        assert not orphan.exists() and not stray.exists()
        assert prune_resume_states(repo.conn, tmp_path, keep=("queued", "leased"))["removed"] == 3
        assert paths["queued"].exists() and paths["leased"].exists() and young.exists()
        assert not any(paths[s].exists() for s in ("failed", "lost", "cancelled"))
