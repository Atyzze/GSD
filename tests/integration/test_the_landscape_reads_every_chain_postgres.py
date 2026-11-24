from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

LAW = "law".ljust(64, "1")
SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}


def _probes(d_s, *, valid=True):
    read = {"valid": valid, "value": d_s if valid else None, "se": 0.01, "refusal": None if valid else "NO_SCALING_WINDOW"}
    return {"d_s": read, "d_V": dict(read), "d_B": dict(read), "d_w": {"valid": True, "value": 2.0, "se": 0.02},
            "half_volume_radius": 6.5, "small_world": False, "d_s_shape": {"measured": True}}


def _census(n, edges, giant):
    return {"edges": edges, "largest_component": {"size": giant}, "degree_histogram": {"4": n}}


TODAY = {"health": {"sweeps_multiplier": 2},
         "chain_probes": {"given": _probes(2.01), "cubic": _probes(3.02)},
         "census": {"empty": _census(1024, 2048, 1024), "given": _census(1024, 3072, 1000),
                    "cubic": _census(1024, 3072, 1024)}}
SHORTER = {"health": {"sweeps_multiplier": 1},
           "chain_probes": {"given": _probes(1.5), "cubic": _probes(0, valid=False)},
           "census": {"empty": _census(1024, 2048, 1024), "given": _census(1024, 2048, 512),
                      "cubic": _census(1024, 3072, 1024)}}


def _measure(repo, campaign_id, version, i, seed, metrics):
    artifact = f"chains-{i:05d}".ljust(64, "0")
    now = f"2026-11-14T20:00:{i:02d}Z"
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                      "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", now))
    repo.conn.execute(
        "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
        "metrics_json,curves_artifact,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, f"an-{i:05d}", LAW, 1024, seed, version, artifact, json.dumps(metrics), None, now))


def test_every_chain_s_readings_are_read_and_the_longer_run_kept(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.services.api import landscape_chains as LC
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "chains"}, search_seed=1)["campaign_id"])
        repo.insert_candidate(LAW, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        version = repo.campaign_analysis_contract(campaign_id)
        _measure(repo, campaign_id, version, 0, 0, TODAY)
        _measure(repo, campaign_id, version, 1, 1, SHORTER)
        _measure(repo, campaign_id, version, 2, 0, SHORTER)
        rows = repo.conn.execute(LC.ROWS_SQL, (campaign_id, version)).fetchall()
    assert len(rows) == 3
    seeds = LC.chain_seeds(rows)
    assert set(seeds) == {(LAW, "given"), (LAW, "cubic")}
    given = seeds[(LAW, "given")][1024]
    assert sorted(s["d_s"]["value"] for s in given) == [1.5, 2.01], "seed 0's longer run, and seed 1's"
    assert sorted(round(s["degree"], 3) for s in given) == [4.0, 6.0]
    assert sorted(round(s["giant"], 4) for s in given) == [0.5, 0.9766]
    summary = LC.chain_summary(seeds[(LAW, "cubic")][1024])
    assert summary["d_s"]["mean"] == pytest.approx(3.02) and summary["d_s_valid_fraction"] == 0.5
    assert summary["probe_refusals"]["d_s"] == {"NO_SCALING_WINDOW": 1}
    assert summary["d_w"]["mean"] == 2.0 and summary["half_volume_radius"]["mean"] == 6.5
    assert "d_s_shape" not in json.dumps(rows[0]["chain_probes"] or ""), "only what the landscape draws is read"
