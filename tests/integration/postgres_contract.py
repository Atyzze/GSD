#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.db.connection import connect_database, postgres_schema_dsn
from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash


def scenario(dsn: str) -> dict:
    init_db(dsn)
    init_db(dsn)
    repo = Repo(dsn)
    try:
        queue_types = {
            (row["table_name"], row["column_name"]): row["data_type"]
            for row in repo.conn.execute(
                "SELECT table_name,column_name,data_type FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND "
                "((table_name='jobs' AND column_name='priority') OR "
                "(table_name='analysis_queue' AND column_name='priority'))"
            ).fetchall()
        }
        assert queue_types == {
            ("jobs", "priority"): "bigint",
            ("analysis_queue", "priority"): "bigint",
        }
        trigger_names = {
            row["tgname"]
            for row in repo.conn.execute(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND NOT t.tgisinternal "
                "AND t.tgname IN ('gsd_jobs_work_notify','gsd_analysis_work_notify')"
            ).fetchall()
        }
        assert trigger_names == {"gsd_jobs_work_notify", "gsd_analysis_work_notify"}

        campaign_spec = {"mode": "bounded", "ladder": [256, 1024],
                         "analysis_version": "contract-v1"}
        repo.insert_campaign("camp-contract", campaign_spec, content_hash(campaign_spec))
        candidate_spec = {
            "terms": [{"kind": "edge_count", "coefficient": 0.3}],
            "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2},
        }
        repo.insert_candidate("candidate-contract", "camp-contract", candidate_spec,
                              "metropolis", 1, "DISCOVERY_ACTIVE")
        repo.insert_job(job_id="job-contract", campaign_id="camp-contract",
                        candidate_id="candidate-contract", kind="simulate", stage="PILOT",
                        n=256, seed=7, replicate=0, spec={"candidate_spec": candidate_spec},
                        priority=10, sealed=False, requested_by="contract")
        claimed = repo.claim_job("executor-contract", ("simulate",))
        assert claimed
        assert repo.commit_job_result(
            job_id="job-contract", owner="executor-contract",
            lease_generation=claimed["lease_generation"], digest="a" * 64, size=123,
            media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
            analysis_version="contract-v1",
        )
        analysis = repo.claim_analysis_job("executor-contract", "contract-v1")
        assert analysis
        assert repo.commit_analysis_result(
            campaign_id="camp-contract", input_artifact="a" * 64,
            analysis_version="contract-v1", owner="executor-contract",
            claim_token=analysis["analysis_claim_token"], curves_digest="b" * 64,
            curves_size=321, producer_job="job-contract", analysis_id="analysis-contract",
            candidate_id="candidate-contract", n=256, seed=7,
            metrics={"d_V": {"value": 3.5}}, provenance_status="verified",
            provenance_detail={"contract": True},
        )
        rebuild = repo.claim_candidate_evidence_rebuild(
            "executor-contract", "contract-v1"
        )
        assert rebuild and rebuild["candidate_id"] == "candidate-contract"
        revision = repo.conn.execute(
            "SELECT COUNT(*) c,COALESCE(MAX(created_utc),'') newest FROM measurements "
            "WHERE campaign_id='camp-contract' AND candidate_id='candidate-contract' "
            "AND analysis_version='contract-v1'"
        ).fetchone()
        assert repo.complete_candidate_evidence_rebuild(
            campaign_id="camp-contract", candidate_id="candidate-contract",
            analysis_version="contract-v1", owner="executor-contract",
            claim_token=rebuild["rebuild_claim_token"],
            measurement_count=int(revision["c"]),
            newest_measurement_utc=revision["newest"],
            summaries={256: {"seeds": 1}}, transitions=[],
            diagnostics={256: {"contract": "rung-chain-mixing-1", "seeds": 1}},
        ) == "done"
        diagnostics = repo.rung_diagnostics("camp-contract", "candidate-contract")
        assert [(row["n"], row["contract"], row["diagnostics"]["seeds"]) for row in diagnostics] == [
            (256, "rung-chain-mixing-1", 1)]

        repo.insert_candidate("candidate-failure", "camp-contract", candidate_spec,
                              "metropolis", 1, "DISCOVERY_ACTIVE")
        repo.insert_job(job_id="job-failure-source", campaign_id="camp-contract",
                        candidate_id="candidate-failure", kind="simulate", stage="PILOT",
                        n=256, seed=8, replicate=0, spec={"candidate_spec": candidate_spec},
                        priority=11, sealed=False, requested_by="contract")
        source = repo.claim_job("executor-contract", ("simulate",))
        assert source and source["job_id"] == "job-failure-source"
        assert repo.commit_job_result(
            job_id=source["job_id"], owner="executor-contract",
            lease_generation=source["lease_generation"], digest="c" * 64, size=456,
            media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
            analysis_version="contract-v1",
        )
        first = repo.claim_analysis_job("executor-contract", "contract-v1")
        assert first and first["job_id"] == "job-failure-source"
        retry = repo.fail_analysis_claim(
            "camp-contract", "c" * 64, "contract-v1", "executor-contract",
            first["analysis_claim_token"], error="temporary crash",
            error_class="child_crash", retryable=True, terminal_topic="analysis_failed",
            terminal_payload={"job_id": first["job_id"],
                              "candidate_id": first["candidate_id"]},
        )
        assert retry and retry["status"] == "queued" and retry["next_attempt_utc"]
        repo.conn.execute(
            "UPDATE analysis_queue SET next_attempt_utc='1970-01-01T00:00:00Z' "
            "WHERE campaign_id='camp-contract' AND input_artifact=? "
            "AND analysis_version='contract-v1'", ("c" * 64,),
        )
        second = repo.claim_analysis_job("executor-contract", "contract-v1")
        assert second and second["analysis_attempt_number"] == 2
        failed = repo.fail_analysis_claim(
            "camp-contract", "c" * 64, "contract-v1", "executor-contract",
            second["analysis_claim_token"], error="invalid envelope",
            error_class="envelope_contract:ValueError", retryable=False,
            terminal_topic="integrity_failure",
            terminal_payload={"job_id": second["job_id"],
                              "candidate_id": second["candidate_id"]},
        )
        assert failed and failed["status"] == "failed"

        repo.insert_job(job_id="job-cancelled", campaign_id="camp-contract",
                        candidate_id="candidate-failure", kind="simulate", stage="NEXT",
                        n=1024, seed=8, replicate=0, spec={"candidate_spec": candidate_spec},
                        priority=12, sealed=False, requested_by="contract")
        terminal = repo.terminalize_candidate(
            "camp-contract", "candidate-failure", "QUARANTINE", "contract failure"
        )
        assert terminal["jobs_cancelled"] == 1
        assert repo.jobs("camp-contract", job_id="job-cancelled")[0]["status"] == "cancelled"
        assert repo.claim_job("executor-contract", ("simulate",)) is None
        producers = repo.conn.execute(
            "SELECT COUNT(*) c FROM artifact_producers WHERE artifact_hash=?", ("c" * 64,)
        ).fetchone()["c"]

        return {"jobs": repo.jobs("camp-contract"),
                "backlog": repo.analysis_backlog("contract-v1"),
                "active_claims": repo.active_analysis_claims(),
                "artifact_producers": int(producers),
                "analysis_failure_status": failed["status"],
                "terminal_jobs_cancelled": terminal["jobs_cancelled"]}
    finally:
        repo.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", "--postgres", dest="database", default="folder",
                        help="database target; defaults to this build's folder-local PostgreSQL")
    parser.add_argument("--keep-schema", action="store_true")
    args = parser.parse_args(argv)
    schema = "gsd_contract_" + uuid.uuid4().hex[:12]
    admin = connect_database(args.database)
    admin.execute(f"CREATE SCHEMA {schema}")
    admin.close()
    dsn = postgres_schema_dsn(args.database, schema)
    try:
        result = scenario(dsn)
        print(json.dumps({"passed": True, "schema": schema, "result": result}, indent=2))
        return 0
    finally:
        if not args.keep_schema:
            admin = connect_database(args.database)
            admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            admin.close()


if __name__ == "__main__":
    raise SystemExit(main())
