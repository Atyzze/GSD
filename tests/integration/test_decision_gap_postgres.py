from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law-decision-gap".ljust(64, "0")
OLD = "2026-09-18T00:00:00Z"
SPEC = json.loads((Path(__file__).resolve().parents[2]
                   / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


@pytest.fixture
def world(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.log import Log
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign(SPEC, search_seed=7)["campaign_id"])
    repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    yield repo, DecisionStore(repo, Log(tmp_path, "controller"), {"spec": SPEC}), campaign
    repo.close()


def _seed(repo, campaign, job, artifact, analysis_status):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage="rung_n64", n=64,
                    seed=1, replicate=0, spec={}, priority=64, requested_by="test", sealed=False)
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job, "{}", OLD))
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (artifact, job))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,status,attempts,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (campaign, artifact, ANALYSIS_VERSION, LAW, 64, 1, job, analysis_status, 8, OLD, OLD))


def test_a_seed_whose_analysis_failed_for_good_stops_the_law(world):
    from graph_scale_dynamics.db.decision_store import evidence_pending_reasons
    from graph_scale_dynamics.decisions.engine import STOP, Policy, decide
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    repo, store, campaign = world
    _seed(repo, campaign, "gap-1", "a" * 64, "failed")
    assert "analysis failed" in evidence_pending_reasons(repo.conn, campaign, LAW, ANALYSIS_VERSION)
    evidence = store.law_evidence(campaign, LAW)
    assert evidence.get("failed_analyses") == {64: 1} and not evidence.get("pending"), evidence
    decision = decide(LAW, [], Policy.from_spec(SPEC), failed_seeds=evidence["failed_seeds"],
                      failed_analyses=evidence["failed_analyses"])
    assert (decision.action, decision.rule, decision.at_n) == (STOP, "failed", 64)
    assert "could not be analysed" in decision.reason


def test_a_failed_analysis_that_a_later_one_superseded_no_longer_counts(world):
    from graph_scale_dynamics.db.decision_store import evidence_pending_reasons
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    repo, store, campaign = world
    _seed(repo, campaign, "gap-1", "a" * 64, "failed")
    _seed(repo, campaign, "gap-2", "b" * 64, "done")
    assert "analysis failed" not in evidence_pending_reasons(repo.conn, campaign, LAW, ANALYSIS_VERSION)
    assert not store.law_evidence(campaign, LAW).get("failed_analyses")
