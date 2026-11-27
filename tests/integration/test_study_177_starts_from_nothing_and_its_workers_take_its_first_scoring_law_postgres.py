from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}


def _held(repo, campaign_id: str) -> set[str]:
    return {r["candidate_id"] for r in repo.conn.execute(
        "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (str(campaign_id),)).fetchall()}


def test_study_177_starts_from_nothing_and_the_zone_and_depth_workers_take_its_first_scoring_law(
        isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.operations import study_seed
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        design = SD.design_for(ROOT, "177")
        assert len(set(design["search_seeds"])) == 11
        assert not set(design["search_seeds"]) & set(SD.design_for(ROOT, "176")["search_seeds"]), "new seeds"
        SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        kinds = {str(c["campaign_id"]): (c["spec"]["study_design"]["kind"], c["spec"]["study_design"]["group"])
                 for c in repo.all_campaigns()}
        assert sorted(kinds.values()) == sorted([("blind", "A")] * 10 + [("seed", "N")] + [("focus", "N")] * 2
                                                + [("focus", "D")])
        seeded = study_seed.seeded_campaign(repo, "177")
        assert _held(repo, seeded) == set(), "nothing seeded"
        state = focus.load(repo)
        assert state["current"] is None and state["contenders"] == {}
        assert focus.step(repo, force=True) is not None
        assert focus.load(repo)["current"] is None, "no law scores yet: the zone and depth workers wait"

        blind = sorted((cid for cid, kind in kinds.items() if kind[0] == "blind"), key=int)
        first = study_map._insert(repo, blind[4], H12)
        scored = [{"candidate_id": first, "campaign": blind[4], "score": 1, "graph": 1, "label": "S177C5G1"}]
        monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
        assert focus.step(repo, force=True)["label"]
        state = focus.load(repo)
        made = state["campaigns"]
        assert state["current"]["law"] == first and state["current"]["of"] == blind[4]
        assert _held(repo, made[focus.SEEDS]) == {first}, "the zone worker runs the law on more seeds"
        assert len(_held(repo, made[focus.NEIGHBOURS])) == len(state["current"]["points"]) > 40, (
            "and its neighbours and its terms switched off")
        assert _held(repo, made[focus.DEPTH]) == {first}, "the depth worker takes the law in focus first"
        assert state["depth_now"]["law"] == first
        assert [c["campaign_id"] for c in focus.depth_campaigns(repo, "177")] == [made[focus.DEPTH]]
        spec = repo.campaign(made[focus.DEPTH])["spec"]
        assert spec["study_design"]["focus"]["memory_share"] == 0.5 and spec["ladder"][-1] == 4194304
        assert {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}[made[focus.DEPTH]] == 1
        doing = focus.reading(repo)["doing"]
        assert doing.startswith("in focus: ") and "the depth seeker on " in doing and "has failed" not in doing

        second = study_map._insert(repo, blind[1], dict(H12, dynamics=dict(H12["dynamics"], beta=0.3)))
        scored.insert(0, {"candidate_id": second, "campaign": blind[1], "score": 5, "graph": 2, "label": "S177C2G2"})
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert second in state["contenders"] and _held(repo, made[focus.DEPTH]) == {first}, (
            "a better law waits its turn: the depth worker ends one law before it begins the next")
