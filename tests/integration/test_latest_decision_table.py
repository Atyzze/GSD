from __future__ import annotations

import json
import random

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "latest-contract-v1"}
ACTIONS = [("run_next", "base_block"), ("hold", "unsettled"), ("hold", "deep_lane_full"),
           ("stop", "too_dense"), ("run_next", "d_s_settled")]
DISTINCT_ON = (
    "SELECT DISTINCT ON (candidate_id) campaign_id,candidate_id,decision_id,at_n,next_n,action,rule,reason,"
    "jobs_seen,created_utc FROM engine_decisions WHERE campaign_id=? ORDER BY candidate_id,decision_id DESC")


def _decide(repo, campaign, law, order, action, rule, n):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{order:020d}-{law[-4:]}", law, n, n * 4, action, rule, f"{rule} at {n}", None, None,
         1, 1, False, f"{order}:mark", "decision-engine-2", json.dumps({"plateau": {"stability_score": order % 7}}),
         f"2026-09-24T10:{order % 60:02d}:00Z"))


def test_the_table_agrees_with_the_scan_it_replaced(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        rng = random.Random(513)
        for campaign in ("camp-a", "camp-b"):
            repo.insert_campaign(campaign, SPEC, content_hash(SPEC))
            writes = []
            for i in range(12):
                law = f"{campaign}-law-{i:02d}"
                for k in range(rng.randint(1, 6)):
                    writes.append((law, rng.randrange(10 ** 12)) + ACTIONS[rng.randrange(len(ACTIONS))]
                                  + (64 * 4 ** (k % 4),))
            rng.shuffle(writes)
            for law, order, action, rule, n in writes:
                _decide(repo, campaign, law, order, action, rule, n)
        for campaign in ("camp-a", "camp-b"):
            scanned = {r["candidate_id"]: dict(r) for r in repo.conn.execute(DISTINCT_ON, (campaign,)).fetchall()}
            kept = {r["candidate_id"]: dict(r) for r in repo.conn.execute(
                "SELECT campaign_id,candidate_id,decision_id,at_n,next_n,action,rule,reason,jobs_seen,created_utc "
                "FROM engine_decisions_latest WHERE campaign_id=?", (campaign,)).fetchall()}
            assert kept == scanned
            assert repo.latest_engine_decisions(campaign).keys() == scanned.keys()
    finally:
        repo.close()


def test_a_deleted_campaign_takes_its_latest_decisions_with_it(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        for campaign in ("camp-a", "camp-b"):
            repo.insert_campaign(campaign, SPEC, content_hash(SPEC))
            _decide(repo, campaign, f"{campaign}-law", 1, "hold", "unsettled", 64)
        repo.delete_campaign("camp-a", force=True)
        rows = repo.conn.execute("SELECT campaign_id FROM engine_decisions_latest").fetchall()
        assert [r["campaign_id"] for r in rows] == ["camp-b"]
    finally:
        repo.close()
