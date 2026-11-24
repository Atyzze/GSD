from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.services.api import campaign_manager

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "chains-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}]}


def test_the_deepest_rung_reading_is_the_one_counted(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        repo.insert_campaign("camp", SPEC, content_hash(SPEC))
        rows = [("law-a", 64, "agreeing"), ("law-a", 256, "frozen"),
                ("law-b", 64, "converging"),
                ("law-c", 64, None)]
        for law in {"law-a", "law-b", "law-c"}:
            repo.insert_candidate(law, "camp", LAW, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        for law, n, reading in rows:
            body = {"contract": "rung-chain-mixing-2"}
            if reading:
                body["meeting_reading"] = {"reading": reading}
            repo.conn.execute("INSERT INTO rung_diagnostics(campaign_id,candidate_id,n,analysis_version,contract,"
                              "diagnostics_json,created_utc) VALUES(?,?,?,?,?,?,?)",
                              ("camp", law, n, "chains-contract-v1", body["contract"], json.dumps(body), "t"))
        row = next(r for r in campaign_manager.overview(repo)["campaigns"] if r["campaign_id"] == "camp")
        assert row["meeting_readings"] == {"frozen": 1, "converging": 1}
    finally:
        repo.close()
