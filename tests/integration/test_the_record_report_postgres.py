from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from test_engine_campaign_decider import Log, SPEC, engine_campaign  # noqa: E402,F401


def test_the_record_is_collected_and_read(engine_campaign):  # noqa: F811
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.decisions.decider import decide_pass
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.research.record_report import build_record_sections, collect_record
    dsn, campaign_id = engine_campaign
    with Repo(dsn) as repo:
        for index, outcome in enumerate(["admitted", "invalid:no_sparse_phase", "invalid:no_sparse_phase",
                                         "duplicate_law"]):
            repo.conn.execute("INSERT INTO proposal_draws(campaign_id,stream_index,draw_index,outcome,candidate_id,"
                              "law_json,created_utc) VALUES(?,?,?,?,?,?,?)",
                              (campaign_id, 0, index, outcome, None, json.dumps({}), utc_now()))
        store = DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})
        decide_pass(store, campaign_id, store.policy)
        record = collect_record(repo, campaign_id)
    sections = build_record_sections(record)
    ledger = sections["draw_ledger"]
    assert ledger["draws"] == 4 and ledger["admitted_share"] == 0.25
    assert ledger["refused_by_reason"]["invalid:no_sparse_phase"] == {"draws": 2, "share": 0.5}
    replayed = sections["decision_record"]
    assert replayed["decisions"] >= 1 and replayed["replay_share"] == 1.0, replayed
    assert sections["depth_audit"]["audited_decisions"] == 0
    assert "no attempt carries a cost record" in sections["cost_per_attempt"]["why"]
    assert "error" not in record["reset"], record["reset"]
    assert sections["reset_rules"]["parks"]["laws_parked"] == 0
    assert sections["compute_by_regime"]["laws"]["zero_temperature"] == 0
    assert sections["spectral_windows"]["whole_range_test"]["judged"] == 0


def test_the_costs_are_split_child_from_bookkeeping_per_rung():
    from graph_scale_dynamics.research.record_report import build_record_sections
    record = {"costs": [{"n": 1024, "cost": {"child": {"cpu_seconds": 4.0, "io": {"write_bytes": 100}},
                                             "bookkeeping": {"cpu_seconds": 0.5, "io": {"write_bytes": 10}}}},
                        {"n": 1024, "cost": {"child": {"cpu_seconds": 6.0, "io": {"write_bytes": 300}},
                                             "bookkeeping": {"cpu_seconds": 0.7, "io": {"write_bytes": 30}}}}]}
    costs = build_record_sections(record)["cost_per_attempt"]["by_rung"]["1024"]
    assert costs["child_cpu_seconds"]["median"] == 5.0 and costs["bookkeeping_write_bytes"]["median"] == 20.0
