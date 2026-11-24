from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

SPEC = json.loads((Path(__file__).resolve().parents[2]
                   / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


@pytest.fixture
def world(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.gates import LET_THROUGH_RULE
    from graph_scale_dynamics.observability.log import Log
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    spec = json.loads(json.dumps(SPEC))
    engine = dict(spec.get("engine") or {})
    engine["policy"] = dict(engine.get("policy") or {}, let_through_rule=LET_THROUGH_RULE, confirm_after=3,
                            known_result_after=2, learn_in_batches_of=3)
    spec["engine"] = engine
    campaign = str(repo.create_campaign(spec, search_seed=7)["campaign_id"])
    yield repo, DecisionStore(repo, Log(tmp_path, "controller"), {"spec": spec}), campaign, spec
    repo.close()


def _decide(store, campaign, law, n, action, rule, salted=(), signature=None):
    facts = {"salted": list(salted)} if salted else {}
    if signature:
        facts["signature"] = signature
    store.record_decision(campaign, {"law": law, "action": action, "rule": rule, "reason": "test", "at_n": n,
                                     "next_n": None, "engine": "decision-engine-2", "facts": facts})


def test_the_ledger_counts_the_study_s_own_decisions_and_clamps(world):
    from graph_scale_dynamics.db.decision_store import let_through_ledger
    from graph_scale_dynamics.decisions import gates as G
    from graph_scale_dynamics.decisions.decider import learned_for
    from graph_scale_dynamics.decisions.engine import Policy
    repo, store, campaign, spec = world
    for i in range(3):
        law = f"law{i}".ljust(64, "0")
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        _decide(store, campaign, law, 4096, "run_next", "salted", ["starts_alike"], signature="ring")
        _decide(store, campaign, law, 16384, "stop", "starts_alike", signature="ring")
    policy = Policy.from_spec(spec)
    ledger = let_through_ledger(repo.conn, "test", fresh=True)
    entry = ledger.document(policy)["gates"]["starts_alike"]["4096"]
    assert (entry["let_through"], entry["clean"], entry["same_gate"], entry["missed"]) == (3, 3, 3, 0)
    assert entry["label"] == "confirmed" and ledger.share("starts_alike", 4096, policy) == G.CONFIRMED_SHARE
    assert ledger.known_results(policy) == ((4096, "ring"),)
    law = "law-miss".ljust(64, "0")
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
    live, learned = learned_for(store, store.fixed_points(campaign), policy, law, 4096)
    assert ("starts_alike", 4096, G.CONFIRMED_SHARE) in live.salt_shares and live.known_results
    assert (learned["number"], learned["batch"], learned["laws_learned_from"], learned["decisions_read"]) == (4, 1, 3, 6)
    first, _ = learned_for(store, store.fixed_points(campaign), policy, "law0".ljust(64, "0"), 4096)
    assert first.salt_shares == () and first.known_results == (), "the first batch learns from no law"
    _decide(store, campaign, law, 4096, "run_next", "salted", ["starts_alike"])
    _decide(store, campaign, law, 16384, "run_next", "starts_shape")
    again = let_through_ledger(repo.conn, "test", fresh=True)
    assert again.share("starts_alike", 4096, policy) == G.TESTING_SHARE, "a miss puts the gate back to 10%"
