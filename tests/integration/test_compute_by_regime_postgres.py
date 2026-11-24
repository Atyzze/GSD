from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]


def test_the_queries_read_the_ledger_beside_each_laws_dynamics(isolated_postgres_schema):
    sys.path.insert(0, str(ROOT))
    from graph_scale_dynamics.research import compute_by_regime as C
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.dsl import dsl
    spec = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
    law = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign(spec, search_seed=1)["campaign_id"])
        repo.insert_candidate(dsl.fingerprint(law), campaign_id, law, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        by_rung = [dict(r) for r in repo.conn.execute(C.BY_RUNG_SQL, (campaign_id, campaign_id)).fetchall()]
        laws = [dict(r) for r in repo.conn.execute(C.LAWS_SQL, ("", "")).fetchall()]
    summary = C.summarise(by_rung, laws)
    assert summary["laws"]["finite_temperature"] + summary["laws"]["unrecorded"] == 1
    assert summary["laws"]["zero_temperature"] == 0
