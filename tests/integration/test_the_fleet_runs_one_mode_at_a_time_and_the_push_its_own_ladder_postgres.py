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


def _job(repo, campaign: str, law: str, n: int, seed: int = 0) -> str:
    job_id = f"mode-{campaign}-{law[:10]}-{n}-{seed}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=n,
                    seed=seed, spec={}, priority=100_000_000 + n)
    return job_id


def _finish(repo, campaign: str, law: str, n: int, *, per_node: int = 20_000) -> int:
    rows = repo.conn.execute("SELECT job_id FROM jobs WHERE campaign_id=? AND candidate_id=? AND n=? AND "
                             "status='queued'", (campaign, law, n)).fetchall()
    for row in rows:
        repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (row["job_id"],))
        repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,"
                          "peak_rss_bytes,wall_seconds,peak_edge_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (f"a-{row['job_id']}", row["job_id"], 1, "w", "2026-11-27T10:00:00Z", "2026-11-27T10:01:00Z",
                           0, per_node * n, n / 1000.0, 4 * n))
    return len(rows)


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
    laws = {"blind": study_map._insert(repo, blind[0], _law(0.41)), "focus": study_map._insert(repo, blind[2], _law(0.19)),
            "pushed": study_map._insert(repo, blind[5], _law(0.31))}
    repo.set_flag(worker_count.MOST_FLAG, "32")
    repo.set_flag(worker_count.FLAG, "16")
    monkeypatch.setattr(push_ladder, "reach", lambda repo: 10 * G)
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * G))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: G // 10)
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    yield repo, W, focus, {"blind": blind[0], "focus": blind[2], "pushed": blind[5]}, laws
    repo.close()


def test_the_fleet_is_in_one_mode_at_a_time_and_takes_only_its_runs(folder, monkeypatch):
    from graph_scale_dynamics.db.lane_yield import mode_yield_reason
    from graph_scale_dynamics.domain.model import MODE_YIELD_REASON
    from graph_scale_dynamics.operations import modes, push_ladder
    from graph_scale_dynamics.services.analyzer import main as A
    from graph_scale_dynamics.services.api import focus_route
    repo, W, focus, camps, laws = folder
    focus.step(repo, force=True)
    state = focus.load(repo)
    zone = str(state["campaigns"][focus.NEIGHBOURS])
    mode = modes.here(repo)
    assert mode["mode"] == modes.BLIND and camps["blind"] in mode["campaigns"] and zone not in mode["campaigns"]
    assert str(state["campaigns"][focus.DEPTH]) not in mode["campaigns"]
    from graph_scale_dynamics.operations import study_map
    neighbour = study_map._insert(repo, zone, _law(0.2))
    blind_job = _job(repo, camps["blind"], laws["blind"], 64)
    zone_job = _job(repo, zone, neighbour, 1024)
    assert W.claim_simulation_for_owner(repo, "executor-0-1")["job_id"] == blind_job, "blind: the blind ladder alone"
    assert W.claim_simulation_for_owner(repo, "executor-1-1") is None, "a zone's run waits for the zone search"
    assert mode_yield_reason(repo, {"campaign_id": zone, "candidate_id": neighbour, "n": 1024}) == MODE_YIELD_REASON

    scored = [{"candidate_id": laws["focus"], "campaign": camps["focus"], "score": 1, "graph": 1, "label": "S178-C3-G1"}]
    monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
    focus.step(repo, force=True)
    mode = modes.here(repo)
    assert mode["mode"] == modes.ZONE and "is in focus" in mode["why"] and zone in mode["campaigns"]
    assert camps["blind"] not in mode["campaigns"]
    assert mode_yield_reason(repo, {"campaign_id": camps["blind"], "candidate_id": laws["blind"], "n": 64}) == (
        MODE_YIELD_REASON), "the blind run under way stops, its seed saved: the zone search has the fleet"
    assert W.claim_simulation_for_owner(repo, "executor-2-1")["job_id"] == zone_job
    _job(repo, camps["blind"], laws["blind"], 256)
    assert W.claim_simulation_for_owner(repo, "executor-3-1") is None, "never a blind run beside the zone's"

    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    mode = modes.here(repo)
    state = focus.load(repo)
    pushed = str(state["campaigns"][push_ladder.PUSH])
    assert mode["mode"] == modes.PUSH and mode["campaigns"] == [pushed] and mode["laws"] == [laws["pushed"]]
    assert mode_yield_reason(repo, {"campaign_id": zone, "candidate_id": neighbour, "n": 1024}) == MODE_YIELD_REASON
    push_ladder.tick(repo, force=True)
    queued = repo.conn.execute("SELECT n, COUNT(*) AS c FROM jobs WHERE campaign_id=? AND status='queued' GROUP BY n",
                               (pushed,)).fetchall()
    assert [(int(r["n"]), int(r["c"])) for r in queued] == [(64, 16)], "the ladder from 64, a seed for every worker"
    taken = [W.claim_simulation_for_owner(repo, f"executor-{i}-2") for i in range(17)]
    assert all(job and job["campaign_id"] == pushed for job in taken[:16]) and taken[16] is None, (
        "every worker on the pushed law, all sixteen seeds at once, nothing else")
    probe = _job(repo, zone, neighbour, 4096, seed=9)
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact='art-zone' WHERE job_id=?", (probe,))
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", ("art-zone", 1, "application/octet-stream", probe, "{}",
                                              "2026-11-27T10:00:00Z"))
    repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                      "producer_job,priority,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (zone, "art-zone", A.ANALYSIS_VERSION, neighbour, 4096, 9, probe, 100, "queued",
                       "2026-11-27T10:00:00Z", "2026-11-27T10:00:00Z"))
    assert A.claim_analysis_for_owner(repo, "analyzer-1") is None, "probes too: the pushed law's alone"

    focus_route.act(repo, {"do": "unpush", "law": laws["pushed"], "campaign": camps["pushed"]})
    assert modes.here(repo)["mode"] == modes.ZONE, "the list empty, the zone search has the fleet again"
    assert A.claim_analysis_for_owner(repo, "analyzer-2")["result_artifact"] == "art-zone"


def test_a_pushed_law_climbs_its_own_ladder_on_every_worker_until_not_one_seed_fits(folder):
    from graph_scale_dynamics.operations import modes, push, push_ladder
    from graph_scale_dynamics.services.api import focus_route
    repo, _W, focus, camps, laws = folder
    focus.step(repo, force=True)
    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    seeds: dict[int, int] = {}
    seen = None
    for _ in range(40):
        push_ladder.tick(repo, force=True)
        state = focus.load(repo)
        if state["depth_now"] is None:
            break
        found = push_ladder.rungs(repo, pushed, laws["pushed"])
        top = max(found)
        seeds[top] = found[top]["seeds"]
        if top == 16384:
            seen = push_ladder.forecast(repo, pushed, laws["pushed"], now=0.0)
        _finish(repo, pushed, laws["pushed"], top)
    assert seeds == {64: 16, 256: 16, 1024: 16, 4096: 16, 16384: 16, 65536: 6, 262144: 3}, (
        "every worker while memory holds them; then as many as fit, never fewer than three")
    done = focus.load(repo)["pushed_done"][-1]
    assert done["law"] == laws["pushed"] and done["at_n"] == 262144 and done["rule"] == "memory"
    assert push.laws(focus.load(repo)) == [] and modes.here(repo)["mode"] != modes.PUSH, (
        "the law reached its limit: it leaves the list and the fleet goes back")
    assert any(e.get("push_ended") and "not one seed of N=1,048,576 fits" in e["why"]
               for e in focus.load(repo)["events"])

    marks, rows = seen["marks"], {r["n"]: r for r in seen["rungs"]}
    assert rows[64]["state"] == "done" and rows[16384]["state"] == "running" and rows[65536]["state"] == "ahead"
    assert marks["fewer"]["n"] == 65536 and marks["fewer"]["at_once"] in (5, 6), (
        "the first break: fewer seeds than workers, priced before 16,384 is measured, so one more step of margin")
    assert marks["two_passes"]["n"] == 262144 and marks["one_worker"]["n"] == 262144
    assert rows[262144]["seeds"] == 3 and rows[262144]["passes"] == 3 and rows[262144]["at_once"] == 1
    assert seen["limit"]["n"] == 1048576 and seen["end"]["n"] == 262144 and seen["end"]["hours"] > 0
    assert rows[65536]["hours"] == pytest.approx(rows[65536]["seconds"] / 3600, abs=1e-3), "six at once: one pass"
    assert rows[262144]["hours"] == pytest.approx(3 * rows[262144]["seconds"] / 3600, abs=1e-3), "three passes"
    spec = repo.campaign(pushed)["spec"]
    assert push_ladder.is_push(spec) and spec["ladder"][0] == 64
