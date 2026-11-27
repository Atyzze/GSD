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


def test_a_focus_takes_one_law_of_study_174_into_its_neighbours_its_seeds_and_its_depth(isolated_postgres_schema):
    from graph_scale_dynamics.db.decision_store import let_through_campaigns
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.scheduling import work_groups
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        design = SD.design_for(ROOT, "174")
        SD.start(repo, design, json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        batches = sorted(str(c["campaign_id"]) for c in repo.all_campaigns())
        holder = study_map._insert(repo, batches[2], H12)
        other = study_map._insert(repo, batches[0], dict(H12, dynamics=dict(H12["dynamics"], beta=0.5)))
        assert focus.command(repo, "174", "ffff", False)[0] == 2
        assert sorted(str(c["campaign_id"]) for c in repo.all_campaigns()) == batches, "a law it lacks makes nothing"

        state = focus.begin(repo, "174", law=holder[:12], tree=ROOT)
        made = state["campaigns"]
        specs = {str(c["campaign_id"]): c["spec"] for c in repo.all_campaigns()}
        assert set(specs) == set(batches) | set(made.values())
        assert {name: specs[cid]["study_design"]["group"] for name, cid in made.items()} == {"N": "N", "S": "N", "D": "D"}
        assert specs[made["N"]]["ladder"][-1] == specs[made["S"]]["ladder"][-1] == 16384
        assert specs[made["D"]]["ladder"][-4:] == [65536, 262144, 1048576, 4194304], "open to the memory limit (873)"
        assert specs[made["S"]]["default_seeds"] == 2 * specs[made["N"]]["default_seeds"] == 6
        assert specs[made["D"]]["engine"]["policy"]["let_through_from"] > 262144
        assert set(let_through_campaigns(repo.conn)) == set(batches), "a focus's chosen laws stay out of the ledger"
        from graph_scale_dynamics.db.decision_store import study_batches
        from graph_scale_dynamics.decisions.engine import Policy
        learning = {cid for cid, _ in study_batches(repo, batches[0], Policy.from_spec(specs[batches[0]]))}
        assert learning == set(batches), "nor in the batches a gate learns from"

        laws = {name: {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (cid,)).fetchall()}
            for name, cid in made.items()}
        assert laws["S"] == {holder} and laws["D"] == set(), "the law in focus runs on more seeds; no depth of its own"
        current = state["current"]
        radii = {}
        for point in current["points"].values():
            if point["how"] == focus.KNOCKOUT:
                continue
            radii[point["radius"]] = radii.get(point["radius"], 0) + 1
        assert sorted(p["term"] for p in current["points"].values() if p["how"] == focus.KNOCKOUT) == [
            "degree_cube_sum", "degree_neighbor_gradient", "square_edge_overlap"], "each term switched off once"
        assert radii == {1e-9: 4, 1e-6: 4, 1e-3: 4, 0.01: 8, 0.1: 8, 0.2: 8, 0.4: 8}
        assert laws["N"] == set(current["points"]) and holder not in laws["N"]
        assert current["stage"] == focus.NEIGHBOURHOOD and current["of"] == batches[2]
        one = 1 / 16
        assert work_groups.shares(repo) == pytest.approx({"A": 0.5 * (1 - one), "N": 0.5 * (1 - one), "D": one}), (
            "its first law leans the folder half to the focus, the depth seeker holding one worker of sixteen")
        assert {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}[made["D"]] == 1
        allocation = {row["campaign_id"]: row["work_group"] for row in repo.worker_allocation()}
        assert {allocation[cid] for cid in batches} == {None} and allocation[made["S"]] == "N"

        found = focus.step(repo, force=True)
        assert found["stage"] == focus.NEIGHBOURHOOD and found["added"] == 0
        assert focus.load(repo)["current"]["seeds"] is None, "nothing is read before the seeds' campaign decides"

        again = focus.begin(repo, "174", law=other[:12], tree=ROOT)
        assert again["campaigns"] == made, "a folder's focus keeps its three campaigns from law to law"
        assert [(d["law"], d["stage"]) for d in again["done"]] == [(holder, focus.UNCONFIRMED)]
        assert again["current"]["law"] == other
        assert {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (made["D"],)).fetchall()} == set(), (
            "the depth campaign takes no law of its own since 893")
        assert again.get("depth_now") is None
        code, text = focus.command(repo, "174", None, True)
        assert code == 0 and f"campaign {made['N']}" in text and "sensitive to: not read yet" in text
        with pytest.raises(ValueError, match="study 174"):
            focus.begin(repo, "176", tree=ROOT)
    finally:
        repo.close()


def test_the_map_page_starts_steers_stops_and_starts_the_focus_again(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map
    from graph_scale_dynamics.scheduling import work_groups
    from graph_scale_dynamics.services.api import focus_route
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        SD.start(repo, SD.design_for(ROOT, "174"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        batches = sorted(str(c["campaign_id"]) for c in repo.all_campaigns())
        holder = study_map._insert(repo, batches[2], H12)
        empty = focus_route.answer(repo)
        assert empty["focus"] is None and empty["studies"] == [{"study": "174", "campaigns": len(batches)}]
        assert empty["defaults"]["radii"][0] == [1e-9, 4]
        with pytest.raises(ValueError, match="no focus yet"):
            focus.act(repo, {"do": "stop"})

        assert focus.act(repo, {"do": "start"}) == {"ok": True, "did": "start"}
        assert focus.load(repo)["current"] is None, "no law scores yet: nothing to focus until one does"
        focus.act(repo, {"do": "law", "law": holder[:12]})
        made = focus.load(repo)["campaigns"]
        assert focus.load(repo)["current"]["law"] == holder

        focus.act(repo, {"do": "settings", "settings": {"radii": [[0.1, 2]], "contenders": 1}})
        focus.act(repo, {"do": "split", "split": "A=1,N=1,D=2"})
        assert work_groups.shares(repo) == {"A": 0.25, "N": 0.25, "D": 0.5}

        focus.act(repo, {"do": "stop"})
        paused = {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}
        assert {paused[cid] for cid in made.values()} == {0} and focus.step(repo, force=True) is None
        assert {paused[cid] for cid in batches} == {None}, "the blind draw goes on"
        focus.act(repo, {"do": "start"})
        resumed = {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}
        assert {resumed[cid] for cid in made.values() if cid != made["D"]} == {None} and resumed[made["D"]] == 1
        assert not focus.load(repo)["stopped"]
        focus.act(repo, {"do": "lean", "focus": 0})
        assert focus.load(repo)["stopped"] and work_groups.shares(repo) == {"A": 1.0}
        off = {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}
        assert {off[cid] for cid in made.values()} == {0} and {off[cid] for cid in batches} == {None}
        focus.act(repo, {"do": "lean", "focus": 0.8})
        assert not focus.load(repo)["stopped"] and work_groups.shares(repo)["N"] == pytest.approx(0.8 * 15 / 16)
        on = {str(c["campaign_id"]): c.get("workers_target") for c in repo.all_campaigns()}
        assert on[made["D"]] == 1 and on[made["N"]] is None

        focus.act(repo, {"do": "skip", "law": holder[:12]})
        state = focus.load(repo)
        assert state["current"] is None and holder in state["skipped"]
        page = focus_route.answer(repo)["focus"]
        assert page["next_settings"]["radii"] == [[0.1, 2]] and page["settings"]["radii"][0] == [1e-9, 4]
        assert page["skipped"][holder] and page["done"][-1]["why"] == "skipped on the operator's word"
        focus.act(repo, {"do": "law", "law": holder[:12]})
        state = focus.load(repo)
        assert holder not in state["skipped"] and state["current"]["radii"] == [[0.1, 2]], "the settings, from this law"
    finally:
        repo.close()
