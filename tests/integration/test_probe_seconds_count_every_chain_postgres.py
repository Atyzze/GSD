from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law".ljust(64, "0")
SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}
DEEP = {"probe_seconds": {"kappa": 0.4},
        "chain_probes": {"given": {"probe_seconds": {}},
                         **{name: {"probe_seconds": {"d_s": 20.0, "d_V": 9.0, "d_B": 8.0, "d_w": 13.0}}
                            for name in ("cubic", "honeycomb", "tesseract")}}}
SHALLOW = {"probe_seconds": {"d_s": 0.5, "d_V": 0.1, "d_B": 0.2, "d_w": 0.3, "kappa": 0.01},
           "chain_probes": {"given": {"probe_seconds": {"d_s": 0.25, "d_V": 0.05, "d_B": 0.1, "d_w": 0.15}}}}


def test_the_columns_are_every_chain_s_seconds():
    from graph_scale_dynamics.db.repo_shared import _probe_seconds_columns
    assert _probe_seconds_columns(DEEP) == (60.0, 27.0, 24.0, 39.0), "an empty chain from empty: the given chains' seconds alone"
    assert _probe_seconds_columns(SHALLOW) == pytest.approx((0.75, 0.15, 0.3, 0.45))
    assert _probe_seconds_columns({"probe_seconds": {"kappa": 0.4}}) == (None, None, None, None), \
        "nothing probed is no time, not a time of zero"
    assert _probe_seconds_columns({"chain_probes": {"cubic": None, "square": "x"}}) == (None, None, None, None)


def _measure(repo, campaign_id: str, version: str, i: int, n: int, metrics: dict, columns: tuple) -> None:
    artifact = f"seconds-{campaign_id}-{i:05d}".ljust(64, "0")
    now = f"2026-11-02T10:00:{i:02d}Z"
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                      "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", now))
    repo.conn.execute(
        "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
        "metrics_json,curves_artifact,created_utc,probe_seconds_d_s,probe_seconds_d_v,probe_seconds_d_b,"
        "probe_seconds_d_w) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, f"an-{i:05d}", LAW, n, i % 3, version, artifact, json.dumps(metrics), None, now, *columns))




def test_the_ladder_reads_every_chain_s_seconds_as_they_are_written(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.db.repo_shared import _probe_seconds_columns
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "seconds"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        version = repo.campaign_analysis_contract(campaign_id)
        for i in range(6):
            _measure(repo, campaign_id, version, i, 262144, DEEP, _probe_seconds_columns(DEEP))
        for i in range(6, 9):
            _measure(repo, campaign_id, version, i, 1024, SHALLOW, _probe_seconds_columns(SHALLOW))
        rows = {row["n"]: row for row in rung_distribution_for(repo, campaign_id)}
    assert rows[262144]["probe_timed_measurements"] == 6
    assert (rows[262144]["d_s_median_seconds"], rows[262144]["d_w_median_seconds"]) == (60.0, 39.0)
    assert rows[262144]["d_s_seconds_total"] == 360.0
    assert rows[1024]["d_s_median_seconds"] == 0.75, "the given chain's seconds join the chain from empty's"
