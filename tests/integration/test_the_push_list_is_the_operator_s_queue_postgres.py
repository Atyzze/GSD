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
G = 10 ** 9


def _law(beta: float) -> dict:
    return dict(H12, dynamics=dict(H12["dynamics"], beta=beta))


@pytest.fixture
def folder(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus, push_ladder, study_map
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.scheduling import worker_count
    from graph_scale_dynamics.services.worker import main as W
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    SD.start(repo, SD.design_for(ROOT, "178"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
    blind = sorted((str(c["campaign_id"]) for c in repo.all_campaigns()
                    if c["spec"]["study_design"]["kind"] == "blind"), key=int)
    laws = {"held": study_map._insert(repo, blind[2], _law(0.19)), "steered": study_map._insert(repo, blind[5], _law(0.31)),
            "later": study_map._insert(repo, blind[6], _law(0.37))}
    repo.set_flag(worker_count.MOST_FLAG, "32")
    repo.set_flag(worker_count.FLAG, "4")
    monkeypatch.setattr(push_ladder, "reach", lambda repo: 40 * G)
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * G))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: G // 10)
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    focus.step(repo, force=True)
    yield repo, W, focus, {"held": blind[2], "steered": blind[5], "later": blind[6]}, laws
    repo.close()


def _first_rung(repo, campaign: str, law: str) -> list[tuple[int, int]]:
    return [(int(r["n"]), int(r["c"])) for r in repo.conn.execute(
        "SELECT n, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND candidate_id=? GROUP BY n ORDER BY n",
        (campaign, law)).fetchall()]


def test_the_list_s_first_law_is_pushed_and_moving_or_taking_it_off_stops_its_run_at_once(folder):
    from graph_scale_dynamics.db.lane_yield import mode_yield_reason
    from graph_scale_dynamics.domain.model import MODE_YIELD_REASON
    from graph_scale_dynamics.operations import modes, push, push_ladder
    from graph_scale_dynamics.services.api import focus_route
    repo, W, focus, camps, laws = folder
    for name in ("held", "steered", "later"):
        focus_route.act(repo, {"do": "push", "law": laws[name], "campaign": camps[name]})
    push_ladder.tick(repo, force=True)
    state = focus.load(repo)
    pushed = str(state["campaigns"][push_ladder.PUSH])
    assert push.laws(state) == [laws["held"], laws["steered"], laws["later"]]
    assert state["depth_now"]["law"] == laws["held"] and _first_rung(repo, pushed, laws["held"]) == [(64, 4)]
    run = {"kind": "simulate", "campaign_id": pushed, "candidate_id": laws["held"], "n": 262144}
    assert mode_yield_reason(repo, run) is None

    focus_route.act(repo, {"do": "push_move", "law": laws["steered"][:12], "to": 0})
    assert modes.pushing(repo)["laws"] == [laws["steered"]]
    assert mode_yield_reason(repo, run) == MODE_YIELD_REASON, "moved down, its run under way stops, its seed saved"
    push_ladder.tick(repo, force=True)
    state = focus.load(repo)
    assert state["depth_now"]["law"] == laws["steered"] and _first_rung(repo, pushed, laws["steered"]) == [(64, 4)]
    assert _first_rung(repo, pushed, laws["held"]) == [(64, 4)], "the law moved down keeps its rung, to go on later"
    taken = [W.claim_simulation_for_owner(repo, f"executor-{i}-1") for i in range(5)]
    assert [j["candidate_id"] for j in taken[:4]] == [laws["steered"]] * 4 and taken[4] is None, (
        "the first law's seeds only; the law moved down waits")

    focus_route.act(repo, {"do": "unpush", "law": laws["steered"], "campaign": camps["steered"]})
    assert mode_yield_reason(repo, dict(run, candidate_id=laws["steered"], n=64)) == MODE_YIELD_REASON, (
        "taken off, even its small run stops: the next law has the fleet")
    push_ladder.tick(repo, force=True)
    assert focus.load(repo)["depth_now"]["law"] == laws["held"], "the next in the list goes on where it was"
    focus_route.act(repo, {"do": "push", "law": laws["steered"], "campaign": camps["steered"]})
    assert push.laws(focus.load(repo))[-1] == laws["steered"], "pushed again, it joins the end"

    repo.heartbeat("executor-0-1", {"job": taken[0]["job_id"], "pss_now": 3 * G, "pss": 4 * G, "elapsed": 60.0},
                   paced=True)
    found = focus_route.top(repo)
    assert any(r.get("memory_now") == 3 * G and r.get("memory_peak") == 4 * G for r in found["slot"]["running"])
    assert found["mode"]["mode"] == modes.PUSH and found["law"]["ladder"]["rungs"][0]["n"] == 64
    assert found["law"]["ladder"]["workers"] == 4 and found["slot"]["order"][0]["law"] == laws["held"]
    home = {laws[k]: camps[k] for k in laws}
    assert found["law"]["campaign"] == camps["held"] and found["now"]["campaign"] == camps["held"], (
        "894: the law is named and linked as it was pushed, not by its code in the push campaign")
    assert found["now"]["pushed_in"] == pushed and found["law"]["label"] == found["now"]["label"]
    assert all(r["of"] == home[r["law"]] for r in found["slot"]["running"])
    from graph_scale_dynamics.services.api.overview import _pushed_as
    rows = [{"candidate_id": laws["held"]}, {"candidate_id": "f" * 64}]
    _pushed_as(repo, repo.campaign(pushed)["spec"], rows)
    assert rows[0]["pushed_as"] == {"campaign": camps["held"], "label": found["law"]["label"]} and "pushed_as" not in rows[1]


def test_the_law_held_when_893_came_in_is_put_first_once_and_891_s_central_laws_join_the_end(folder):
    from graph_scale_dynamics.operations import push
    repo, _W, focus, camps, laws = folder
    state = focus._loaded(repo)
    state["contenders"][laws["held"]] = {"of": camps["held"], "label": "S178-C3-G1", "joined_utc": "2026-11-27T07:19:30Z"}
    state["depth_now"] = {"law": laws["held"], "label": "S178-C3-G1", "campaign": str(state["campaigns"][focus.DEPTH]),
                          "since": "2026-11-27T07:19:30Z"}
    state.pop(push.ADOPTED, None)
    push.add(state, laws["steered"], camps["steered"], "S178-C6-G1")
    state["central"] = [{"law": laws["later"], "of": camps["later"], "label": "S178-C7-G1", "zone": "S178-C15-G2302"}]
    focus.save(repo, state)
    state = focus.load(repo)
    focus.depth_next(repo, state, [])
    assert [(e["law"], e.get("by")) for e in state["pushed"]] == [
        (laws["held"], push.OWN_LINE), (laws["steered"], None), (laws["later"], "zone S178-C15-G2302")]
    assert "central" not in state and state[push.ADOPTED]
    state["pushed"] = state["pushed"][1:]
    state["depth_now"] = {"law": laws["held"], "label": "S178-C3-G1", "campaign": "13", "since": "x"}
    focus.depth_next(repo, state, [])
    assert push.laws(state)[0] == laws["steered"] and laws["held"] not in push.laws(state), "once only"


def test_a_pushed_law_that_reaches_its_limit_leaves_the_list_and_the_next_has_the_fleet(folder, monkeypatch):
    from graph_scale_dynamics.operations import push, push_ladder
    from graph_scale_dynamics.services.api import focus_route
    repo, _W, focus, camps, laws = folder
    for name in ("held", "steered"):
        focus_route.act(repo, {"do": "push", "law": laws[name], "campaign": camps[name]})
    monkeypatch.setattr(push_ladder, "reach", lambda repo: 1)
    push_ladder.tick(repo, force=True)
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=? AND candidate_id=?", (pushed, laws["held"]))
    for row in repo.conn.execute("SELECT job_id FROM jobs WHERE campaign_id=? AND candidate_id=?",
                                 (pushed, laws["held"])).fetchall():
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,"
                          "peak_rss_bytes,wall_seconds,peak_edge_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (f"a-{row['job_id']}", row["job_id"], 1, "w", "2026-11-27T10:00:00Z",
                           "2026-11-27T10:00:01Z", 0, 10 ** 6, 1.0, 256))
    push_ladder.tick(repo, force=True)
    state = focus.load(repo)
    assert push.laws(state) == [laws["steered"]] and state["pushed_done"][-1]["law"] == laws["held"]
    assert state["pushed_done"][-1]["at_n"] == 64 and state["depth_now"] is None
    push_ladder.tick(repo, force=True)
    assert focus.load(repo)["depth_now"]["law"] == laws["steered"]


def test_a_pushed_law_whose_every_seed_of_a_size_failed_leaves_the_list_and_says_why(folder):
    from graph_scale_dynamics.operations import push, push_ladder
    from graph_scale_dynamics.services.api import focus_route
    repo, _W, focus, camps, laws = folder
    for name in ("held", "steered"):
        focus_route.act(repo, {"do": "push", "law": laws[name], "campaign": camps[name]})
    push_ladder.tick(repo, force=True)
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    repo.conn.execute("UPDATE jobs SET status='failed' WHERE campaign_id=? AND candidate_id=?", (pushed, laws["held"]))
    push_ladder.tick(repo, force=True)
    state = focus.load(repo)
    assert push.laws(state) == [laws["steered"]] and state["pushed_done"][-1]["rule"] == "failed"
    assert state["events"][-1]["why"] == "every seed of N=64 failed"


def test_the_map_names_the_n_push_s_runs_as_the_law_was_pushed(folder):
    from graph_scale_dynamics.operations import push_ladder, zone_live
    from graph_scale_dynamics.services.api import focus_route
    repo, W, focus, camps, laws = folder
    focus_route.act(repo, {"do": "push", "law": laws["held"], "campaign": camps["held"]})
    push_ladder.tick(repo, force=True)
    assert W.claim_simulation_for_owner(repo, "executor-1-1") is not None
    state = focus.load(repo)
    pushed = str(state["campaigns"][push_ladder.PUSH])
    found = zone_live.reading(repo, state)
    run = next(r for r in found["running"] if r["campaign"] == pushed)
    label = next(e["label"] for e in state["pushed"] if e["law"] == laws["held"])
    assert run["role"] == zone_live.PUSHED and run["label"] == label and run["home"] == camps["held"]
    assert run["part"] == "the first pushed law, its ladder again from 64"
    assert next(r for r in found["laws"] if r["law"] == laws["held"])["home"] == camps["held"]
