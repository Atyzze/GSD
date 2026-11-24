from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def _batch(index: int, *, learn_in: int = 2) -> dict:
    from graph_scale_dynamics.operations import study_design as SD
    design = SD.design_for(ROOT, "170")
    spec = SD.campaign_spec(design, SD.without_terms(design, json.loads(json.dumps(SURVEY)), log=lambda *_a: None),
                            design["campaigns"][index], index)
    spec["engine"]["policy"]["learn_in_batches_of"] = learn_in
    return spec


@pytest.fixture
def study(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.log import Log
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    specs = [_batch(0), _batch(1)]
    ids = [str(repo.create_campaign(spec, search_seed=11 + i)["campaign_id"]) for i, spec in enumerate(specs)]
    controls = str(repo.create_campaign(json.loads(json.dumps(SURVEY)), search_seed=3)["campaign_id"])
    for i, campaign in enumerate(ids):
        for n in range(3):
            repo.insert_candidate(f"b{i}l{n}".ljust(64, "4"), campaign, {"terms": [], "n": [i, n]}, "equilibrium", 1,
                                  "EXTENDING")
    repo.insert_candidate("c0".ljust(64, "4"), controls, {"terms": [], "c": 0}, "equilibrium", 1, "EXTENDING")
    stores = [DecisionStore(repo, Log(tmp_path, "controller"), {"spec": spec}) for spec in specs]
    yield repo, stores, ids, controls
    repo.close()


def _decide(store, campaign, law, n, action, rule, salted=()):
    store.record_decision(campaign, {"law": law, "action": action, "rule": rule, "reason": "test", "at_n": n,
                                     "next_n": None, "engine": "decision-engine-2",
                                     "facts": {"salted": list(salted)} if salted else {}})


def test_every_batch_of_the_study_is_read_in_its_place_and_nothing_else(study, tmp_path):
    repo, stores, (first, second), controls = study
    assert stores[0].study_batches(first) == [(first, 0), (second, 1)]
    assert stores[1].study_batches(second) == [(first, 0), (second, 1)]
    laws = stores[0].learning_laws(first)
    assert sorted({(law["campaign_id"], law["campaign_order"]) for law in laws}) == [(first, 0), (second, 1)]
    assert len(laws) == 6 and sorted(law["number"] for law in laws) == [1, 1, 2, 2, 3, 3]
    points = stores[0].fixed_points(first)
    assert points.read == [[first, 0], [second, 1]]
    assert set(points.numbers) == {f"b0l{n}".ljust(64, "4") for n in range(3)}, "a batch numbers only its own laws"
    assert [len(points.groups[g]) for g in sorted(points.groups)] == [4, 2], "a group holds every batch's laws"
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.observability.log import Log
    alone = DecisionStore(repo, Log(tmp_path, "controller"),
                          {"spec": json.loads(json.dumps(SURVEY))})
    assert alone.study_batches(controls) == [(controls, 0)], "a campaign outside the study learns from itself"


def test_a_law_of_the_second_group_learns_from_every_batch_and_says_which(study):
    from graph_scale_dynamics.decisions.decider import learned_for
    repo, stores, (first, second), _controls = study
    for i, campaign in enumerate((first, second)):
        for n in range(2):
            law = f"b{i}l{n}".ljust(64, "4")
            _decide(stores[i], campaign, law, 256, "run_next", "salted", ["empty"])
            _decide(stores[i], campaign, law, 1024, "stop", "too_dense")
    keys = [(first, "b0l0".ljust(64, "4")), (second, "b1l0".ljust(64, "4"))]
    rows = stores[0].learning_rows(keys)
    assert [(r["campaign_id"], r["at_n"]) for r in rows] == [(first, 256), (first, 1024), (second, 256), (second, 1024)]
    assert rows[0]["salted"] == ["empty"]
    policy = stores[0].policy
    _, learned = learned_for(stores[0], stores[0].fixed_points(first), policy, "b0l2".ljust(64, "4"), 256)
    assert learned["batch"] == 1 and learned["laws_learned_from"] == 4 and learned["decisions_read"] == 8
    assert learned["campaigns"] == [[first, 0], [second, 1]]


def test_a_group_is_learned_from_only_once_every_batch_has_drawn_it(study):
    from graph_scale_dynamics.decisions.decider import learned_for
    repo, stores, (first, second), _controls = study
    for i, campaign in enumerate((first, second)):
        for n in range(3):
            _decide(stores[i], campaign, f"b{i}l{n}".ljust(64, "4"), 256, "stop", "empty")
            repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE candidate_id=?",
                              (f"b{i}l{n}".ljust(64, "4"),))
    repo.insert_candidate("b0l3".ljust(64, "4"), first, {"terms": [], "n": [0, 3]}, "equilibrium", 1, "EXTENDING")
    repo.insert_candidate("b0l4".ljust(64, "4"), first, {"terms": [], "n": [0, 4]}, "equilibrium", 1, "EXTENDING")
    asking = "b0l4".ljust(64, "4")
    policy, learned = learned_for(stores[0], stores[0].fixed_points(first), stores[0].policy, asking, 256)
    assert (policy, learned) == (None, None), "the second batch has not drawn laws 3 and 4, so group 1 is open"
    from graph_scale_dynamics.operations.study import set_law_budget
    assert set_law_budget(repo, second, 3)["ok"] and set_law_budget(repo, first, 5)["ok"]
    repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE candidate_id=?", ("b0l3".ljust(64, "4"),))
    _decide(stores[0], first, "b0l3".ljust(64, "4"), 256, "stop", "empty")
    _, learned = learned_for(stores[0], stores[0].fixed_points(first), stores[0].policy, asking, 256)
    assert learned["batch"] == 2 and learned["laws_learned_from"] == 7, "the second batch drew all it will"
    assert set_law_budget(repo, second, 4)["ok"]
    repo.insert_candidate("b1l3".ljust(64, "4"), second, {"terms": [], "n": [1, 3]}, "equilibrium", 1, "STOPPED")
    _decide(stores[1], second, "b1l3".ljust(64, "4"), 256, "stop", "empty")
    _, learned = learned_for(stores[0], stores[0].fixed_points(first), stores[0].policy, asking, 256)
    assert learned["laws_learned_from"] == 8 and learned["decisions_read"] == 8, (
        "a law that joins a group already learned from is read: the group is learned again, as a fresh process would")


def test_a_study_of_one_batch_learns_and_records_as_before(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.decider import learned_for
    from graph_scale_dynamics.observability.log import Log
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        spec = _batch(0)
        campaign = str(repo.create_campaign(spec, search_seed=5)["campaign_id"])
        repo.insert_candidate("solo".ljust(64, "4"), campaign, {"terms": []}, "equilibrium", 1, "EXTENDING")
        store = DecisionStore(repo, Log(tmp_path, "controller"), {"spec": spec})
        assert store.study_batches(campaign) == [(campaign, 0)]
        _, learned = learned_for(store, store.fixed_points(campaign), store.policy, "solo".ljust(64, "4"), 256)
        assert "campaigns" not in learned, "a decision made on one campaign records what it recorded before"
