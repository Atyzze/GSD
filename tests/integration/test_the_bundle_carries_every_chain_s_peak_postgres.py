from __future__ import annotations

import gzip
import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law-chains".ljust(64, "0")
WHEN = "2026-11-21T04:00:00Z"
N = 1024


def _envelope(seed: int) -> dict:
    from tests.support import chains as C
    sparse = {"edge_count": 2048, "peak_edge_count": 2300, "mean_degree": 4.0, "max_degree": 9}
    dense = {"edge_count": 16384, "peak_edge_count": 16384, "mean_degree": 32.0, "max_degree": 61}
    moved = {"parts": {"moves": 5000, "evaluations": 5000, "changes": 1200, "lists": 30, "entries": 400, "tests": 900}}
    frozen = {"parts": {"moves": 5000, "evaluations": 5000, "changes": 0, "lists": 0, "entries": 0, "tests": 0}}
    return C.envelope(N, C.chain("empty", init="empty", final=sparse, termination={"reason": "completed"},
                              accounting=moved, accepted_moves=1200, seconds=0.75),
                      C.chain("square", init="periodic_square_lattice", final=dense, ended={"reason": "mean_degree_cap"},
                              termination={"reason": "mean_degree_cap"}, accounting=frozen, accepted_moves=0,
                              seconds=0.5),
                      C.chain("cubic", init="periodic_cubic_quotient", skipped=True), seed=seed)


def _run(repo, store, campaign, job, seed, *, kept=True):
    from graph_scale_dynamics.artifact_store.retention import compact_payload
    raw = f"{seed:064x}"
    compact = store.put_json(compact_payload(_envelope(seed), {}))[0] if kept else "e" + f"{seed:063x}"
    repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=LAW, kind="simulate", stage="rung_n1024",
                    n=N, seed=seed, replicate=0, spec={}, priority=64, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (raw, job))
    for digest in (raw, compact):
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)", (digest, 1, "application/json", job, "{}", WHEN))
    repo.conn.execute("INSERT INTO artifact_retention(artifact_hash,storage_class,body_state,compact_artifact,"
                      "created_utc,updated_utc) VALUES(?,?,?,?,?,?)",
                      (raw, "raw_simulation", "transient", compact, WHEN, WHEN))
    for number, memory, error_class, finished in ((1, 9_000_000_000, "preempted_fleet_paused", "2026-11-21T04:01:00Z"),
                                                  (2, 700_000_000, None, "2026-11-21T04:00:30Z")):
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,started_utc,finished_utc,wall_seconds,"
                          "peak_pss_bytes,error_class) VALUES(?,?,?,?,?,?,?,?)",
                          (f"{job}-{number}", job, number, WHEN, finished, 12.0, memory, error_class))


def test_the_bundle_carries_every_chain_s_final_and_peak_degree(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.artifact_store.blobstore import BlobStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.reporting.study_tables import CHAIN_FIELDS, tables
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        store = BlobStore(tmp_path / "blobs")
        campaign = str(repo.create_campaign({"name": "chains"}, search_seed=3)["campaign_id"])
        repo.insert_candidate(LAW, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        _run(repo, store, campaign, "job-a", 1)
        _run(repo, store, campaign, "job-b", 2, kept=False)
        found = tables(repo, [campaign], blobs=tmp_path / "blobs")
        rows = [json.loads(line) for line in gzip.decompress(found["chains.ndjson.gz"]).splitlines()]
        readme = json.loads(found["README.json"])["tables"]["chains.ndjson.gz"]
        assert readme["rows"] == len(rows) == 4 and readme["one_row_per"] == "seed and chain"
        assert all(set(row) == set(CHAIN_FIELDS) for row in rows)
        kept = {row["chain"]: row for row in rows if row["job_id"] == "job-a"}
        assert (kept["empty"]["final_mean_degree"], kept["empty"]["peak_mean_degree"]) == (4.0, 4.4922)
        assert not kept["empty"]["ended_at_cap"] and kept["empty"]["termination"] == "completed"
        assert kept["square"]["ended_at_cap"] and kept["square"]["peak_mean_degree"] == 32.0
        assert kept["square"]["max_degree"] == 61 and kept["square"]["termination"] == "mean_degree_cap"
        assert not kept["cubic"]["ran"] and kept["cubic"]["peak_edges"] is None
        weights = Policy().work_weights()
        parts = kept["empty"]["work_parts"]
        assert parts == {"moves": 5000, "evaluations": 5000, "changes": 1200, "lists": 30, "entries": 400, "tests": 900}
        assert kept["empty"]["work_units"] == sum(weights[name] * count for name, count in parts.items()) > 0
        assert (kept["empty"]["moves"], kept["empty"]["accepted_moves"], kept["empty"]["seconds"]) == (5000, 1200, 0.75)
        assert (kept["square"]["moves"], kept["square"]["accepted_moves"]) == (5000, 0), (
            "a chain that accepted no move changed no edge: what a frozen lattice is told by (841)")
        assert kept["square"]["work_units"] == weights["moves"] * 5000 + weights["evaluations"] * 5000
        assert all(kept["cubic"][key] is None for key in ("moves", "accepted_moves", "work_units", "work_parts",
                                                           "seconds")), "a chain that did not run has no work"
        assert {row["seed_peak_memory_bytes"] for row in kept.values()} == {700_000_000}, (
            "the last attempt that was not interrupted, as report 28 reads it")
        assert all(row["evidence"] == "compact" and row["n"] == N for row in kept.values())
        lost = [row for row in rows if row["job_id"] == "job-b"]
        assert len(lost) == 1 and lost[0]["chain"] is None and "not readable" in lost[0]["evidence"]
        assert "chains.ndjson.gz" not in tables(repo, [campaign]), "no blob store, no table"
    finally:
        repo.close()
