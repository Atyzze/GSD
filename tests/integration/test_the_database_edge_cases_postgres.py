from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
LAW = "l30".ljust(64, "0")


def test_a_start_leaves_an_unchanged_analysis_row_as_it_was(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        repo.insert_job(job_id="j-l30".ljust(64, "j"), campaign_id=campaign_id, candidate_id=LAW, kind="simulate",
                        stage="rung_n64", n=64, seed=0, replicate=0, spec={}, priority=64, requested_by="decider",
                        sealed=False)
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)",
                          ("art-l30", 1, "application/json", "j-l30".ljust(64, "j"), "{}", "2026-10-29T00:00:00Z"))
        repo.conn.execute("UPDATE jobs SET status='done', result_artifact='art-l30' WHERE job_id=?",
                          ("j-l30".ljust(64, "j"),))
        assert repo.ensure_analysis_queue(ANALYSIS_VERSION) == 1
        repo.conn.execute("UPDATE analysis_queue SET updated_utc='2026-10-01T00:00:00Z'")
        assert repo.ensure_analysis_queue(ANALYSIS_VERSION) == 0
        row = repo.conn.execute("SELECT status, updated_utc FROM analysis_queue").fetchone()
        assert (row["status"], row["updated_utc"]) == ("queued", "2026-10-01T00:00:00Z")
        repo.conn.execute("UPDATE analysis_queue SET status='cancelled'")
        assert repo.ensure_analysis_queue(ANALYSIS_VERSION) == 1, "a cancelled row still comes back"
