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
ANALYSIS = "test-version"


def _law(beta: float) -> dict:
    return dict(H12, dynamics=dict(H12["dynamics"], beta=beta))


def _queued(repo, campaign: str, law: str) -> list[tuple[int, str]]:
    return [(int(r["n"]), str(r["job_id"])) for r in repo.conn.execute(
        "SELECT n, job_id FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' AND status='queued' "
        "ORDER BY n, job_id", (campaign, law)).fetchall()]


def _job(repo, campaign: str, law: str, n: int, seed: int = 0) -> str:
    job_id = f"slot-{campaign}-{law[:10]}-{n}-{seed}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="extension", n=n,
                    seed=seed, spec={}, priority=200_000_000 + n)
    return job_id


@pytest.fixture
def folder(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus, study_map
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.services.worker import main as W
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    SD.start(repo, SD.design_for(ROOT, "178"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
    blind = sorted((str(c["campaign_id"]) for c in repo.all_campaigns()
                    if c["spec"]["study_design"]["kind"] == "blind"), key=int)
    laws = {"held": study_map._insert(repo, blind[2], _law(0.19)), "steered": study_map._insert(repo, blind[5], _law(0.31)),
            "later": study_map._insert(repo, blind[6], _law(0.37))}
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * G))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: G // 10)
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    yield repo, W, focus, {"held": blind[2], "steered": blind[5], "later": blind[6]}, laws
    repo.close()


def test_a_law_pushed_first_takes_the_depth_worker_at_once_and_the_law_it_held_waits_with_its_runs(folder,
                                                                                                    monkeypatch):
    from graph_scale_dynamics.operations import push, study_map
    from graph_scale_dynamics.services.api import focus_route
    repo, W, focus, camps, laws = folder
    focus_route.act(repo, {"do": "push", "law": laws["held"], "campaign": camps["held"]})
    focus.step(repo, force=True)
    state = focus.load(repo)
    depth = str(state["campaigns"][focus.DEPTH])
    assert state["depth_now"]["law"] == laws["held"]
    for n in (64, 256):
        _job(repo, depth, laws["held"], n)
    held_jobs = _queued(repo, depth, laws["held"])

    focus_route.act(repo, {"do": "push", "law": laws["steered"], "campaign": camps["steered"]})
    focus_route.act(repo, {"do": "push", "law": laws["later"], "campaign": camps["later"]})
    focus_route.act(repo, {"do": "push_move", "law": laws["steered"][:12], "to": 0})
    focus.step(repo, force=True)
    state = focus.load(repo)
    assert [e["law"] for e in state["pushed"]] == [laws["steered"], laws["held"], laws["later"]]
    assert state["depth_now"]["law"] == laws["steered"] and state["depth_waiting"] == [laws["held"]], (
        "moved first, it takes the depth worker at the next step; the law it held waits")
    assert str(state["campaigns"][focus.DEPTH]) == depth and repo.campaign(depth)["status"] == "active"
    assert _queued(repo, depth, laws["held"]) == held_jobs, "the waiting law keeps every run it had queued"
    assert push.order_here(repo) == {"campaign": depth, "host": True, "laws": [laws["steered"], laws["held"]]}

    for n in (64, 1024):
        _job(repo, depth, laws["steered"], n)
    steered = _queued(repo, depth, laws["steered"])
    claimed = W.claim_depth_for_owner(repo, "executor-32-1")
    assert (int(claimed["n"]), claimed["job_id"]) == steered[0] and claimed["candidate_id"] == laws["steered"]
    assert W.claim_depth_for_owner(repo, "executor-32-1")["candidate_id"] == laws["steered"]
    repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=? AND candidate_id=? AND status='queued'",
                      (depth, laws["steered"]))
    big = _job(repo, depth, laws["held"], 65536)
    filled = W.claim_depth_for_owner(repo, "executor-32-1")
    assert filled["candidate_id"] == laws["held"] and int(filled["n"]) < 16384, (
        "while the first law waits for its next size, a waiting law's small run fills the slot")
    repo.conn.execute("UPDATE jobs SET status='done' WHERE campaign_id=? AND candidate_id=? AND status='queued' "
                      "AND job_id<>?", (depth, laws["held"], big))
    assert W.claim_depth_for_owner(repo, "executor-32-1") is None, (
        "a waiting law's large run does not go before the first law's next size")
    repo.conn.execute("UPDATE jobs SET status='done' WHERE kind='simulate' AND status='queued' AND campaign_id<>?",
                      (depth,))
    assert W.claim_simulation_for_owner(repo, "executor-0-1") is None, (
        "while the list holds the host the fleet takes no other run, and none of a waiting law past 16,384")

    decided = study_map.decided
    monkeypatch.setattr(study_map, "decided", lambda repo, campaign_id, law: law == laws["steered"]
                        or decided(repo, campaign_id, law))
    focus.step(repo, force=True)
    state = focus.load(repo)
    assert [e["law"] for e in state["pushed"]] == [laws["held"], laws["later"]]
    assert state["pushed_done"][-1]["law"] == laws["steered"], "a pushed law that reaches its limit leaves the list"
    assert state["depth_now"]["law"] == laws["held"] and state["depth_waiting"] == [], (
        "the waiting law goes on where it was, in the same depth campaign")
    assert _queued(repo, depth, laws["held"]) == [(65536, big)]
    repo.heartbeat("executor-32-1", {"job": claimed["job_id"], "pss_now": 3 * G, "pss": 4 * G, "elapsed": 60.0}, paced=True)
    found = focus_route.top(repo)
    assert any(r["n"] == int(claimed["n"]) and r.get("memory_now") == 3 * G and r.get("memory_peak") == 4 * G
               for r in found["slot"]["running"]), "the run under way says the memory it holds"
    assert found["slot"]["campaign"] == depth and [o["law"] for o in found["slot"]["order"]] == [laws["held"]]
    assert found["done"][-1]["law"] == laws["steered"]


def test_a_zone_s_central_law_joins_the_end_of_the_push_list(folder):
    from graph_scale_dynamics.operations import push
    repo, _W, focus, camps, laws = folder
    state = focus._loaded(repo)
    push.add(state, laws["held"], camps["held"], "S178-C3-G1")
    state["central"] = [{"law": laws["later"], "of": camps["later"], "label": "S178-C7-G1", "zone": "S178-C15-G2302"}]
    focus.save(repo, state)
    focus.step(repo, force=True)
    state = focus.load(repo)
    assert [(e["law"], e.get("by")) for e in state["pushed"]] == [(laws["held"], None),
                                                                  (laws["later"], "zone S178-C15-G2302")]
    assert "central" not in state, "891's list of central laws is folded into the push list"


def _probe(repo, campaign: str, law: str, n: int, job_id: str) -> str:
    artifact = f"artifact-{job_id}"
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (artifact, job_id))
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/octet-stream", job_id, "{}",
                                              "2026-11-27T08:00:00Z"))
    repo.conn.execute(
        "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,producer_job,"
        "priority,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, artifact, ANALYSIS, law, n, 0, job_id, 100, "queued", "2026-11-27T08:00:00Z",
         "2026-11-27T08:00:00Z"))
    return artifact


def test_while_the_push_list_holds_a_law_the_whole_host_is_its_and_taking_it_off_stops_its_run_at_once(folder,
                                                                                                      monkeypatch):
    from graph_scale_dynamics.db.lane_yield import depth_yield_reason
    from graph_scale_dynamics.domain.model import DEPTH_YIELD_REASON
    from graph_scale_dynamics.operations import depth_reach, push
    from graph_scale_dynamics.services.analyzer import main as A
    from graph_scale_dynamics.services.api import focus_route
    repo, W, focus, camps, laws = folder
    monkeypatch.setattr(A, "ANALYSIS_VERSION", ANALYSIS)
    scored = [{"candidate_id": laws["held"], "campaign": camps["held"], "score": 1, "graph": 1, "label": "S178-C3-G1"}]
    monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
    focus.step(repo, force=True)
    state = focus.load(repo)
    depth = str(state["campaigns"][focus.DEPTH])
    assert state["depth_now"]["law"] == laws["held"] and push.laws(state) == [], (
        "the depth worker's own pick stays off the list: it would hold the host from the zone")
    assert push.order_here(repo) == {"campaign": depth, "host": False, "laws": [laws["held"]]}
    assert push.holds_host(repo) is None and depth_reach.room_for(repo, depth).get("share") == 0.5

    focus_route.act(repo, {"do": "push", "law": laws["steered"], "campaign": camps["steered"]})
    focus_route.act(repo, {"do": "push", "law": laws["later"], "campaign": camps["later"]})
    assert push.holds_host(repo)["laws"] == [laws["steered"]], "the list holds the host the moment a law is on it"
    own = {"kind": "simulate", "campaign_id": depth, "candidate_id": laws["held"], "n": 262144}
    other = {"kind": "simulate", "campaign_id": camps["later"], "candidate_id": laws["later"], "n": 4096}
    assert depth_yield_reason(repo, own) == DEPTH_YIELD_REASON and depth_yield_reason(repo, other) == DEPTH_YIELD_REASON, (
        "every other run is stopped, its seed saved: the depth worker's own pick and the fleet's work alike")
    focus.step(repo, force=True)
    state = focus.load(repo)
    assert state["depth_now"]["law"] == laws["steered"]
    assert depth_reach.room_for(repo, depth)["host"] is True, "its reach is all the memory the host admits"

    for n in (64, 256):
        for seed in range(3):
            _job(repo, depth, laws["steered"], n, seed)
    blind = _job(repo, camps["later"], laws["later"], 64)
    taken = [W.claim_simulation_for_owner(repo, f"executor-{i}-1") for i in range(8)]
    assert [(int(j["n"]), j["candidate_id"]) for j in taken if j] == [(64, laws["steered"])] * 3 + [(256, laws["steered"])] * 3
    assert taken[6] is None and taken[7] is None, "the fleet's slots take only the pushed law's runs, all seeds at once"
    assert repo.conn.execute("SELECT status FROM jobs WHERE job_id=?", (blind,)).fetchone()["status"] == "queued"
    mine = _probe(repo, depth, laws["steered"], 64, taken[0]["job_id"])
    _probe(repo, camps["later"], laws["later"], 64, blind)
    assert A.claim_analysis_for_owner(repo, "analyzer-1")["result_artifact"] == mine
    assert A.claim_analysis_for_owner(repo, "analyzer-2") is None, "probes too: the pushed law's alone"

    focus_route.act(repo, {"do": "unpush", "law": laws["steered"], "campaign": camps["steered"]})
    assert depth_yield_reason(repo, dict(own, candidate_id=laws["steered"], n=65536)) == DEPTH_YIELD_REASON, (
        "taken off the top, its run under way is stopped at once")
    assert push.holds_host(repo)["laws"] == [laws["later"]]
    focus.step(repo, force=True)
    state = focus.load(repo)
    assert state["depth_now"]["law"] == laws["later"]
    assert state["depth_done"][laws["steered"]]["left"] == "taken off the push list"

    focus_route.act(repo, {"do": "push", "law": laws["steered"], "campaign": camps["steered"]})
    state = focus.load(repo)
    assert push.laws(state) == [laws["later"], laws["steered"]] and laws["steered"] not in state["depth_done"], (
        "pushed again, it joins the end and may run again where it was")
    focus_route.act(repo, {"do": "push_move", "law": laws["steered"], "to": 0})
    assert depth_yield_reason(repo, dict(other, campaign_id=depth, n=65536)) == DEPTH_YIELD_REASON
    assert depth_yield_reason(repo, dict(other, campaign_id=depth, n=4096)) is None, (
        "moved down, its small run may finish; its large one gives the host to the new first")

    for law, camp in (("later", "later"), ("steered", "steered")):
        focus_route.act(repo, {"do": "unpush", "law": laws[law], "campaign": camps[camp]})
    assert push.holds_host(repo) is None, "the list empty, the host goes back to the fleet"
    focus.step(repo, force=True)
    assert focus.load(repo)["depth_now"]["law"] == laws["held"], "the depth worker's own pick goes on where it was"


def test_the_law_the_depth_worker_held_when_892_came_in_is_put_first_on_the_list_once(folder):
    from graph_scale_dynamics.operations import push
    repo, _W, focus, camps, laws = folder
    state = focus._loaded(repo)
    state["contenders"][laws["held"]] = {"of": camps["held"], "label": "S178-C3-G1", "joined_utc": "2026-11-27T07:19:30Z"}
    state["depth_now"] = {"law": laws["held"], "label": "S178-C3-G1", "campaign": str(state["campaigns"][focus.DEPTH]),
                          "since": "2026-11-27T07:19:30Z"}
    state.pop(push.ADOPTED, None)
    push.add(state, laws["steered"], camps["steered"], "S178-C6-G1")
    focus.save(repo, state)
    state = focus.load(repo)
    focus.depth_next(repo, state, [])
    assert [(e["law"], e.get("by")) for e in state["pushed"]] == [(laws["held"], push.OWN_LINE),
                                                                  (laws["steered"], None)]
    assert state["depth_now"]["law"] == laws["held"] and state[push.ADOPTED], (
        "the law it held stays first, where the operator can take it off")
    state["pushed"] = [e for e in state["pushed"] if e["law"] != laws["held"]]
    focus.depth_next(repo, state, [])
    assert state["depth_now"]["law"] == laws["steered"] and push.laws(state) == [laws["steered"]], (
        "once only: taken off, it is not put back")
