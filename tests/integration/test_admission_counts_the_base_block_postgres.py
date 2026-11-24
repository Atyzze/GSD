from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = dict(json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text()),
            max_active_candidates=2)
CANDIDATE = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())


class Log:
    def write(self, *args, **kwargs):
        pass


def _law(k: int) -> tuple[str, dict]:
    from graph_scale_dynamics.dsl import dsl
    spec = copy.deepcopy(CANDIDATE)
    spec["terms"][1]["coeff"]["c0"] = round(0.3 + 0.01 * k, 4)
    return dsl.fingerprint(spec), spec


@pytest.fixture
def campaign(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
    return isolated_postgres_schema.dsn, campaign_id


def _store(repo, campaign_id):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    return DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})


def _running(repo, store, campaign_id, k, state, action, next_n):
    law, spec = _law(k)
    repo.insert_candidate(law, campaign_id, spec, "equilibrium", 2, state)
    store.record_decision(campaign_id, {"law": law, "action": action, "rule": "r", "reason": "r", "at_n": 4096,
                                        "next_n": next_n, "engine": "decision-engine-2"})
    if action == "run_next":
        for seed in range(3):
            repo.insert_job(job_id=f"{law[:40]}-{next_n}-{seed}", campaign_id=campaign_id, candidate_id=law,
                            kind="simulate", stage=f"rung_n{next_n}", n=next_n, seed=seed, replicate=0, spec={},
                            priority=next_n, requested_by="decider", sealed=False)
    return law


def _proposed(repo, campaign_id, ks):
    for k in ks:
        law, spec = _law(k)
        repo.insert_candidate(law, campaign_id, spec, "equilibrium", 2, "PROPOSED")


def _admit(repo, campaign_id):
    from graph_scale_dynamics.services.controller.engine_campaign import admit_proposed
    return admit_proposed(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC}, _store(repo, campaign_id))


def test_laws_waiting_at_bought_deep_rungs_leave_the_places_free(campaign):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        for k in (1, 2):
            _running(repo, store, campaign_id, k, "EXTENDING", "run_next", 65536)
        _proposed(repo, campaign_id, (10, 11))
        assert _admit(repo, campaign_id) == 2, "bought rungs hold no admission place"
        states = [r["state"] for r in repo.conn.execute(
            "SELECT state FROM campaign_candidates WHERE campaign_id=? AND state='BASE_BLOCK_RUNNING'",
            (campaign_id,)).fetchall()]
        assert len(states) == 2


def test_laws_in_their_base_block_fill_the_places(campaign):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        _running(repo, store, campaign_id, 1, "BASE_BLOCK_RUNNING", "run_next", 1024)
        _running(repo, store, campaign_id, 2, "BASE_BLOCK_RUNNING", "run_next", 4096)
        _proposed(repo, campaign_id, (10,))
        assert _admit(repo, campaign_id) == 0


def test_a_law_admitted_and_not_yet_started_holds_its_place(campaign):
    from graph_scale_dynamics.db.repo import Repo
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        _proposed(repo, campaign_id, (10, 11, 12))
        assert _admit(repo, campaign_id) == 2
        assert _admit(repo, campaign_id) == 0, "the two admitted laws fill both places before any job exists"


def test_held_and_finishing_laws_hold_no_place_and_both_counts_agree(campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.scheduling.admission import SLOT_BASE_BLOCK
    from graph_scale_dynamics.services.proposer.main import admission
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        _running(repo, store, campaign_id, 1, "HELD", "hold", 1048576)
        _running(repo, store, campaign_id, 2, "BASE_BLOCK_RUNNING", "stop", None)
        _running(repo, store, campaign_id, 3, "BASE_BLOCK_RUNNING", "run_next", 256)
        window = admission(repo.live_laws_latest_decision(campaign_id), pool_min=4, max_active=2,
                           top_base_n=4096)
        assert window["counts"][SLOT_BASE_BLOCK] == 1
        _proposed(repo, campaign_id, (10, 11))
        assert _admit(repo, campaign_id) == 1, "the controller counts what the proposer's window counts"


def test_laws_waiting_to_learn_give_up_their_place_up_to_a_learning_group(campaign):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.scheduling.admission import note_waiting_to_learn, waiting_to_learn
    dsn, campaign_id = campaign
    with Repo(dsn) as repo:
        store = _store(repo, campaign_id)
        first = _running(repo, store, campaign_id, 1, "BASE_BLOCK_RUNNING", "run_next", 1024)
        second = _running(repo, store, campaign_id, 2, "BASE_BLOCK_RUNNING", "run_next", 4096)
        deep = _running(repo, store, campaign_id, 3, "EXTENDING", "run_next", 65536)
        _proposed(repo, campaign_id, (10, 11, 12))
        assert _admit(repo, campaign_id) == 0, "two laws in their base block fill both places"
        live = repo.live_laws_latest_decision(campaign_id)
        assert note_waiting_to_learn(repo, campaign_id, {first, second, deep}, live, 4096, 1) == [min(first, second)]
        assert waiting_to_learn(repo, campaign_id) == {min(first, second)}, "a deep law holds no place to give up"
        assert _admit(repo, campaign_id) == 1, "one law waiting to learn gives up its place, at most one group"
        note_waiting_to_learn(repo, campaign_id, set(), repo.live_laws_latest_decision(campaign_id), 4096, 1)
        assert waiting_to_learn(repo, campaign_id) == set() and repo.get_flag(f"learning_waits:{campaign_id}") == ""
