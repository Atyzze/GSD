from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())


def test_study_176_starts_ten_blind_batches_and_a_map_of_the_ten_best_half_the_fleet_each(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.scheduling import work_groups
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        design = SD.design_for(ROOT, "176")
        SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        campaigns = {str(c["campaign_id"]): c["spec"] for c in repo.all_campaigns()}
        groups = {cid: spec["study_design"]["group"] for cid, spec in campaigns.items()}
        assert sorted(groups.values()) == ["A"] * 10 + ["B"]
        mapped = next(cid for cid, group in groups.items() if group == "B")
        assert campaigns[mapped]["search_policy"]["kind"] == "hand"
        assert campaigns[mapped]["engine"]["policy"]["gate_from"] == []
        blind = next(cid for cid, group in groups.items() if group == "A")
        assert campaigns[blind]["engine"]["policy"]["gate_from"] == [["nothing_read", 16384]]
        rows = repo.conn.execute("SELECT candidate_id,state FROM campaign_candidates WHERE campaign_id=?",
                                 (mapped,)).fetchall()
        assert len(rows) == design["map"]["laws"] == 125 and {row["state"] for row in rows} == {"PROPOSED"}
        assert work_groups.shares(repo) == {"A": 0.5, "B": 0.5}
        state = study_map.load(repo)
        assert state["campaign"] == mapped and len(state["regions"]) == 10
        assert {law for region in state["regions"].values() for law in region["points"]} == {
            row["candidate_id"] for row in rows}
        allocation = {row["campaign_id"]: row["work_group"] for row in repo.worker_allocation()}
        assert allocation == groups
        work_groups.set_shares(repo, {"A": 3, "B": 1})
        SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None,
                 made={i: cid for i, cid in enumerate(sorted(campaigns, key=int))})
        assert work_groups.shares(repo) == {"A": 0.75, "B": 0.25}, "a split the operator set is never reset"
    finally:
        repo.close()
