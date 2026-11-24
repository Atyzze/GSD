from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

SPEC = {"terms": [{"op": "edge_count", "params": {}, "coeff": {"c0": 0.1, "scale": "one"}}],
        "dynamics": {"kind": "metropolis", "beta": 1.0}}
VERSION = "held-contract-v1"


def _law(name: str) -> str:
    return name.ljust(64, "0")


def _decide(repo, campaign_id, law, decision_id, action, rule, **fields):
    from graph_scale_dynamics.domain.model import utc_now
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,priority,"
        "queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign_id, decision_id, law, fields.get("at_n", 4096), fields.get("next_n", 16384), action, rule, rule,
         fields.get("priority"), None, 0, 0, False, "0:", "decision-engine-2", json.dumps({}), utc_now()))


def _campaign(repo, name):
    campaign_id = str(repo.create_campaign({"name": name}, search_seed=1)["campaign_id"])
    return campaign_id


def test_the_reader_marks_held_laws_apart_and_counts_them_whatever_the_limit(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations.lifecycle_recovery import stranded_work_alerts
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = _campaign(repo, "held")
        for name in ("held", "released", "undecided", "working"):
            repo.insert_candidate(_law(name), campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        _decide(repo, campaign_id, _law("held"), "0000000000000000001-a", "run_next", "base_block", at_n=1024,
                next_n=4096)
        _decide(repo, campaign_id, _law("held"), "0000000000000000002-a", "hold", "unsettled")
        _decide(repo, campaign_id, _law("released"), "0000000000000000003-a", "hold", "unsettled")
        _decide(repo, campaign_id, _law("released"), "0000000000000000004-a", "run_next", "d_s_settled",
                priority=1)
        _decide(repo, campaign_id, _law("working"), "0000000000000000005-a", "hold", "unsettled")
        repo.insert_job(job_id="job-working", campaign_id=campaign_id, candidate_id=_law("working"),
                        kind="simulate", stage="rung_n16384", n=16384, seed=0, replicate=0,
                        spec={"candidate_spec": SPEC}, priority=10, sealed=False, requested_by="fixture")

        rows = repo.stranded_candidates(campaign_id, VERSION, limit=500)
        ids = {row["candidate_id"]: row["held"] for row in rows}
        assert ids == {_law("held"): True, _law("released"): False, _law("undecided"): False}, ids
        assert [row["held"] for row in rows] == [False, False, True], "stranded laws come first"
        assert all(row["held_total"] == 1 for row in rows)

        cut = repo.stranded_candidates(campaign_id, VERSION, limit=1)
        assert len(cut) == 1 and cut[0]["held"] is False and cut[0]["held_total"] == 1

        alert = stranded_work_alerts(rows, {}, lambda stamp: 0.0)[0]
        assert (alert["stranded"], alert["held"], alert["severity"]) == (2, 1, "warning")
        assert _law("held") not in {row["candidate_id"] for row in alert["candidates"]}
        assert "1 held by the engine" in alert["headline"], alert["headline"]


def test_a_campaign_whose_idle_laws_are_all_held_has_no_stranded_law(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations.lifecycle_recovery import stranded_work_alerts
    from graph_scale_dynamics.operations.liveness import liveness_findings
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = _campaign(repo, "all held")
        for index in range(3):
            law = _law(f"held{index}")
            repo.insert_candidate(law, campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
            _decide(repo, campaign_id, law, f"000000000000000001{index}-a", "hold", "unsettled")
        rows = repo.stranded_candidates(campaign_id, VERSION)
        alert = stranded_work_alerts(rows, {}, lambda stamp: 0.0)[0]
        assert (alert["stranded"], alert["held"], alert["severity"]) == (0, 3, "info"), alert
        assert alert["headline"].startswith("no stranded laws"), alert["headline"]
        assert alert["candidates"] == []

        repo.refresh_scheduler_state(analysis_version=VERSION, total_slots=8, max_analyzers=1)
        keys = {item["key"] for item in liveness_findings(repo.conn, queue_age_seconds=0)}
        assert "liveness:work-supply-starved" not in keys, keys
        repo.insert_candidate(_law("undecided"), campaign_id, SPEC, "metropolis", 1, "BASE_BLOCK_RUNNING")
        repo.refresh_scheduler_state(analysis_version=VERSION, total_slots=8, max_analyzers=1)
        starved = [item for item in liveness_findings(repo.conn, queue_age_seconds=0)
                   if item["key"] == "liveness:work-supply-starved"]
        assert starved and starved[0]["detail"]["stranded_candidates"] == 1, starved


def test_report_14_counts_held_laws_beside_the_stranded_ones():
    from graph_scale_dynamics.research.report_pipeline import _pipeline_blockers
    from graph_scale_dynamics.operations.compute_ecology import capacity_diagnosis
    snapshot = {
        "candidates": [{"candidate_id": "held", "state": "BASE_BLOCK_RUNNING"},
                       {"candidate_id": "stuck", "state": "BASE_BLOCK_RUNNING"}],
        "engine_decisions": {"held": [{"action": "hold", "rule": "unsettled", "decision_id": "2"}],
                             "stuck": [{"action": "run_next", "rule": "d_s_settled", "next_n": 16384,
                                        "decision_id": "3"}]},
        "rungs": [], "jobs": [], "analysis_work": [], "evidence_rebuilds": [], "phenotypes": [],
    }
    blockers = _pipeline_blockers(snapshot)
    assert (blockers["stranded_nonterminal"], blockers["held"]) == (1, 1), blockers
    assert "HELD" not in blockers["blocker_counts"]
    assert [row["candidate_id"] for row in blockers["sample_stranded_candidates"]] == ["stuck"]
    only_held = capacity_diagnosis(total_slots=32, simulation_active=17, analysis_active=0, simulation_claimable=0,
                                   analysis_claimable=0, memory_reserved_bytes=0, memory_budget_bytes=1,
                                   stranded_nonterminal=0, held=203)
    assert only_held["state"] != "WORK_SUPPLY_STARVED" and only_held["work"]["held_candidates"] == 203
    assert "203 held law(s)" in only_held["explanation"], only_held["explanation"]


def test_report_14_reads_the_pause_flag_not_a_scheduler_row_the_pause_stopped_updating(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations.compute_ecology import current_capacity_diagnosis
    from graph_scale_dynamics.research.report_pipeline import _collect_snapshot_rows
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = _campaign(repo, "paused")
        repo.refresh_scheduler_state(analysis_version=VERSION, total_slots=32, max_analyzers=1)
        repo.set_flag("paused", "1")
        rows = _collect_snapshot_rows(repo, campaign_id)
        assert rows["scheduler_snapshot"]["paused"] is True
        diagnosis = current_capacity_diagnosis(rows, {"claimable_simulations": 5}, {"stranded_nonterminal": 0})
        assert diagnosis["state"] == "PAUSED", diagnosis["state"]
