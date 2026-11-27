from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(repo, campaign: str, law: str, n: int, seed: int, status: str) -> str:
    job_id = f"zone-{campaign}-{law[:12]}-{n}-{seed}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=n,
                    seed=seed, spec={"n": n})
    repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
    return job_id


def _attempt(repo, job_id: str, started: datetime, wall: float | None) -> None:
    finished = None if wall is None else _stamp(started + timedelta(seconds=wall))
    repo.conn.execute(
        "INSERT INTO attempts(attempt_id,job_id,number,worker,started_utc,finished_utc,exit_code,wall_seconds,"
        "build_number,runtime_fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (f"a-{job_id}", job_id, 1, "w1", _stamp(started), finished, None if wall is None else 0, wall, 884, "test"))


def test_the_map_page_says_where_each_law_of_the_zone_stands_who_runs_now_and_how_long_is_left(
        isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map, study_seed, zone_live
    from graph_scale_dynamics.scheduling import work_groups
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
        kinds = {str(c["campaign_id"]): c["spec"]["study_design"]["kind"] for c in repo.all_campaigns()}
        blind = sorted((cid for cid, kind in kinds.items() if kind == "blind"), key=int)
        first = study_map._insert(repo, blind[4], H12)
        scored = [{"candidate_id": first, "campaign": blind[4], "score": 1, "graph": 1, "label": "S177-C5-G1"}]
        monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
        focus.step(repo, force=True)
        focus.lean(repo, 0.9)
        state = focus.load(repo)
        made = state["campaigns"]
        zone = str(made[focus.NEIGHBOURS])
        rings = [law for law, p in state["current"]["points"].items() if p["how"] == "neighbour"]
        running, queued, between, held, untouched = rings[:5]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for law in (running, queued, between, held):
            for seed in range(3):
                _attempt(repo, _job(repo, zone, law, 64, seed, "done"), now - timedelta(minutes=20), 2.0)
        for n in (256, 1024):
            for seed in range(3):
                _attempt(repo, _job(repo, zone, running, n, seed, "done"), now - timedelta(minutes=10), 6.0)
        _attempt(repo, _job(repo, zone, running, 4096, 0, "done"), now - timedelta(minutes=4), 30.0)
        _attempt(repo, _job(repo, zone, running, 4096, 1, "leased"), now - timedelta(seconds=40), None)
        _job(repo, zone, running, 4096, 2, "queued")
        for seed in range(3):
            _job(repo, zone, queued, 256, seed, "queued")
        repo.conn.execute(
            "INSERT INTO engine_decisions_latest(campaign_id,candidate_id,decision_id,at_n,next_n,action,rule,reason,"
            "jobs_created,jobs_seen,facts_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (zone, held, "d1", 64, 256, "hold", "budget_hold", "held for the test", 0, "[]", "{}",
             _stamp(now - timedelta(minutes=3))))
        seeded = study_seed.seeded_campaign(repo, "177")
        dex_law = study_map._insert(repo, seeded, dict(H12, dynamics=dict(H12["dynamics"], beta=0.25)))
        _attempt(repo, _job(repo, seeded, dex_law, 1024, 0, "leased"), now - timedelta(seconds=5), None)
        drawn = study_map._insert(repo, blind[0], dict(H12, dynamics=dict(H12["dynamics"], beta=0.31)))
        _attempt(repo, _job(repo, blind[0], drawn, 64, 0, "leased"), now - timedelta(seconds=2), None)

        state = focus.load(repo)
        state["typical"] = zone_live.typical(repo, list(made.values()), now=now)
        assert state["typical"]["zone"]["64"] == 2.0 and state["typical"]["zone"]["4096"] == 30.0
        found = zone_live.reading(repo, state, now=now)

        assert found["workers"] == {"the N-push": 0, "zone": 1, "zone seeds": 0, "depth": 0, "Dex laws": 1, "blind": 1, "other": 0}
        roles = [(r["role"], r["part"], r["n"]) for r in found["running"]]
        assert roles[0][0] == "zone" and roles[0][1].startswith("ring ") and roles[0][2] == 4096, roles
        assert ("Dex laws", "a Dex law, read again here", 1024) in roles and ("blind", "drawn blind", 64) in roles
        assert found["running"][0]["seconds"] == 40.0 and found["running"][0]["typical"] == 30.0
        assert found["running"][0]["label"].startswith(f"S177-C{zone}-G")
        assert found["order"]["name"] == "the zone of the law in focus" and found["order"]["ordered"]

        points = {p["law"]: p for p in found["zone"]["points"]}
        assert len(points) == len(state["current"]["points"])
        where = {law: points[law]["where"] for law in (running, queued, between, held, untouched)}
        assert where[running]["stage"] == zone_live.RUNNING and where[running]["n"] == 4096
        assert (where[running]["done"], where[running]["running"], where[running]["queued"]) == (1, 1, 1)
        assert where[running]["seconds"] == 40.0, "how long it has run: its seed's attempt began 40 s ago"
        assert points[running]["reached"] == 1024
        assert where[queued]["stage"] == zone_live.QUEUED and where[queued]["n"] == 256
        assert where[between]["stage"] == zone_live.DECIDER and where[between]["n"] == 64
        assert where[held]["stage"] == zone_live.HELD and where[held]["rule"] == "budget_hold"
        assert where[held]["seconds"] == 180.0
        assert where[untouched]["stage"] == zone_live.NOT_STARTED
        ring = found["zone"]["rings"][f"{state['current']['points'][running]['radius']:g}"]
        assert ring["running"] >= 1 and sum(ring[s] for s in zone_live.STAGES) + ring["read"] == ring["laws"]
        assert found["zone"]["left_seconds"] > 0 and found["zone"]["eta_seconds"] == found["zone"]["left_seconds"]
        assert found["zone"]["left_unknown"], "16,384 is not timed yet in this folder"
        assert "67% of ring 0.1" in found["zone"]["judged"]
        assert found["zone"]["pace"]["read"] == 0 and found["zone"]["pace"]["of"] == len(points)

        rows = {str(r["campaign_id"]): r for r in repo.worker_allocation()}
        assert rows[seeded]["design_kind"] == "seed" and rows[seeded]["work_group"] == "N"
        assert work_groups.group_of(rows[seeded]) == work_groups.BLIND, "the Dex laws count with the laws coming in"
        assert work_groups.group_of(rows[zone]) == work_groups.NEIGHBOURS

        earlier = study_map._insert(repo, zone, dict(H12, dynamics=dict(H12["dynamics"], beta=0.41)))
        _job(repo, zone, earlier, 64, 0, "queued")
        focus.step(repo, force=True)
        state = focus.load(repo)
        priority = {str(r["candidate_id"]): int(r["priority"]) for r in repo.conn.execute(
            "SELECT candidate_id, priority FROM jobs WHERE campaign_id=? AND status='queued'", (zone,)).fetchall()}
        assert priority[earlier] >= focus.BEHIND > priority[queued], "an earlier law's neighbours wait behind its own"
        assert state["zone_first"][focus.NEIGHBOURS]["waiting"] == 1
        assert zone_live.reading(repo, state, now=now)["zone_first"][focus.NEIGHBOURS]["waiting"] == 1
        assert focus.typical_of(repo, state) is state["typical"], "read again only every five minutes"
        state.pop("typical")
        focus.save(repo, state)
        focus.step(repo, force=True)
        state = focus.load(repo)
        assert state["typical"]["zone"]["1024"] == 6.0, "the focus's step keeps the typical times it reads"
        assert set(state["current"].get("needs_at") or {}) <= {n["what"] for n in state["current"]["needs"] if n["done"]}
