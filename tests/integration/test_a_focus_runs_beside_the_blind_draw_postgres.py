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
        assert specs[made["D"]]["ladder"][-2:] == [65536, 262144]
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
        assert laws["S"] == laws["D"] == {holder}
        current = state["current"]
        radii = {}
        for point in current["points"].values():
            radii[point["radius"]] = radii.get(point["radius"], 0) + 1
        assert radii == {1e-9: 4, 1e-6: 4, 1e-3: 4, 0.01: 8, 0.1: 8, 0.2: 8, 0.4: 8}
        assert laws["N"] == set(current["points"]) and holder not in laws["N"]
        assert current["stage"] == focus.NEIGHBOURHOOD and current["of"] == batches[2]
        assert work_groups.shares(repo) == {"A": 0.5, "N": 0.25, "D": 0.25}
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
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (made["D"],)).fetchall()} == {holder, other}
        code, text = focus.command(repo, "174", None, True)
        assert code == 0 and f"campaign {made['N']}" in text and "sensitive to: not read yet" in text
        with pytest.raises(ValueError, match="study 174"):
            focus.begin(repo, "176", tree=ROOT)
    finally:
        repo.close()
