from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def test_study_175_starts_one_hand_campaign_holding_every_law_it_names_and_draws_none(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import study_design as SD
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        design = SD.design_for(ROOT, "175")
        first = SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        rows = repo.conn.execute("SELECT candidate_id,state FROM campaign_candidates WHERE campaign_id=?",
                                 (str(first),)).fetchall()
        assert len(rows) == design["perturb"]["laws"] == 595
        assert {row["state"] for row in rows} == {"PROPOSED"}
        holders = json.loads((ROOT / design["perturb"]["source"]).read_text(encoding="utf-8"))["holders"]
        assert {h["candidate_id"] for h in holders} <= {row["candidate_id"] for row in rows}
        spec = repo.campaign(str(first))["spec"]
        assert spec["search_policy"]["kind"] == "hand" and spec["study_design"]["kind"] == "perturb"
        assert len(repo.all_campaigns()) == 1
    finally:
        repo.close()
