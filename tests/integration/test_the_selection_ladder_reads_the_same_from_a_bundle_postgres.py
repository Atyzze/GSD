from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "graph_scale_dynamics" / "resources" / "ui"


def _campaign(repo, tmp_path) -> str:
    from tests.integration.slice_driver import every_chain_spec
    spec = json.loads(every_chain_spec(tmp_path / "spec.json", let_through=True).read_text())
    campaign_id = str(repo.create_campaign(spec, search_seed=1)["campaign_id"])
    version = repo.campaign_analysis_contract(campaign_id)
    laws = {"a": ("BASE_BLOCK_RUNNING", [64, 256], ("run_next", "keep_going", 256, 1024)),
            "b": ("PARKED", [64, 256, 1024], ("hold", "starts_alike", 1024, None)),
            "c": ("HELD", [64, 256, 1024, 4096], ("hold", "waiting", 4096, 16384)),
            "d": ("STOPPED", [64], ("stop", "empty", 64, None)),
            "e": ("PROPOSED", [], None)}
    for i, (name, (state, rungs, decision)) in enumerate(sorted(laws.items())):
        law = name.ljust(64, "1")
        reason = f"decision engine: {decision[1]}" if decision else None
        repo.insert_candidate(law, campaign_id, {"terms": [{"op": "edge_count", "params": {}, "coeff": {
            "c0": 0.1 + i, "scale": "one"}}], "dynamics": {"kind": "metropolis", "beta": 1.0}}, "metropolis", 1, state)
        repo.conn.execute("UPDATE campaign_candidates SET state=?, state_reason=? WHERE campaign_id=? AND candidate_id=?",
                          (state, reason, campaign_id, law))
        for n in rungs:
            repo.conn.execute(
                "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
                "VALUES(?,?,?,?,?,?)", (campaign_id, law, n, version, "{}", "2026-11-25T20:00:00Z"))
        if decision:
            action, rule, at_n, next_n = decision
            repo.conn.execute(
                "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
                "jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, f"{i + 1:020d}-aaaaaaaa", law, at_n, next_n, action, rule, rule, 0, 0, False, "",
                 "test", "{}", "2026-11-25T20:00:00Z"))
    from graph_scale_dynamics.observability import score_board
    score_board.keep(repo, campaign_id, {"c".ljust(64, "1"): {"score": 7, "top_n": 4096}})
    return campaign_id


def test_the_selection_s_ladder_reads_the_same_live_from_a_bundle_s_tables_and_in_the_page(isolated_postgres_schema,
                                                                                          tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability import selection_ladder as SL
    from graph_scale_dynamics.reporting import study_tables
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign = _campaign(repo, tmp_path)
        live = SL.facts(repo, [campaign])
        points: dict = {}
        list(study_tables.rung_rows(repo, [campaign], points))
        rows = json.loads(json.dumps(list(study_tables.law_rows(repo, [campaign], points)), default=str))
    from_bundle = SL.facts_of_rows(rows)
    assert {tuple(map(str, f[:2])): f for f in live} == {tuple(map(str, f[:2])): f for f in from_bundle}, (
        "law by law, the live folder and its bundle's tables say the same")
    ladder = {r["n"]: r for r in SL.ladder(live)}
    assert [ladder[n]["laws"] for n in (64, 256, 1024, 4096)] == [4, 3, 2, 1]
    assert ladder[1024]["under_way"] == 1, "a law running toward 1,024"
    assert ladder[1024]["settled"] == {"starts_alike": 1} and ladder[64]["settled"] == {"empty": 1}
    assert ladder[4096]["waiting"] == 1 and ladder[4096]["scoring"] == 1
    keep = {(campaign, "b".ljust(64, "1")), (campaign, "c".ljust(64, "1"))}
    node = shutil.which("node") or "/opt/node22/bin/node"
    script = ("global.window={};require(process.argv[1]);const [facts,keep]=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify([window.GSD_SELECTION.ladder(facts,null),"
              "window.GSD_SELECTION.ladder(facts,new Set(keep))]))")
    out = subprocess.run([node, "-e", script, str(UI / "selection.js")], check=True, capture_output=True, text=True,
                         input=json.dumps([live, [f"{c}|{law}" for c, law in sorted(keep)]]), timeout=60)
    whole, kept = json.loads(out.stdout)
    assert whole == SL.ladder(live), "the page's ladder is the server's, row by row"
    assert kept == SL.ladder(live, keep), "and the same for a selection"
    assert [r["laws"] for r in kept] == [2, 2, 2, 1]


def test_the_study_s_hours_come_in_four_parts_the_system_s_from_the_host_s_total(isolated_postgres_schema,
                                                                                  tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability import study_hours as H
    from tests.integration.slice_driver import every_chain_spec
    init_db(isolated_postgres_schema.dsn)
    base = json.loads(every_chain_spec(tmp_path / "spec.json", let_through=True).read_text())
    with Repo(isolated_postgres_schema.dsn) as repo:
        hours_of = {"A": 7200.0, "N": 3600.0, "D": 1800.0}
        for i, (group, kind) in enumerate((("A", "blind"), ("N", "focus"), ("D", "focus"))):
            spec = dict(base, study_design={"study": "176", "group": group, "kind": kind})
            cid = str(repo.create_campaign(spec, search_seed=1 + i)["campaign_id"])
            law = f"law{group}".ljust(64, "1")
            repo.insert_candidate(law, cid, {"terms": [{"op": "edge_count", "params": {}, "coeff": {
                "c0": 0.1 + i, "scale": "one"}}], "dynamics": {"kind": "metropolis", "beta": 1.0}}, "metropolis", 1,
                "BASE_BLOCK_RUNNING")
            repo.insert_job(job_id=f"job-{group}", campaign_id=cid, candidate_id=law, kind="simulate", stage="base",
                            n=64, seed=0, spec={})
            repo.conn.execute(
                "INSERT INTO attempts(attempt_id,job_id,number,started_utc,wall_seconds,peak_rss_bytes) "
                "VALUES(?,?,?,?,?,?)", (f"att-{group}", f"job-{group}", 1, "2026-11-25T20:00:00Z",
                                        hours_of[group], 2 * H.GIB))
        found = H.hours(repo, cores=4)
        assert not found["host_read"] and found["core_hours"] == {"A": 2.0, "N": 1.0, "D": 0.5, "system": 0.0,
                                                                  "total": 3.5}
        assert found["memory_gib_hours"]["D"] == 1.0, "2 GiB held half an hour"
        repo.record_resource_telemetry({"campaign_id": "1", "telemetry_contract": "t", "build_number": 872,
                                        "runtime_fingerprint": "r", "environment_fingerprint": "e",
                                        "sampled_utc": "2026-11-25T20:00:00Z", "phase": "runtime",
                                        "interval_seconds": 3600.0, "cpu_percent": 100.0,
                                        "memory_used_bytes": 8 * H.GIB, "quality": "clean"})
        found = H.hours(repo, cores=4)
        assert found["host_read"] and found["core_hours"]["system"] == 0.5, "4 core-hours less the workers' 3.5"
        assert found["core_hours"]["total"] == 4.0
        assert found["memory_gib_hours"]["system"] == 1.0, "8 GiB-hours less the workers' 7"
