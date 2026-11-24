from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


class Log:
    def write(self, *args, **kwargs):
        pass


@pytest.mark.parametrize("kind", ["engine", "lattice", "deep"])
def test_a_benchmark_campaign_enqueues_its_first_rung(isolated_postgres_schema, kind):
    from tools import benchmark_campaign as B
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.decider import decide_pass
    from graph_scale_dynamics.dsl import dsl

    spec = {"engine": B.benchmark_spec, "lattice": B.lattice_spec, "deep": B.deep_spec}[kind](
        json.loads(B.DEFAULT_SPEC.read_text()))
    law = B.lattice_laws()[4]["spec"]
    law_id = dsl.fingerprint(law)
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(spec, search_seed=1)["campaign_id"])
        repo.insert_candidate(law_id, campaign_id, law, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        store = DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": spec})
        tally = decide_pass(store, campaign_id, store.policy)
        assert tally[("run_next", "start")] == 1, tally
        jobs = repo.conn.execute("SELECT n,seed,spec_json FROM jobs WHERE campaign_id=? AND candidate_id=? "
                                 "ORDER BY seed", (campaign_id, law_id)).fetchall()
        assert [j["n"] for j in jobs] == [64] * store.policy.seeds
        budget = store.policy.work_budget(64)
        assert all(json.loads(j["spec_json"])["execution"]["one_shot"]["work_budget"] == budget for j in jobs)
