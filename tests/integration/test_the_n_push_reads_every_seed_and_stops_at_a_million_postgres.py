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
GIB = 1024 ** 3
MILLION = 1048576


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
    laws = {"pushed": study_map._insert(repo, blind[2], _law(0.19)), "blind": study_map._insert(repo, blind[5], _law(0.31))}
    repo.set_flag(worker_count.MOST_FLAG, "32")
    repo.set_flag(worker_count.FLAG, "16")
    monkeypatch.setattr(push_ladder, "reach", lambda repo: 10 ** 15)
    monkeypatch.setattr(push_ladder, "asked", lambda repo, campaign_id, law, n: None)
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * GIB))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: GIB // 10)
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    focus.step(repo, force=True)
    yield repo, focus, {"pushed": blind[2], "blind": blind[5]}, laws
    repo.close()


def _jobs(repo, campaign: str, law: str, n: int, status: str | None = None) -> list[str]:
    return [str(r["job_id"]) for r in repo.conn.execute(
        "SELECT job_id FROM jobs WHERE campaign_id=? AND candidate_id=? AND n=?" + (" AND status=?" if status else "")
        + " ORDER BY seed", (campaign, law, n, *((status,) if status else ()))).fetchall()]


def _attempt(repo, job: str, *, code: int | None, peak: int, wall: float, number: int = 1) -> None:
    repo.conn.execute("INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,"
                      "peak_rss_bytes,wall_seconds,peak_edge_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (f"a{number}-{job}", job, number, "w", "2026-11-27T10:00:00Z", "2026-11-27T10:01:00Z", code,
                       peak, wall, 1000))


def _finish(repo, campaign: str, law: str, n: int, *, per_node: int) -> list[str]:
    return _complete(repo, _jobs(repo, campaign, law, n, "queued"), n, per_node=per_node)


def _complete(repo, jobs: list[str], n: int, *, per_node: int) -> list[str]:
    done = []
    for job in jobs:
        artifact = f"art-{job}"[:64].ljust(64, "0")
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                          "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", job, "{}", "2026-11-27T10:01:00Z"))
        repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (artifact, job))
        _attempt(repo, job, code=0, peak=per_node * n, wall=n / 1000.0)
        done.append(job)
    return done


def _probes(repo, campaign: str, jobs: list[str], status: str = "queued") -> None:
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    for job in jobs:
        row = repo.conn.execute("SELECT candidate_id, n, seed, result_artifact FROM jobs WHERE job_id=?", (job,)).fetchone()
        repo.conn.execute(
            "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,producer_job,"
            "status,error_class,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (campaign, row["result_artifact"], ANALYSIS_VERSION, row["candidate_id"], int(row["n"]), int(row["seed"]), job,
             status, "superseded" if status == "cancelled" else None, "2026-11-27T13:30:00Z", "2026-11-27T13:30:00Z"))


def _status(repo, campaign: str) -> dict[str, int]:
    return {str(r["status"]): int(r["c"]) for r in repo.conn.execute(
        "SELECT status, COUNT(*) AS c FROM analysis_queue WHERE campaign_id=? GROUP BY status", (campaign,)).fetchall()}


def test_a_start_keeps_every_probe_the_n_push_bought_and_still_cancels_a_blind_rung_s_excess(folder):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    from graph_scale_dynamics.operations import push_ladder
    from graph_scale_dynamics.scheduling.rungs import max_seed_attempts_for_rung
    from graph_scale_dynamics.services.api import focus_route
    repo, focus, camps, laws = folder
    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    push_ladder.tick(repo, force=True)
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    ceiling = max_seed_attempts_for_rung(repo.campaign(pushed)["spec"], 64)
    for seed in range(3, 16):
        repo.insert_job(job_id=f"more-{seed}", campaign_id=pushed, candidate_id=laws["pushed"], kind="simulate",
                        stage="extend", n=64, seed=seed, spec={}, priority=64)
    assert ceiling < 16, "896 bought 16 seeds a rung, past the clean-up's ceiling for the push campaign's rung"
    runs = _finish(repo, pushed, laws["pushed"], 64, per_node=10_000)
    assert len(runs) == 16
    _probes(repo, pushed, runs[:8])
    _probes(repo, pushed, runs[8:], status="cancelled")
    assert repo.ensure_analysis_queue(ANALYSIS_VERSION) == 8, "the start queues again the probes 896's start cancelled"
    assert repo.cancel_superseded_analysis_work(ANALYSIS_VERSION) == 0, "897: none of the push's own seeds is excess"
    assert _status(repo, pushed) == {"queued": 16}

    blind = camps["blind"]
    over = max_seed_attempts_for_rung(repo.campaign(blind)["spec"], 64) + 2
    for seed in range(over):
        repo.insert_job(job_id=f"blind-{seed}", campaign_id=blind, candidate_id=laws["blind"], kind="simulate",
                        stage="base", n=64, seed=100 + seed, spec={}, priority=64)
    _probes(repo, blind, _complete(repo, [f"blind-{seed}" for seed in range(over)], 64, per_node=10_000))
    assert repo.cancel_superseded_analysis_work(ANALYSIS_VERSION) == 2, (
        "a blind campaign's seeds past its ceiling are still a crash's leftovers")
    assert _status(repo, blind) == {"queued": over - 2, "cancelled": 2} and _status(repo, pushed) == {"queued": 16}


def _climb(repo, focus, pushed: str, law: str, *, per_node: int, until: int | None = None) -> dict[int, int]:
    from graph_scale_dynamics.operations import push_ladder
    seeds: dict[int, int] = {}
    for _ in range(40):
        push_ladder.tick(repo, force=True)
        if focus.load(repo)["depth_now"] is None:
            break
        found = push_ladder.rungs(repo, pushed, law)
        top = max(found)
        seeds[top] = found[top]["seeds"]
        if until is not None and top >= until:
            break
        _finish(repo, pushed, law, top, per_node=per_node)
    return seeds


def test_the_n_push_stops_a_law_at_a_million_unless_it_is_pushed_past_it(folder):
    from graph_scale_dynamics.operations import modes, push, push_ladder
    from graph_scale_dynamics.scheduling import worker_count
    from graph_scale_dynamics.services.api import focus_route
    repo, focus, camps, laws = folder
    repo.set_flag(worker_count.FLAG, "4")
    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    assert max(repo.campaign(pushed)["spec"]["ladder"]) == 4194304, "the push campaign's ladder still reaches 4,194,304"
    seen = _climb(repo, focus, pushed, laws["pushed"], per_node=1000, until=MILLION)
    assert max(seen) == MILLION
    state = focus.load(repo)
    ladder = push_ladder.forecast(repo, pushed, laws["pushed"], now=0.0, ceiling=push.ceiling_of(state, laws["pushed"]))
    assert [r["n"] for r in ladder["rungs"]][-1] == MILLION and ladder["ceiling"]["n"] == MILLION
    assert ladder["ceiling"]["next"] == 4194304 and ladder["ceiling"]["next_bytes"] > 0, (
        "the page says what pushing past would ask")
    assert ladder["end"]["n"] == MILLION and ladder["limit"] is None

    _finish(repo, pushed, laws["pushed"], MILLION, per_node=1000)
    push_ladder.tick(repo, force=True)
    state = focus.load(repo)
    done = state["pushed_done"][-1]
    assert done["law"] == laws["pushed"] and done["at_n"] == MILLION and done["rule"] == push_ladder.CEILING_RULE
    assert any("its ceiling, N=1,048,576" in (e.get("why") or "") for e in state["events"])
    assert push.laws(state) == [] and modes.here(repo)["mode"] != modes.PUSH
    assert 4194304 not in push_ladder.rungs(repo, pushed, laws["pushed"]), "no seed of 4,194,304 is bought"

    answer = focus_route.act(repo, {"do": "push_past", "law": laws["pushed"], "campaign": camps["pushed"]})
    assert answer["to"] == 4194304 and push.laws(focus.load(repo)) == [laws["pushed"]]
    push_ladder.tick(repo, force=True)
    found = push_ladder.rungs(repo, pushed, laws["pushed"])
    assert found[4194304]["seeds"] >= 3 and found[MILLION]["done"] == seen[MILLION], (
        "pushed past, it goes on from its last size: the sizes it ran stay")
    assert focus.load(repo)["pushed"][0]["to"] == 4194304


def test_the_forecast_prices_a_seed_as_the_admission_asks_and_says_how_many_run_now(folder, monkeypatch):
    from graph_scale_dynamics.operations import push, push_ladder
    from graph_scale_dynamics.scheduling import worker_count
    from graph_scale_dynamics.services.api import focus_route
    repo, focus, camps, laws = folder
    per_node = int(1.49 * GIB / 262144)
    asks = {MILLION: int(10.06 * GIB)}
    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    _climb(repo, focus, pushed, laws["pushed"], per_node=per_node, until=262144)
    _finish(repo, pushed, laws["pushed"], 262144, per_node=per_node)
    repo.set_flag(worker_count.FLAG, "11")
    monkeypatch.setattr(push_ladder, "reach", lambda repo: 54 * GIB)
    monkeypatch.setattr(push_ladder, "asked", lambda repo, campaign_id, law, n: asks.get(int(n)))
    bought = push_ladder.step(repo, focus.load(repo))
    assert bought["queued"] == MILLION and bought["asked_bytes"] == asks[MILLION] and bought["seeds"] == 3, (
        "3 seeds a rung (900), all at once: one asks 10.06 GiB to start and each running one is held at 1.1 times its "
        "peak, so up to seven would fit in 54 GiB")
    assert bought["at_once"] == 3 and bought["passes"] == 1
    for seed in range(3, 8):
        repo.insert_job(job_id=f"g73-{seed}", campaign_id=pushed, candidate_id=laws["pushed"], kind="simulate",
                        stage="extend", n=MILLION, seed=seed, spec={}, priority=1)
    jobs = _jobs(repo, pushed, laws["pushed"], MILLION)
    assert len(jobs) == 8, "178's G73 at 1,048,576: 8 seeds bought by 896"
    for i, job in enumerate(jobs[2:5]):
        repo.conn.execute("UPDATE jobs SET status='leased', lease_owner=?, lease_expires_utc='2099-01-01T00:00:00Z', "
                          "memory_reservation_bytes=? WHERE job_id=?", (f"executor-{i}-1", int(11.77 * GIB), job))
        repo.heartbeat(f"executor-{i}-1", {"job": job, "pss_now": int(9.2 * GIB), "pss": int(9.4 * GIB), "elapsed": 300},
                       paced=True)
        _attempt(repo, job, code=-9, peak=int(6.8 * GIB), wall=600.0)
    monkeypatch.setattr(push_ladder, "_headroom", lambda repo: int(6.29 * GIB))
    push_ladder.step(repo, state := focus.load(repo))
    left = {str(r["job_id"]): str(r["status"]) for r in repo.conn.execute(
        "SELECT job_id, status FROM jobs WHERE campaign_id=? AND n=?", (pushed, MILLION)).fetchall()}
    assert sorted(left.values()) == ["cancelled"] * 5 + ["leased"] * 3, (
        "a rung keeps 3 seeds: the 3 running stay, the 5 queued are let go")
    assert any(e.get("trimmed") == 5 for e in state["events"])
    focus.save(repo, state)
    state = focus.load(repo)
    seen = push_ladder.forecast(repo, pushed, laws["pushed"], now=0.0, ceiling=push.ceiling_of(state, laws["pushed"]))
    row = next(r for r in seen["rungs"] if r["n"] == MILLION)
    assert row["state"] == "running" and row["needs_bytes"] == asks[MILLION], (
        "priced as the admission asks, not by the 6.8 GiB of a run cut short")
    assert row["cut_bytes"] == int(6.8 * GIB) and row["live_bytes"] == int(9.4 * GIB) and row["at_once"] == 3
    assert row["hold_bytes"] == pytest.approx(1.1 * 9.4 * GIB, rel=1e-6), "a running pushed seed is held at 1.1 times its peak"
    assert seen["under_way"] == {"n": MILLION, "running": 3, "held_bytes": 3 * int(11.77 * GIB),
                                 "live_bytes": int(9.4 * GIB), "asked_bytes": asks[MILLION],
                                 "headroom_bytes": int(6.29 * GIB), "more": 0}
    assert row["seeds"] == 3 and row["passes"] == 1 and row["hours"] == pytest.approx(row["seconds"] / 3600, abs=1e-3), (
        "the three running, one pass: about 11 h where 8 seeds in passes read 33 h")
    assert seen["marks"]["fewer"] is None and seen["marks"]["two_passes"] is None
    done = next(r for r in seen["rungs"] if r["n"] == 262144)
    assert done["typical_bytes"] == per_node * 262144 and done["state"] == "done" and done["at_once"] == 3
    assert done["passes"] == 1 and done["starts_utc"] == "2026-11-27T10:00:00Z" and done["ends_utc"] == (
        "2026-11-27T10:01:00Z") and done["hours"] == pytest.approx(1 / 60, abs=1e-3), "what the rung took, and when"
    carried = push.for_the_bundle(repo, focus.load(repo))
    assert "top" not in carried and carried["law"]["ladder"]["under_way"]["running"] == 3, (
        "the bundle carries the N-push's forecast as the Top page shows it")
    assert carried["law"]["ceiling"] == MILLION and carried["pushed"][0]["ceiling"] == MILLION


class _Said:
    def __init__(self):
        self.lines = []

    def write(self, event, **fields):
        self.lines.append((event, fields))


def test_a_pushed_seed_is_asked_and_held_at_a_tenth_over_its_own_peak(folder, monkeypatch):
    from graph_scale_dynamics.operations import push_ladder
    from graph_scale_dynamics.scheduling import worker_count
    from graph_scale_dynamics.services.api import focus_route
    from graph_scale_dynamics.services.worker import main as W
    repo, focus, camps, laws = folder
    repo.set_flag(worker_count.FLAG, "4")
    per_node = int(1.49 * GIB / 262144)
    focus_route.act(repo, {"do": "push", "law": laws["pushed"], "campaign": camps["pushed"]})
    pushed = str(focus.load(repo)["campaigns"][push_ladder.PUSH])
    _climb(repo, focus, pushed, laws["pushed"], per_node=per_node, until=262144)
    _finish(repo, pushed, laws["pushed"], 262144, per_node=per_node)
    push_ladder.tick(repo, force=True)
    fresh, resumed = _jobs(repo, pushed, laws["pushed"], MILLION)[:2]
    _attempt(repo, resumed, code=-9, peak=int(9.8 * GIB), wall=600.0)
    job = lambda job_id: {"job_id": job_id, "campaign_id": pushed, "candidate_id": laws["pushed"], "n": MILLION}
    grown = 1.49 * GIB * 4 * 1.1
    assert push_ladder.claim_bytes(repo, job(fresh)) == pytest.approx(grown, rel=1e-3), (
        "a fresh seed is asked 1.1 times the typical peak of its law's own whole runs below, grown to its size: "
        "about 6.6 GiB at 1,048,576 in 178, where the admission asked 10.1")
    assert push_ladder.claim_bytes(repo, job(resumed)) == pytest.approx(1.1 * 9.8 * GIB, rel=1e-3), (
        "a seed stopped and resumed is asked 1.1 times what it reached before its stop")
    blind = {"job_id": "x", "campaign_id": camps["blind"], "candidate_id": laws["blind"], "n": MILLION}
    assert push_ladder.claim_bytes(repo, blind) is None, "every other law keeps the admission's own price"

    leased = repo.claim_job("executor-9-1", ("simulate",), campaigns=(pushed,), min_n=MILLION)
    said = _Said()
    held = W.restate_reservation(repo, said, leased, "executor-9-1", int(leased["lease_generation"]),
                                 {"pss_bytes": int(9.8 * GIB), "uss_bytes": 0, "rss_bytes": 0}, int(9.8 * GIB),
                                 int(14.7 * GIB), early=False)
    assert held == pytest.approx(1.1 * 9.8 * GIB, rel=1e-3) and said.lines[0][0] == "memory_reservation_settled", (
        "a running pushed seed is held at 1.1 times its peak, not 1.5: in 178 three seeds of 1,048,576 at 9.8 GiB "
        "were held at 14.7 each")
    priced = push_ladder.price(repo, pushed, laws["pushed"], push_ladder.rungs(repo, pushed, laws["pushed"]), MILLION,
                               54 * GIB)
    assert priced["hold_bytes"] == pytest.approx(1.1 * 9.8 * GIB, rel=1e-3), "the forecast holds it as the admission"
