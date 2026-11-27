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


def _job(repo, campaign: str, law: str, n: int, *, priority: int, status: str = "queued") -> str:
    job_id = f"order-{campaign}-{law[:10]}-{n}"
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage="base", n=n,
                    seed=0, spec={}, priority=priority)
    repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
    return job_id


def _probe(repo, campaign: str, law: str, n: int, job_id: str, priority: int) -> str:
    artifact = f"artifact-{job_id}"
    repo.conn.execute("UPDATE jobs SET status='done', result_artifact=? WHERE job_id=?", (artifact, job_id))
    repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                      "VALUES(?,?,?,?,?,?)", (artifact, 1, "application/octet-stream", job_id, "{}",
                                              "2026-11-26T18:00:00Z"))
    repo.conn.execute(
        "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,producer_job,"
        "priority,status,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, artifact, "test-version", law, n, 0, job_id, priority, "queued", "2026-11-26T18:00:00Z",
         "2026-11-26T18:00:00Z"))
    return artifact


@pytest.fixture
def folder(isolated_postgres_schema, monkeypatch):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.operations import focus
    from graph_scale_dynamics.operations import study_design as SD
    from graph_scale_dynamics.operations import study_map, study_seed
    from graph_scale_dynamics.scheduling import memory as M
    from graph_scale_dynamics.services.worker import main as W
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    SD.start(repo, SD.design_for(ROOT, "177"), json.loads(json.dumps(SURVEY)), tree=ROOT, log=lambda *_a: None)
    kinds = {str(c["campaign_id"]): c["spec"]["study_design"]["kind"] for c in repo.all_campaigns()}
    blind = sorted((cid for cid, kind in kinds.items() if kind == "blind"), key=int)
    first = study_map._insert(repo, blind[4], H12)
    scored = [{"candidate_id": first, "campaign": blind[4], "score": 1, "graph": 1, "label": "S177-C5-G1"}]
    monkeypatch.setattr(focus, "best", lambda repo, study, state=None: [dict(e) for e in scored])
    focus.step(repo, force=True)
    state = focus.load(repo)
    zone = str(state["campaigns"][focus.NEIGHBOURS])
    seeded = study_seed.seeded_campaign(repo, "177")
    monkeypatch.setattr(M, "memory_pressure_snapshot", lambda: {"available": False})
    monkeypatch.setattr(M, "system_memory", lambda: M.MemorySnapshot(total=98746621952, available=60 * G))
    monkeypatch.setattr(W, "predicted_claim_peak_bytes", lambda conn, **kw: G // 10)
    monkeypatch.setattr(W, "hard_process_limit_bytes", lambda spec, **kw: None)
    laws = {"point": next(iter(state["current"]["points"])),
            "earlier": study_map._insert(repo, zone, _law(0.41)),
            "dex": study_map._insert(repo, seeded, _law(0.25)),
            "blind": study_map._insert(repo, blind[0], _law(0.31))}
    yield repo, W, focus, {"zone": zone, "seeded": seeded, "blind": blind[0]}, laws
    repo.close()


def test_runs_go_to_the_zone_then_the_dex_laws_then_the_blind_draw_and_earlier_laws_last(folder):
    from graph_scale_dynamics.scheduling import work_groups
    repo, W, focus, camps, laws = folder
    base = 100_000_000
    jobs = {"blind": _job(repo, camps["blind"], laws["blind"], 64, priority=base + 64),
            "dex": _job(repo, camps["seeded"], laws["dex"], 64, priority=base + 64),
            "earlier": _job(repo, camps["zone"], laws["earlier"], 64, priority=base + 64),
            "point": _job(repo, camps["zone"], laws["point"], 1024, priority=base + 1024)}
    focus.step(repo, force=True)
    priority = {r["job_id"]: int(r["priority"]) for r in repo.conn.execute("SELECT job_id, priority FROM jobs")}
    assert priority[jobs["earlier"]] >= work_groups.BEHIND > priority[jobs["point"]]
    now = work_groups.now_on([dict(r) for r in repo.worker_allocation()])
    assert now["name"] == "the zone of the law in focus" and now["queued"]["earlier laws' leftovers"] == 1
    taken = [W.claim_simulation_for_owner(repo, f"executor-{i}")["job_id"] for i in range(4)]
    assert taken == [jobs["point"], jobs["dex"], jobs["blind"], jobs["earlier"]], (
        "the zone's own run first though it is the largest; the base half takes no earlier law's run before it")
    assert W.claim_simulation_for_owner(repo, "executor-9") is None


def test_probes_are_read_in_the_same_order_and_their_slots_follow_the_first_work(folder):
    from graph_scale_dynamics.scheduling import work_groups
    repo, W, focus, camps, laws = folder
    base = 100_000_000
    point = _job(repo, camps["zone"], laws["point"], 16384, priority=2 * base + 16384)
    probes = {"blind": _probe(repo, camps["blind"], laws["blind"],
                              64, _job(repo, camps["blind"], laws["blind"], 64, priority=base + 64), base + 64),
              "dex": _probe(repo, camps["seeded"], laws["dex"],
                            64, _job(repo, camps["seeded"], laws["dex"], 64, priority=base + 64), base + 64),
              "earlier": _probe(repo, camps["zone"], laws["earlier"], 64,
                                _job(repo, camps["zone"], laws["earlier"], 64, priority=work_groups.BEHIND + base),
                                work_groups.BEHIND + base),
              "point": _probe(repo, camps["zone"], laws["point"], 16384, point, 2 * base + 16384)}
    for i in range(30):
        _job(repo, camps["blind"], laws["blind"], 128 + i, priority=base + 128 + i)
    assert repo.analysis_backlog_tiers("test-version") == {0: 1, 2: 1, 3: 1, 4: 1}
    work = repo.simulation_work_counts(ordered=True)
    assert work["queued"] == 30 and work["tiers"] == {3: 30}
    state = repo.refresh_scheduler_state(analysis_version="test-version", total_slots=16, max_analyzers=16)
    assert state["analysis_slots"] == 1 and state["analysis_backlog"] == 4, (
        "the zone has no run queued and one probe: its probe is the first work, one slot for it")
    order = [repo.claim_analysis_job(f"analyzer-{i}", "test-version", order="oldest")["result_artifact"]
             for i in range(4)]
    assert order == [probes["point"], probes["dex"], probes["blind"], probes["earlier"]], (
        "the zone's 16,384 before every smaller probe; earlier laws' last")
    assert repo.claim_analysis_job("analyzer-9", "test-version") is None
    repo.conn.execute("UPDATE analysis_queue SET status='queued', lease_owner=NULL, claim_token=NULL")
    assert repo.claim_analysis_job("analyzer-a", "test-version", tier_at_most=work_groups.DEPTH_TIER,
                                   order="oldest")["result_artifact"] == probes["point"]
    assert repo.claim_analysis_job("analyzer-b", "test-version", tier_at_most=work_groups.DEPTH_TIER) is None


def test_a_folder_without_a_focus_keeps_its_shares():
    from graph_scale_dynamics.scheduling import work_groups
    from graph_scale_dynamics.services.worker import main as W
    rows = [{"campaign_id": "1", "work_group": "A", "design_kind": "blind", "leased": 1, "queued": 5, "behind": 0,
             "workers_target": None}]
    assert work_groups.ordered(rows) is None
    assert W.offers(rows, {}) == [(None, None, {})]
    assert work_groups.now_on(rows) == {"ordered": False, "tier": None, "name": None}
