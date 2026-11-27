from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics/resources/configs/campaign_engine_survey.json").read_text())
GIB = 1024 ** 3
H12 = {"dsl_version": 1, "init": "empty",
       "dynamics": {"beta": 0.188203, "kind": "equilibrium", "locality": 0.357622,
                    "move_mix": {"add": 0.025633, "delete": 0.025633, "swap": 0.948734}, "sweeps": 30},
       "terms": [{"coeff": {"c0": 1.22227, "scale": "one"}, "op": "degree_cube_sum", "params": {}},
                 {"coeff": {"c0": -0.0113247, "scale": "one"}, "op": "degree_neighbor_gradient", "params": {}},
                 {"coeff": {"c0": -1.76001, "scale": "one"}, "op": "square_edge_overlap", "params": {}}]}


def _start(repo):
    from graph_scale_dynamics.operations import study_design as SD
    return SD.start(repo, SD.design_for(ROOT, "176"), json.loads(json.dumps(SURVEY)), tree=ROOT,
                    log=lambda *_a: None)


def _law(repo, campaign_id: str) -> str:
    from graph_scale_dynamics.operations import study_map
    return str(study_map._insert(repo, campaign_id, H12))


def test_a_focus_on_the_old_ladder_moves_its_depth_seeker_to_one_open_to_the_memory_limit(isolated_postgres_schema,
                                                                                         monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    init_db(isolated_postgres_schema.dsn)
    real = focus.plan
    with Repo(isolated_postgres_schema.dsn) as repo:
        old_plan = deepcopy(real(ROOT))
        old_plan["depth"]["beyond"] = [262144]
        monkeypatch.setattr(focus, "plan", lambda tree=None: deepcopy(old_plan))
        _start(repo)
        state = focus.begin(repo, "176", tree=ROOT)
        old = state["campaigns"][focus.DEPTH]
        assert max(focus.depth_ladder(repo, old)) == 262144, "a focus begun before 873"
        own = next(iter(focus.own_campaigns(repo, "176")))
        law = _law(repo, own)
        focus._insert(repo, old, focus._spec_of(repo, own, law))
        state["contenders"][law] = {"of": own, "score": 9, "label": "S176C1G1", "joined_utc": "2026-11-26T00:00:00Z"}
        focus.save(repo, state)
        monkeypatch.setattr(focus, "plan", real)
        made = focus.renew_depth(repo, state, tree=ROOT)
        assert made and made != old and state["campaigns"][focus.DEPTH] == made
        assert max(focus.depth_ladder(repo, made)) == 4194304, "the ladder open to 4,194,304"
        from graph_scale_dynamics.operations import campaign_control
        assert campaign_control.is_paused(repo, old), "the old depth campaign rests, its readings kept"
        assert focus.load(repo)["campaigns"][focus.DEPTH] == made, "the renewal is saved the moment it is made"
        assert focus.depth_next(repo, state, []) is None
        held = {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (made,)).fetchall()}
        assert held == set(), "since 893 the depth campaign takes no contender: the push list has its own ladder"
        assert focus.renew_depth(repo, state, tree=ROOT) is None, "renewed once"
        assert state["depth_before"][0]["campaign"] == old
        stale = focus.load(repo)
        stale["campaigns"][focus.DEPTH] = old
        assert focus.renew_depth(repo, stale, tree=ROOT) == made, (
            "a state that missed its save adopts the campaign already made rather than make another")
        assert len(focus.depth_campaigns(repo, "176")) == 2


def test_a_depth_law_whose_next_size_would_not_fit_is_written_down_for_the_decider(isolated_postgres_schema):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.decisions import memory_ceiling as MC
    from graph_scale_dynamics.operations import depth_reach as D
    from graph_scale_dynamics.operations import focus
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        _start(repo)
        state = focus.begin(repo, "176", tree=ROOT)
        depth = state["campaigns"][focus.DEPTH]
        own = next(iter(focus.own_campaigns(repo, "176")))
        law = _law(repo, own)
        focus._insert(repo, depth, focus._spec_of(repo, own, law))
        for n, peak in ((65536, 1 * GIB), (262144, 4 * GIB)):
            repo.insert_job(job_id=f"deep-{n}", campaign_id=depth, candidate_id=law, kind="simulate", stage="base",
                            n=n, seed=0, spec={})
            repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,started_utc,wall_seconds,peak_rss_bytes) "
                              "VALUES(?,?,?,?,?,?)", (f"a-{n}", f"deep-{n}", 1, "2026-11-26T00:00:00Z", 60.0, peak))
        assert D.peaks(repo, depth, law) == {65536: 1 * GIB, 262144: 4 * GIB}
        ladder = focus.depth_ladder(repo, depth)
        assert D.keep(repo, depth, [law], ladder, room={"reach_bytes": 40 * GIB, "floor_bytes": 10 * GIB}) == {}, (
            "17.6 GiB fits 40")
        added = D.keep(repo, depth, [law], ladder, room={"reach_bytes": 12 * GIB, "floor_bytes": 10 * GIB})
        assert added[law]["next_n"] == 1048576 and added[law]["reach_bytes"] == 12 * GIB
        store = DecisionStore(repo, lambda *_a, **_k: None, repo.campaign(depth))
        assert store.memory_ceilings(depth) == {law: added[law]}, "the decider reads what the focus wrote"
        assert store.memory_ceilings(own) == {}, "and only for the depth campaign"
        assert D.keep(repo, depth, [law], ladder, room={"reach_bytes": 1 * GIB, "floor_bytes": 10 * GIB}) == {}, (
            "written once")
        assert MC.flag_value(repo.get_flag(MC.FLAG, ""))["contract"] == MC.CONTRACT
