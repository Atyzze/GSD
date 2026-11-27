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
G = 1024 ** 3


def _law(beta: float) -> dict:
    return dict(H12, dynamics=dict(H12["dynamics"], beta=beta))


def _run(repo, campaign: str, law: str, n: int, seed: int, peak: int | None = None) -> None:
    job_id = f"push-{campaign}-{law[:10]}-{n}-{seed}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=n,
                    seed=seed, spec={}, priority=100000000 + n)
    repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job_id,))
    repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,"
                      "peak_rss_bytes,wall_seconds,peak_edge_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (f"a-{job_id}", job_id, 1, "w", "2026-11-27T01:00:00Z", "2026-11-27T01:10:00Z", 0, peak, 600.0,
                       4 * n))


def test_a_law_pushed_on_its_page_goes_first_to_the_depth_worker_while_nothing_is_in_focus(isolated_postgres_schema,
                                                                                             monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import depth_reach, focus, push, study_map
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.services.api import focus_route
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "178"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        blind = sorted((str(c["campaign_id"]) for c in repo.all_campaigns()
                        if c["spec"]["study_design"]["kind"] == "blind"), key=int)
        first = study_map._insert(repo, blind[2], _law(0.19))
        second = study_map._insert(repo, blind[5], _law(0.31))
        state = focus.load(repo)
        depth = str(state["campaigns"][focus.DEPTH])
        focus.step(repo, force=True)
        assert focus.load(repo)["current"] is None and not focus.load(repo).get("depth_now"), "nothing scores"

        done = focus_route.act(repo, {"do": "push", "law": first, "campaign": blind[2]})
        assert done["pushed"] == [first] and repo.campaign(depth)["workers_target"] == 1
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert state["current"] is None and state["depth_now"]["law"] == first, (
            "a pushed law needs no score and no law in focus: the depth worker takes it")
        held = {r["candidate_id"] for r in repo.conn.execute(
            "SELECT candidate_id FROM campaign_candidates WHERE campaign_id=?", (depth,)).fetchall()}
        assert first in held

        focus.act(repo, {"do": "push", "law": second[:12]})
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert [e["law"] for e in state["pushed"]] == [first, second] and state["depth_now"]["law"] == first, (
            "the law the depth worker runs is finished first; the next pushed waits")
        assert focus.depth_line(state, [])[:2] == [first, second]

        focus.act(repo, {"do": "unpush", "law": first, "campaign": blind[2]})
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert [e["law"] for e in state["pushed"]] == [second] and state["depth_now"]["law"] == second, (
            "taken off the list, it is no longer a contender: the depth worker turns to the next pushed")
        depth = str(state["depth_now"]["campaign"])

        for n, peak in ((16384, 2 * G), (65536, 8 * G)):
            for seed in range(3):
                _run(repo, depth, second, n, seed, peak)
        _run(repo, blind[0], study_map._insert(repo, blind[0], _law(0.41)), 4096, 0)
        monkeypatch.setattr(depth_reach, "room_for", lambda repo, campaign_id: depth_reach.room_of_share(0.5, 92 * G))
        found = focus_route.top(repo)
        assert found["focus"] is True and [e["law"] for e in found["pushed"]] == [second]
        assert found["top"][0]["law"] == second and found["top"][0]["deepest"] == 65536 and found["top"][0]["running"]
        assert found["top"][1]["deepest"] == 4096 and found["laws_read"] == 2
        law = found["law"]
        assert law["law"] == second and [s["n"] for s in law["sizes"]] == [16384, 65536]
        assert law["sizes"][1]["peak_bytes"] == 8 * G and law["sizes"][1]["runs"] == 3
        f = law["forecast"]
        assert f["reach_bytes"] == 46 * G and f["ahead"][0]["n"] == 262144 and f["ahead"][0]["fits"]
        assert f["limit"]["n"] == 1048576 and f["limit"]["short_bytes"] == f["limit"]["needs_bytes"] - 46 * G
        assert f["words"].startswith("N=1,048,576 would need") and "more than the 46.0 GiB" in f["words"]

        with pytest.raises(ValueError, match="name the law"):
            push.toggle(repo, "")
