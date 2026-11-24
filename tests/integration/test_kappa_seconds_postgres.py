from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}


def _measure(repo, campaign_id: str, version: str, i: int, n: int, kappa, now: str, d_s: float = 0.5) -> None:
    artifact = f"kappa-{campaign_id}-{i:05d}".ljust(64, "0")
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                      "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", now))
    seconds = {"d_s": d_s} if kappa is None else {"d_s": d_s, "kappa": kappa}
    repo.conn.execute(
        "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
        "metrics_json,curves_artifact,created_utc,probe_seconds_d_s) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, f"an-{i:05d}", "law".ljust(64, "0"), n, i, version, artifact,
         json.dumps({"probe_seconds": seconds, "curvature": {"empty": {"measured": True, "mean": -0.5}}}),
         None, now, d_s))


def test_the_scan_reads_each_measurement_once_and_the_ladder_shows_it(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability import kappa_seconds as K
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "kappa"}, search_seed=1)["campaign_id"])
        version = repo.campaign_analysis_contract(campaign_id)
        repo.insert_candidate("law".ljust(64, "0"), campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        for i in range(30):
            n = 1024 if i % 3 else 4096
            kappa = None if i % 10 == 0 else round(0.01 * (i + 1), 3)
            _measure(repo, campaign_id, version, i, n, kappa, f"2026-09-30T10:00:{i:02d}Z")
        K._LAST_SCAN.pop(campaign_id, None)
        try:
            assert K.scan(repo, campaign_id, now=1000.0, limit=12) == 10, "a page of twelve, two without the curvature"
            assert K.scan(repo, campaign_id, now=1010.0) == 0, "at most one pass a campaign every 30 seconds"
            assert K.scan(repo, campaign_id, now=1031.0) == 17, "the rest, and none of the first page again"
            assert K.scan(repo, campaign_id, now=1062.0) == 0
            _measure(repo, campaign_id, version, 30, 4096, 2.5, "2026-09-30T11:00:00Z")
            assert K.scan(repo, campaign_id, now=1093.0) == 1
        finally:
            K._LAST_SCAN.pop(campaign_id, None)
        cells = K.ladder_cells(repo, campaign_id)
        expected = {n: [round(0.01 * (i + 1), 3) for i in range(30) if i % 10 and (1024 if i % 3 else 4096) == n]
                    for n in (1024, 4096)}
        expected[4096].append(2.5)
        for n, values in expected.items():
            assert cells[n]["kappa_timed_measurements"] == len(values)
            assert cells[n]["kappa_seconds_total"] == round(sum(values), 1)
            ordered = sorted(values)
            middle = (ordered[len(ordered) // 2] if len(ordered) % 2
                      else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2)
            assert cells[n]["kappa_median_seconds"] == round(middle, 3)
        ladder = {row["n"]: row for row in rung_distribution_for(repo, campaign_id)}
    assert ladder[4096]["kappa_median_seconds"] == cells[4096]["kappa_median_seconds"]
    assert ladder[4096]["probe_seconds_total"] == round(11 * 0.5 + cells[4096]["kappa_seconds_total"], 1), (
        "the probes' total counts the curvature's seconds beside d_s's")


def test_a_rung_keeps_a_bounded_sample_and_the_same_one_every_time():
    from graph_scale_dynamics.observability import kappa_seconds as K
    one, two = ({"contract": K.KAPPA_SECONDS_CONTRACT, "cursor": ["", ""], "rungs": {}} for _ in range(2))
    for state in (one, two):
        for i in range(1000):
            K.add(state, "7", 65536, float(i))
    assert len(one["rungs"]["65536"]["sample"]) == K.SAMPLE_SIZE and one == two
    assert one["rungs"]["65536"]["count"] == 1000 and one["rungs"]["65536"]["sum"] == sum(range(1000))
    assert 250 < sorted(one["rungs"]["65536"]["sample"])[K.SAMPLE_SIZE // 2] < 750, "the sample spans the rung"
