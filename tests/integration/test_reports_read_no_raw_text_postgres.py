from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}


def _documents() -> list[dict]:
    return json.loads((ROOT / "tests/fixtures/metrics_documents.json").read_text())["documents"]


def _job_spec(n: int, k: int) -> dict:
    return {"candidate_spec": dict(SPEC, dynamics=dict(SPEC["dynamics"], sweeps=30)), "engine_version": "engine-3.0.0",
            "execution": {"sweeps_multiplier": 1 << (n // 128), "proposal_locality": 0.25 * (k % 2),
                          "one_shot": {"contract": "one-shot-sampling-1", "work_budget": 10 ** 12}},
            "resource_limits": {"contract": "gsd-deep-memory-lane-1", "interpretation": "why the limits are what they are"}}


def _decide(repo, campaign_id: str, law: str, k: int, now: str) -> None:
    rows = [("start", "run_next", None, 64, {"reason": "no rung measured yet"})]
    if k % 2 == 0:
        rows.append(("d_s_settled", "run_next", 64, 256, {"d_s": 1.9 + k / 10, "mean_degree_settled": k == 0,
                                                          "windows": {"64": [1, 2]}}))
    for i, (rule, action, at_n, next_n, facts) in enumerate(rows):
        repo.conn.execute(
            "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
            "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (campaign_id, f"{k:04d}-{i}", law, at_n, next_n, action, rule, f"reason {rule}", None, None, 3, 3, False,
             "", "decision-engine-2", json.dumps(facts, sort_keys=True), now))


def _campaign(repo) -> str:
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.scaleflow.flow import rung_summary
    campaign_id = str(repo.create_campaign({"name": "raw-text"}, search_seed=1)["campaign_id"])
    version = repo.campaign_analysis_contract(campaign_id)
    documents, now = _documents(), utc_now()
    for k in range(4):
        law = f"law{k}".ljust(64, "0")
        repo.insert_candidate(law, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        for n in (64, 256):
            per_seed = []
            for seed in range(3):
                job = f"job-{k}-{n}-{seed}"
                repo.insert_job(job_id=job, campaign_id=campaign_id, candidate_id=law, kind="simulate", stage="BASE",
                                n=n, seed=seed, replicate=0, spec=_job_spec(n, k), priority=64, sealed=False,
                                requested_by="raw-text")
                repo.record_attempt(f"a-{job}", job, 1, "exec")
                repo.close_attempt(f"a-{job}", 0, 10 ** 8, 1.5, None, {"cpu": {"user": 1.0}})
                metrics = documents[(k + seed) % len(documents)]
                artifact = f"{k}-{n}-{seed}".ljust(64, "0")
                repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                                  "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job, "{}", now))
                repo.conn.execute(
                    "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,"
                    "input_artifact,metrics_json,curves_artifact,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (campaign_id, f"an-{job}", law, n, seed, version, artifact, json.dumps(metrics), None, now))
                per_seed.append(metrics)
            repo.conn.execute(
                "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
                "VALUES(?,?,?,?,?,?)", (campaign_id, law, n, version, json.dumps(rung_summary(per_seed)), now))
        _decide(repo, campaign_id, law, k, now)
    return campaign_id


def _with_text(rows: list[dict], column: str, key: str, order: list[str]) -> list[dict]:
    out = []
    for row in rows:
        full = dict(row, **{column: json.dumps(row[key])})
        out.append({name: full[name] for name in order if name in full} | {key: row[key]})
    return out


def _stable_difference(first, again, other, path="$"):
    if first != again and type(first) is not dict and type(first) is not list:
        return None
    if isinstance(first, dict) and isinstance(again, dict) and isinstance(other, dict):
        if list(first) != list(other) and list(first) == list(again):
            return f"{path}: keys {sorted(set(first) ^ set(other))}"
        for name in first:
            if name in again and name in other:
                found = _stable_difference(first[name], again[name], other[name], f"{path}.{name}")
                if found:
                    return found
        return None
    if isinstance(first, list) and isinstance(again, list) and isinstance(other, list):
        if len(first) != len(other) and len(first) == len(again):
            return f"{path}: {len(first)} items against {len(other)}"
        for i, (a, b, c) in enumerate(zip(first, again, other, strict=False)):
            found = _stable_difference(a, b, c, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if first == other else f"{path}: {json.dumps(first)[:120]} against {json.dumps(other)[:120]}"


def test_every_report_is_the_same_without_the_raw_text(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.reporting.snapshot_transport import in_transport_types
    from graph_scale_dynamics.research.report_pipeline import BUILDERS, build_report, collect_replication_snapshot
    from graph_scale_dynamics.research.snapshot_rows import UNREAD_METRICS_SECTIONS
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = _campaign(repo)
        replication = in_transport_types(collect_replication_snapshot(repo, campaign_id))
        as_549 = in_transport_types({"jobs": repo.jobs(campaign_id),
                                     "engine_decisions": repo.campaign_engine_decisions(campaign_id)})
        stored = {row["analysis_id"]: json.loads(row["metrics_json"]) for row in repo.conn.execute(
            "SELECT analysis_id,metrics_json FROM measurements WHERE campaign_id=?", (campaign_id,)).fetchall()}
    primary = replication["campaign_snapshots"][0]
    assert len(primary["measurements"]) == 24 and len(primary["rungs"]) == 8
    assert sum(len(rows) for rows in primary["engine_decisions"].values()) == 6
    assert not any(name in row["metrics"] for row in primary["measurements"] for name in UNREAD_METRICS_SECTIONS)
    assert all("spec_json" not in row for row in primary["jobs"] + primary["attempts"])
    measured = ["analysis_id", "input_artifact", "candidate_id", "n", "seed", "metrics_json", "created_utc"]
    texted = copy.deepcopy(replication)
    old = texted["campaign_snapshots"][0]
    for row in old["measurements"]:
        row["metrics"] = stored[row["analysis_id"]]
    old["measurements"] = _with_text(old["measurements"], "metrics_json", "metrics", measured)
    old["rungs"] = _with_text(old["rungs"], "summary_json", "summary", ["candidate_id", "n", "summary_json"])
    old["jobs"], old["engine_decisions"] = as_549["jobs"], as_549["engine_decisions"]
    spec_text = {job["job_id"]: job["spec_json"] for job in old["jobs"]}
    for i, row in enumerate(old["attempts"]):
        order = list(row)
        old["attempts"][i] = {name: row[name] for name in order[:order.index("requested_by") + 1]} | {
            "spec_json": spec_text[row["job_id"]]} | {name: row[name] for name in order[order.index("requested_by") + 1:]}

    def reports(source):
        built = {}
        for code in sorted(BUILDERS):
            given = copy.deepcopy(source)
            snapshot = dict(given["campaign_snapshots"][0], replication_snapshot=given)
            try:
                built[code] = build_report(code, snapshot)["body"]
            except Exception as exc:  # noqa: BLE001
                built[code] = {"raised": type(exc).__name__}
        return built

    first, again, other = reports(replication), reports(replication), reports(texted)
    differences = {code: _stable_difference(first[code], again[code], other[code]) for code in sorted(first)}
    assert not {code: found for code, found in differences.items() if found}, differences
    assert sum("raised" not in body for body in first.values()) >= len(first) - 2, (
        "most reports build on this snapshot: " + str({c: b for c, b in first.items() if "raised" in b}))


def test_the_snapshot_fixture_is_what_the_collector_collects(isolated_postgres_schema):
    import gzip
    import os

    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.reporting.snapshot_transport import in_transport_types
    from graph_scale_dynamics.research.report_pipeline import collect_replication_snapshot
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        fresh = in_transport_types(collect_replication_snapshot(repo, _campaign(repo)))
    path = ROOT / "tests/fixtures/report_snapshot.json.gz"
    if os.environ.get("GSD_WRITE_REPORT_SNAPSHOT_FIXTURE") == "1":
        path.write_bytes(gzip.compress(json.dumps(fresh, separators=(",", ":")).encode(), compresslevel=9, mtime=0))
    fixture = json.loads(gzip.decompress(path.read_bytes()))

    def shape(snapshot):
        primary = snapshot["campaign_snapshots"][0]
        return (sorted(snapshot), sorted(primary), sorted(primary["measurements"][0]), sorted(primary["rungs"][0]),
                sorted(primary["jobs"][0]), sorted(primary["attempts"][0]), sorted(primary["candidates"][0]))
    assert shape(fixture) == shape(fresh), "the collector changed: GSD_WRITE_REPORT_SNAPSHOT_FIXTURE=1 writes it again"
