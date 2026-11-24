from __future__ import annotations

import json
import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

SCANS = ("SELECT relname,seq_scan,COALESCE(idx_scan,0) AS idx_scan FROM pg_stat_user_tables "
         "WHERE schemaname=current_schema()")
STARTS = ("given", "square", "cubic")


def _probes(d: float, valid: bool) -> dict:
    read = {"valid": valid, "value": d if valid else None, "se": 0.01, "refusal": None if valid else "NO_SCALING_WINDOW"}
    return {"d_s": read, "d_V": dict(read), "d_B": dict(read), "d_w": dict(read), "half_volume_radius": 6.5}


def _metrics(n: int, d: float) -> dict:
    census = {"n": n, "edges": 2 * n, "largest_component": {"size": n, "edges": 2 * n}}
    return {"health": {"n": n, "sweeps_multiplier": 1},
            "chain_probes": {name: _probes(d + 0.01 * i, i != 1) for i, name in enumerate(STARTS)},
            "census": {name: dict(census) for name in ("empty",) + STARTS},
            "d_s": {"valid": True, "d_s": d, "se": 0.02}, "d_V": {"valid": True, "d_V_window": d, "se": 0.02},
            "d_B": {"valid": False, "refusal": "NOT_POWER_LAW"}, "d_w": {"valid": True, "d_w": 2.0, "se": 0.02}}


def _campaign(repo, tmp_path) -> tuple[str, str]:
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    from tests.integration.slice_driver import every_chain_spec
    spec = json.loads(every_chain_spec(tmp_path / "spec.json", let_through=True).read_text())
    campaign_id = str(repo.create_campaign(spec, search_seed=1)["campaign_id"])
    version = repo.campaign_analysis_contract(campaign_id)
    k = 0
    for law in range(3):
        law_id = f"law{law}".ljust(64, "1")
        repo.insert_candidate(law_id, campaign_id, {"terms": [{"op": "edge_count", "params": {}, "coeff": {
            "c0": 0.1 + law, "scale": "one"}}], "dynamics": {"kind": "metropolis", "beta": 1.0}}, "metropolis", 1,
            "BASE_BLOCK_RUNNING")
        for n in (64, 256):
            seeds = [_metrics(n, 2.0 + 0.01 * s) for s in range(2)]
            for seed, metrics in enumerate(seeds):
                k += 1
                artifact = f"art{k:05d}".ljust(64, "0")
                repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                                  "created_utc) VALUES(?,?,?,?,?,?)",
                                  (artifact, 1, "application/json", None, "{}", "2026-11-20T00:00:00Z"))
                repo.conn.execute(
                    "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,"
                    "input_artifact,metrics_json,curves_artifact,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (campaign_id, f"an{k:05d}", law_id, n, seed, version, artifact, json.dumps(metrics), None,
                     "2026-11-20T00:00:00Z"))
            repo.conn.execute(
                "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
                "VALUES(?,?,?,?,?,?)",
                (campaign_id, law_id, n, version, json.dumps(rung_summary(seeds)), "2026-11-20T00:00:00Z"))
    return campaign_id, version


def _flushed(repo) -> None:
    repo.conn.execute("SELECT pg_stat_force_next_flush()")
    repo.conn.execute("SELECT 1")


def _scans(dsn) -> dict:
    from graph_scale_dynamics.db.repo import Repo
    with Repo(dsn) as repo:
        return {r["relname"]: (int(r["seq_scan"]), int(r["idx_scan"])) for r in repo.conn.execute(SCANS).fetchall()}


def _stamp(dsn) -> str:
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api import landscape_inputs
    with Repo(dsn) as repo:
        return landscape_inputs.stamp(repo.conn)


def _settled(read, *, seconds: float = 20.0):
    last, deadline = read(), time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(1.0)
        now = read()
        if now == last:
            return now
        last = now
    raise AssertionError("the statistics never settled")


def _moved(read, before, *, seconds: float = 20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        now = read()
        if now != before:
            return now
        time.sleep(0.5)
    return before


def test_the_inputs_name_every_table_the_landscape_reads(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.score_board import FLAG_PREFIX
    from graph_scale_dynamics.services.api import landscape_inputs, landscape_worker
    dsn = isolated_postgres_schema.dsn
    init_db(dsn)
    with Repo(dsn) as repo:
        campaign_id, _version = _campaign(repo, tmp_path)
        _flushed(repo)
    before = _settled(lambda: _scans(dsn))
    control_keys: list[str] = []
    with Repo(dsn) as repo:
        execute = repo.conn.execute

        def spied(sql, args=()):
            if " control" in " ".join(str(sql).lower().split()):
                control_keys.extend(str(a) for a in args)
            return execute(sql, args)

        repo.conn.execute = spied
        payload = landscape_worker.build_landscape(repo, campaign_id)
        repo.conn.execute = execute
        _flushed(repo)
    after = _moved(lambda: _scans(dsn), before)
    read = {table for table, counts in after.items() if counts != before.get(table)}
    assert payload["dimension_points"], "the landscape read the seeded laws"
    assert {"rung_summaries", "measurements", "engine_decisions"} <= read, read
    assert read <= set(landscape_inputs.TABLES) | {"control"}, (
        f"the landscape reads {sorted(read - set(landscape_inputs.TABLES) - {'control'})}, which its inputs' "
        "stamp does not watch: an idle folder would keep a stale landscape")
    assert control_keys and all(key.startswith(FLAG_PREFIX) for key in control_keys), control_keys


def test_the_stamp_holds_still_without_writes_and_moves_with_one(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.score_board import FLAG_PREFIX
    dsn = isolated_postgres_schema.dsn
    init_db(dsn)
    with Repo(dsn) as repo:
        campaign_id, version = _campaign(repo, tmp_path)
        _flushed(repo)
    quiet = _settled(lambda: _stamp(dsn))
    with Repo(dsn) as repo:
        repo.publish_runtime_imports("landscape-worker")
        _flushed(repo)
    time.sleep(2.0)
    assert _stamp(dsn) == quiet, "the landscape worker's own record of its imports builds nothing again"
    with Repo(dsn) as repo:
        repo.conn.execute(
            "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
            "VALUES(?,?,?,?,?,?)", (campaign_id, "law0".ljust(64, "1"), 1024, version, "{}", "2026-11-20T01:00:00Z"))
        _flushed(repo)
    grown = _moved(lambda: _stamp(dsn), quiet)
    assert grown != quiet, "a new rung's summary builds the landscape again"
    with Repo(dsn) as repo:
        repo.set_flag(FLAG_PREFIX + campaign_id, json.dumps({"scores": {"x": 1}}))
    assert _stamp(dsn) != grown, "a score board written builds the landscape again"
