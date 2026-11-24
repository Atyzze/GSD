from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}


def _metrics(i: int) -> dict:
    return {"d_s": {"d_s": round(1 + i / 1000, 3), "window": [i % 7, i % 11]}, "mean_degree": i % 9,
            "probe_seconds": {"d_s": 0.25}, "reading": f"law {i}"}


def test_the_collector_streams_its_json_rows_and_keeps_only_what_they_parse_to(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.research.report_pipeline import collect_replication_snapshot
    init_db(isolated_postgres_schema.dsn)
    count = 2345
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "rows"}, search_seed=1)["campaign_id"])
        version = repo.campaign_analysis_contract(campaign_id)
        laws = [f"law{k}".ljust(64, "0") for k in range(5)]
        for law in laws:
            repo.insert_candidate(law, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        now = utc_now()
        for i in range(count):
            artifact = f"artifact-{i:06d}".ljust(64, "0")
            repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                              "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", now))
            repo.conn.execute(
                "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
                "metrics_json,curves_artifact,created_utc,probe_seconds_d_s) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, f"an-{i:06d}", laws[i % 5], 64 << (2 * (i % 3)), i, version, artifact,
                 json.dumps(_metrics(i)), None, now, 0.25))
        for k, law in enumerate(laws):
            for n in (64, 256, 1024):
                repo.conn.execute(
                    "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
                    "VALUES(?,?,?,?,?,?)", (campaign_id, law, n, version, json.dumps({"n": n, "d_s": {"mean": k}}), now))
        stored = {row["analysis_id"]: json.loads(row["metrics_json"]) for row in repo.conn.execute(
            "SELECT analysis_id,metrics_json FROM measurements WHERE campaign_id=?", (campaign_id,)).fetchall()}
        snapshot = collect_replication_snapshot(repo, campaign_id)
        assert not repo.conn.in_transaction, "the snapshot's transaction ends when it is collected"
    primary = snapshot["campaign_snapshots"][0]
    rows = primary["measurements"]
    assert len(rows) == count and all("metrics_json" not in row for row in rows)
    assert all(row["metrics"] == stored[row["analysis_id"]] for row in rows)
    assert list(rows[0]) == ["analysis_id", "input_artifact", "candidate_id", "n", "seed", "created_utc",
                             "probe_seconds_d_s", "probe_seconds_d_v", "probe_seconds_d_b", "probe_seconds_d_w",
                             "producer_job", "metrics"], "the columns in their order, the parsed metrics last"
    assert next(iter(rows[0]["metrics"])) is next(iter(rows[1]["metrics"])), "a batch's rows share their keys"
    rungs = primary["rungs"]
    assert len(rungs) == 15 and all(set(row) == {"candidate_id", "n", "created_utc", "summary"} for row in rungs)
    assert [row["summary"]["n"] for row in rungs[:3]] == [64, 256, 1024]


def test_a_streamed_query_that_fails_fails_as_the_repository_reports_it(isolated_postgres_schema):
    from graph_scale_dynamics.db.connection import DatabaseOperationalError
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        with pytest.raises(DatabaseOperationalError):
            list(repo.conn.stream("SELECT no_such_column FROM measurements WHERE campaign_id=?", ("x",)))
        assert [row["one"] for row in repo.conn.stream("SELECT 1 AS one WHERE ?=?", (2, 2))] == [1]


def _settled(repo, campaign_id: str, law: str, now: str) -> None:
    for i, (rule, at_n, next_n, facts) in enumerate((("start", None, 64, {}),
                                                     ("d_s_settled", 64, 256, {"mean_degree_settled": True,
                                                                               "d_s": 2.01, "window": [3, 9]}))):
        repo.conn.execute(
            "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
            "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (campaign_id, f"{campaign_id}-{i}", law, at_n, next_n, "run_next", rule, rule, None, None, 3, 3, False,
             "", "decision-engine-2", json.dumps(facts), now))


def test_a_snapshot_holds_its_campaign_alone(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.reporting.snapshot_transport import in_transport_types
    from graph_scale_dynamics.research.report_pipeline import collect_replication_snapshot
    init_db(isolated_postgres_schema.dsn)
    now = utc_now()
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaigns = [str(repo.create_campaign({"name": name}, search_seed=seed)["campaign_id"])
                     for name, seed in (("primary", 1), ("peer", 2))]
        for campaign_id in campaigns:
            version = repo.campaign_analysis_contract(campaign_id)
            law = f"law-{campaign_id}".ljust(64, "0")
            repo.insert_candidate(law, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
            for n in (64, 256):
                repo.conn.execute(
                    "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
                    "VALUES(?,?,?,?,?,?)", (campaign_id, law, n, version, json.dumps({"n": n, "d_s": {"mean": 2}}),
                                            now))
            _settled(repo, campaign_id, law, now)
        replication = in_transport_types(collect_replication_snapshot(repo, campaigns[0]))
    assert replication["campaign_ids"] == campaigns[:1] and replication["compact_peer_campaign_ids"] == []
    (primary,) = replication["campaign_snapshots"]
    assert primary["engine_decisions"][f"law-{campaigns[0]}".ljust(64, "0")][1]["facts"]["window"] == [3, 9], (
        "the primary's decisions keep their facts whole")
