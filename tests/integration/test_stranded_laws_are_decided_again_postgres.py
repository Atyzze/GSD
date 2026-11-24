from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


class _Log:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _law(i: int) -> str:
    return f"law-stranded-{i}".ljust(64, "0")


@pytest.fixture
def world(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "stranded laws"}, search_seed=7)["campaign_id"])
    yield repo, campaign
    repo.close()


def _decide(repo, campaign, law, *, action, rule, n, next_n=None, when="2026-09-28T10:00:00Z", seen="3:mark"):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{time.time_ns():020d}-{law[-6:]}", law, n, next_n, action, rule, f"{rule} at {n}", None, None,
         0, 1, False, seen, "decision-engine-2", "{}", when))


def _job(repo, campaign, law, job_id, *, n, status):
    from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
    repo.insert_job(job_id=job_id, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}", n=n,
                    seed=0, replicate=0, spec={}, priority=n, requested_by="test", sealed=False)
    repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
    if status == "done":
        artifact = job_id.ljust(64, "a")
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)", (artifact, 1, "application/json", None, "{}", "t"))
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,"
                          "seed,producer_job,status,error,error_class,attempts,created_utc,updated_utc) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (campaign, artifact, ANALYSIS_VERSION, law, n, 0, job_id, "done", None, None, 1, "t", "t"))


def test_a_law_running_with_no_work_under_a_stop_is_decided_again(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.operations import stranded_laws as Y
    repo, campaign = world
    names = ("stranded", "working", "stopped", "waiting")
    laws = {name: _law(i) for i, name in enumerate(names)}
    for name, law in laws.items():
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1,
                              "STOPPED" if name == "stopped" else "EXTENDING")
    for name in ("stranded", "working", "stopped"):
        _job(repo, campaign, laws[name], f"{name}-done", n=65536, status="done")
        _decide(repo, campaign, laws[name], action="stop", rule="failed", n=65536)
    _job(repo, campaign, laws["working"], "working-queued", n=65536, status="queued")
    _job(repo, campaign, laws["waiting"], "waiting-done", n=1024, status="done")
    _decide(repo, campaign, laws["waiting"], action="run_next", rule="complete_rung", n=1024, next_n=1024,
            when="2026-09-27T15:25:25Z")
    repo.conn.execute("UPDATE engine_decisions_latest d SET jobs_seen=(SELECT COUNT(*)::text || ':' || "
                      "COALESCE(MAX(j.updated_utc),'') FROM jobs j WHERE j.campaign_id=d.campaign_id AND "
                      "j.candidate_id=d.candidate_id AND j.status NOT IN ('queued','leased'))")
    store = DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}})
    before = set(store.laws_awaiting_decision(campaign))
    assert laws["stranded"] not in before, "the controller's own query never takes it up: the defect"

    survey = Y.survey(repo)
    assert [r["candidate_id"] for r in survey["stranded"]] == [laws["stranded"]]
    result = Y.repair(repo)
    assert [e["law"] for e in result["redecided"]] == [laws["stranded"][:10]]
    assert [e["law"] for e in result["waited"]] == [laws["waiting"][:10]] and result["lasting"] == []
    lines = Y.render(result)
    assert "decided again by the engine" in lines[0] and "awaited their decision for over an hour" in lines[1]

    after = set(DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}}).laws_awaiting_decision(campaign))
    assert laws["stranded"] in after and laws["working"] not in after and laws["stopped"] not in after
    assert laws["waiting"] in after, "the waiting law is the controller's again"
    history = repo.conn.execute("SELECT COUNT(*) c FROM engine_decisions WHERE candidate_id=?",
                                (laws["stranded"],)).fetchone()["c"]
    assert history == 1, "the decision history is untouched; only the latest row's `jobs_seen` is marked"
    event = repo.conn.execute("SELECT COUNT(*) c FROM events WHERE topic='law_redecided'").fetchone()["c"]
    assert event == 2
