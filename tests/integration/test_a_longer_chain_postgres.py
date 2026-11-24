from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
CANDIDATE = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())


class Log:
    def write(self, *args, **kwargs):
        pass


def test_the_longer_chain_is_every_seed_again_under_its_own_stage_and_a_raised_cap(isolated_postgres_schema):
    from graph_scale_dynamics.db.decision_store import LONGER_CHAIN_CAP_FACTOR, DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions.decider import QUEUE_ORDER
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.dsl import dsl
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    law = dsl.fingerprint(CANDIDATE)
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
        repo.insert_candidate(law, campaign_id, CANDIDATE, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        store = DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC})
        policy = Policy.from_spec(SPEC)
        store.enqueue_seeds(campaign_id, law, 4096, seeds=3, work_budget=policy.work_budget(4096),
                            queue_order=QUEUE_ORDER["base"])
        repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=?", (campaign_id,))
        assert store.longer_chains(campaign_id, law) == []
        created = store.enqueue_seeds(campaign_id, law, 4096, seeds=3, work_budget=policy.work_budget(4096),
                                      queue_order=QUEUE_ORDER[2], longer=True)
        assert created == 3, "every seed again, though all three ran"
        rows = repo.conn.execute("SELECT stage, seed, status, priority, spec_json FROM jobs WHERE campaign_id=? "
                                 "AND stage LIKE 'longer%' ORDER BY seed", (campaign_id,)).fetchall()
        assert [r["stage"] for r in rows] == ["longer_n4096_x32"] * 3 and [r["status"] for r in rows] == ["queued"] * 3
        assert all(int(r["priority"]) == QUEUE_ORDER[2] * 10_000_000 + 4096 for r in rows)
        execution = json.loads(rows[0]["spec_json"])["execution"]
        cap = int(one_shot_policy(SPEC, 4096)["max_sweeps_multiplier"])
        assert execution["sweeps_multiplier"] == 32
        assert execution["one_shot"]["max_sweeps_multiplier"] == LONGER_CHAIN_CAP_FACTOR * cap
        assert execution["one_shot"]["work_budget"] == policy.work_budget(4096), "the rung's own budget"
        assert store.longer_chains(campaign_id, law) == [4096]
        again = store.enqueue_seeds(campaign_id, law, 4096, seeds=3, work_budget=policy.work_budget(4096),
                                    queue_order=QUEUE_ORDER[2], longer=True)
        assert again == 0, "the same longer chain is not written twice"
