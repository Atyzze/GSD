from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from test_engine_campaign_decider import LAW, Log, SPEC, engine_campaign  # noqa: E402,F401


def _store(repo, campaign_id):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    return DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})


def _decision(store, campaign_id, law, *, action, rule, at_n, next_n=None, gate=None):
    store.record_decision(campaign_id, {"law": law, "action": action, "rule": rule, "reason": rule, "at_n": at_n,
                                        "next_n": next_n, "engine": "decision-engine-2",
                                        "facts": ({"gate": gate} if gate is not None else {})})


def _refusal(early=None, underlying_next=262144):
    return {"contract": "structure-gate-1", "stage": "full", "result": "no finite dimension", "refused": True,
            "underlying": {"action": "run_next", "rule": "d_s_settled", "next_n": underlying_next, "reason": "r"},
            "audit": {"sampled": False, "near_threshold": False, "due": False},
            **({"early": early} if early is not None else {})}


def test_the_store_reads_both_chains_from_the_measurement_rows(engine_campaign):  # noqa: F811
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    dsn, campaign_id = engine_campaign
    now = utc_now()
    with Repo(dsn) as repo:
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                          "VALUES(?,?,?,?,?,?)", ("artifact-1", 1, "application/json", None, "{}", now))
        for seed, (from_empty_gap, given_gap) in enumerate([(1e-4, 0.2), (3e-4, 0.2)]):
            census = lambda gap: {"largest_component": {"size": 16000, "spectral_gap": {"value": gap},  # noqa: E731
                                                        "diameter": {"lower_bound": 128}}}
            metrics = {"census": {"empty": census(from_empty_gap), "given": census(given_gap)},
                       "log_diameter_flag": False, "log_diameter": {"basis": "diameter lower bound above the threshold"}}
            repo.conn.execute("INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,"
                              "input_artifact,metrics_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                              (campaign_id, f"a{seed}", LAW, 16384, seed, ANALYSIS_VERSION, "artifact-1",
                               json.dumps(metrics), now))
        structure = _store(repo, campaign_id).law_structure(campaign_id, LAW)
    rung = structure[16384]
    assert rung["empty"]["seeds"] == 2 and abs(rung["empty"]["gap"] - 2e-4) < 1e-15
    assert rung["given"]["gap"] == 0.2 and abs(rung["given"]["giant"] - 16000 / 16384) < 1e-12
    assert rung["log_diameter"]["false"] == 2 and rung["log_diameter"]["unknown"] == 0


def test_where_the_gate_stands_is_read_from_the_folder_and_the_campaign(engine_campaign):  # noqa: F811
    from graph_scale_dynamics.db.decision_store import EARLY_STAGE_FLAG, early_stage_counts
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api import gate_route
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        for i, early in enumerate([{"would_refuse": True, "agrees": True, "disagrees": False}] * 3
                                  + [{"would_refuse": True, "agrees": False, "disagrees": True}]):
            _decision(store, campaign_id, f"law-{i}", action="stop", rule="no_finite_dimension", at_n=65536,
                      gate=_refusal(early=early))
        _decision(store, campaign_id, "law-0", action="stop", rule="no_finite_dimension", at_n=65536,
                  gate=_refusal(early={"would_refuse": True, "agrees": True, "disagrees": False}))
        _decision(store, campaign_id, "law-9", action="run_next", rule="gate_audit", at_n=65536, next_n=262144,
                  gate=_refusal())
        assert early_stage_counts(repo.conn, 65536) == {"agree": 3, "disagree": 1, "would_refuse": 4}
        context = store.gate_context(campaign_id)
        assert context["early_stage_switch"] is False and context["early_agreements"] is None, (
            "the scan runs only while the switch is on")
        assert context["audit_in_flight"] == 1 and "retired_patterns" not in context
        gate_route.set_early_stage(repo, True)
        assert repo.get_flag(EARLY_STAGE_FLAG) == "on"
        context = _store(repo, campaign_id).gate_context(campaign_id)
        assert context["early_stage_switch"] is True and context["early_agreements"] == 3
        topics = [r["topic"] for r in repo.conn.execute("SELECT topic FROM events ORDER BY event_id").fetchall()]
        assert "gate_early_stage" in topics


def test_the_gate_s_status_counts_its_laws_and_names_no_pattern(engine_campaign):  # noqa: F811
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.research.gate_report import folder_status
    from graph_scale_dynamics.services.api import gate_route
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        for i in range(4):
            _decision(store, campaign_id, f"law-{i}", action="stop", rule="no_finite_dimension", at_n=65536,
                      gate=_refusal())
        status = folder_status(repo, campaign_id)
        assert "patterns" not in status, "the branching line was the gate's one known pattern; it left at 790"
        assert status["campaign"]["laws_by_latest_rule"] == {"no_finite_dimension": 4}
        assert not hasattr(gate_route, "retire")


def test_report_28_counts_what_the_gate_refused_saved_and_audited(engine_campaign):  # noqa: F811
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.research.gate_report import collect_gate, gate_section
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        _decision(store, campaign_id, "saved", action="stop", rule="no_finite_dimension", at_n=65536,
                  gate=_refusal())
        held = dict(_refusal(), underlying={"action": "hold", "rule": "unsettled", "next_n": 262144, "reason": "r"})
        _decision(store, campaign_id, "held", action="stop", rule="no_finite_dimension", at_n=65536, gate=held)
        _decision(store, campaign_id, "audited", action="run_next", rule="gate_audit", at_n=65536, next_n=262144,
                  gate=dict(_refusal(), audit={"sampled": True, "near_threshold": False, "due": True}))
        _decision(store, campaign_id, "audited", action="run_next", rule="d_s_settled", at_n=262144, next_n=1048576,
                  gate={"stage": "full", "result": "finite dimension"})
        _decision(store, campaign_id, "split", action="run_next", rule="d_s_settled", at_n=65536, next_n=262144,
                  gate={"stage": "full", "result": "chains disagree on structure",
                        "one_more_rung": {"why": "given_chains"}})
        record = collect_gate(repo.conn, campaign_id)
    section = gate_section(record, [{"n": 262144, "cost": {"child": {"cpu_seconds": 1200.0}}}])
    assert section["refused_total"] == 2 and section["refused_laws"] == {"no_finite_dimension (full)": 2}
    assert section["saved"]["by_rung"] == {"262144": {"rungs_refused": 1, "core_hours_estimated": 1.0}}
    assert section["saved"]["held_anyway"] == 1
    assert section["audit"]["next_rung_showed"] == {"d_s_settled (finite dimension)": 1}
    assert section["audit"]["why"] == {"the salted share": 1}
    assert section["one_more_rung"] == {"laws": 1, "next_rung_showed": {"not decided yet": 1}}
    assert "branching_line" not in section
    assert section["full_rule_reads"]["finite dimension"] == 1
