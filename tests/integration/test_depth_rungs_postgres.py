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


def _setup(dsn):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.dsl import dsl
    law = dsl.fingerprint(CANDIDATE)
    init_db(dsn)
    repo = Repo(dsn)
    campaign_id = str(repo.create_campaign(SPEC, search_seed=1)["campaign_id"])
    repo.insert_candidate(law, campaign_id, CANDIDATE, "equilibrium", 1, "EXTENDING")
    return repo, DecisionStore(repo, Log(), {"campaign_id": campaign_id, "spec": SPEC}), campaign_id, law


def test_a_priority_one_rung_has_twice_its_window(isolated_postgres_schema):
    from graph_scale_dynamics.decisions.decider import apply
    from graph_scale_dynamics.decisions.engine import RUN_NEXT, Decision, Policy
    repo, store, campaign_id, law = _setup(isolated_postgres_schema.dsn)
    with repo:
        policy = Policy.from_spec(dict(SPEC, engine=dict(SPEC["engine"], policy=dict(SPEC["engine"]["policy"],
                                                                                     every_chain=True))))
        budget = policy.work_budget(16384)
        shape = Decision(law=law, action=RUN_NEXT, rule="starts_shape", reason="a shape", at_n=4096,
                         next_n=16384, priority=1)
        assert apply(store, campaign_id, shape, policy)["jobs_created"] == 3
        rows = repo.conn.execute("SELECT stage, spec_json FROM jobs WHERE campaign_id=? ORDER BY seed",
                                 (campaign_id,)).fetchall()
        spec = json.loads(rows[0]["spec_json"])
        assert rows[0]["stage"].startswith("rung_n16384")
        assert spec["execution"]["one_shot"]["work_budget"] == 2 * budget
        assert "timeout_seconds" not in spec


def test_a_law_whose_evidence_rebuild_failed_for_good_is_decided_on(isolated_postgres_schema):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.domain.model import utc_now
    repo, store, campaign_id, law = _setup(isolated_postgres_schema.dsn)
    with repo:
        now = utc_now()
        repo.conn.execute(
            "INSERT INTO candidate_evidence_rebuilds(campaign_id,candidate_id,analysis_version,status,attempts,"
            "max_attempts,error,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?)",
            (campaign_id, law, ANALYSIS_VERSION, "failed", 8, 8, "KeyError: 'REFUSED_SOMETHING_NEW'", now, now))
        evidence = store.law_evidence(campaign_id, law)
        assert "pending" not in evidence, "it read as pending for ever"
        assert "failed for good after 8 attempts" in evidence["evidence_failed"]
        assert "REFUSED_SOMETHING_NEW" in evidence["evidence_failed"]
