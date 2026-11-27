from __future__ import annotations

import json
from copy import deepcopy
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


def _focus_on_the_old_ladder(repo, monkeypatch):
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    real = focus.plan
    old_plan = deepcopy(real(ROOT))
    old_plan["depth"]["beyond"] = [262144]
    old_plan["depth"].pop("memory_share", None)
    monkeypatch.setattr(focus, "plan", lambda tree=None: deepcopy(old_plan))
    SD.start(repo, SD.design_for(ROOT, "176"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
    own = next(iter(focus.own_campaigns(repo, "176")))
    holder = study_map._insert(repo, own, H12)
    state = focus.begin(repo, "176", law=holder[:12], tree=ROOT)
    monkeypatch.setattr(focus, "plan", real)
    return state, holder


def test_a_step_that_fails_after_its_renewal_renews_once_and_says_so_on_the_map(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import focus
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        state, holder = _focus_on_the_old_ladder(repo, monkeypatch)
        old = state["campaigns"][focus.DEPTH]
        assert max(focus.depth_ladder(repo, old)) == 262144

        def broken(_repo, _state):
            raise TypeError("keywords must be strings")

        monkeypatch.setattr(focus, "advance", broken)
        for _ in range(3):
            with pytest.raises(TypeError):
                focus.step(repo, force=True)
        depth = focus.depth_campaigns(repo, "176")
        assert len(depth) == 2, "a step that fails after its renewal makes the new depth campaign once, not each minute"
        made = focus.load(repo)["campaigns"][focus.DEPTH]
        assert made != old and control.is_paused(repo, old)
        assert max(focus.depth_ladder(repo, made)) == 4194304
        found = focus.failing(repo)
        assert found["times"] == 3 and found["error"] == "TypeError: keywords must be strings"
        doing = focus.reading(repo)["doing"]
        assert doing.startswith("the focus's step has failed 3 times since") and "nothing it reads is saved" in doing

        monkeypatch.undo()
        assert focus.step(repo, force=True) is not None
        assert focus.failing(repo) is None, "a step that passes clears the failure"
        assert "has failed" not in focus.reading(repo)["doing"]


def test_every_other_depth_campaign_of_the_focus_rests_and_one_seeker_runs_one_law(isolated_postgres_schema,
                                                                                   monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import campaign_control as control
    from graph_scale_dynamics.operations import focus
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        state, holder = _focus_on_the_old_ladder(repo, monkeypatch)
        own = next(iter(focus.own_campaigns(repo, "176")))
        anchor_spec = focus.campaign_specs(repo, "176", own, focus.plan(ROOT), ROOT)[focus.DEPTH]
        extra = [str(control.create_campaign(repo, deepcopy(anchor_spec), search_seed=i)["campaign_id"])
                 for i in (1, 2)]
        focus.step(repo, force=True)
        kept = focus.load(repo)["campaigns"][focus.DEPTH]
        assert kept == extra[0], "an existing depth campaign that fits is adopted, the lowest first"
        assert control.is_paused(repo, extra[1]) and not control.is_paused(repo, kept)
        assert {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}[kept] == 1
        held = {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (kept,)).fetchall()}
        assert held == set(), "since 893 the depth campaign takes no law of its own: the N-push is the push list"
        reading = focus.reading(repo)
        assert reading["depth_now"] is None and "the N-push on" not in reading["doing"]
        spec = repo.campaign(kept)["spec"]
        assert spec["study_design"]["focus"]["memory_share"] == 0.5
        assert spec["default_seeds"] == 3, "three seeds a size, the fewest a campaign may measure on, one at a time"
