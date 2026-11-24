from __future__ import annotations


import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

RUNNING_LAWS = 4
QUEUED_LAWS = 400


@pytest.fixture
def campaign_with_a_deep_queue(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db

    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        campaign_id = str(repo.create_campaign({"name": "deep queue"}, search_seed=1)["campaign_id"])

        def add(cid: str, state: str, status: str) -> None:
            repo.insert_candidate(cid, campaign_id, {"terms": []}, "equilibrium", 1, state)
            repo.insert_job(job_id=f"j-{cid}", campaign_id=campaign_id, candidate_id=cid,
                            kind="simulate", stage="base", n=65536, seed=0, replicate=0,
                            spec={}, priority=100, requested_by="test")
            repo.conn.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, f"j-{cid}"))

        for i in range(QUEUED_LAWS):
            add(f"q{i:04d}".ljust(64, "0"), "BASE_BLOCK_RUNNING", "queued")
        for i in range(RUNNING_LAWS):
            add(f"r{i:04d}".ljust(64, "0"), "PARKED", "leased")
    return isolated_postgres_schema.dsn, campaign_id


def test_running_work_is_listed_however_deep_the_queue_is(campaign_with_a_deep_queue):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview

    dsn, campaign_id = campaign_with_a_deep_queue
    with Repo(dsn) as repo:
        overview = build_fast_overview(repo, campaign_id)

    listed = {str(row["candidate_id"]) for row in (overview.get("active") or [])}
    running = {f"r{i:04d}".ljust(64, "0") for i in range(RUNNING_LAWS)}
    missing = sorted(running - listed)
    assert not missing, (
        f"{len(missing)} of {RUNNING_LAWS} laws with a running rung are absent from the "
        "active list while the queue is 400 deep. NOW RESEARCHING empties and the "
        "operator sees an idle table beside a busy fleet.")


def test_the_queue_still_fills_the_rest_of_the_window(campaign_with_a_deep_queue):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview

    dsn, campaign_id = campaign_with_a_deep_queue
    with Repo(dsn) as repo:
        overview = build_fast_overview(repo, campaign_id)

    listed = {str(row["candidate_id"]) for row in (overview.get("active") or [])}
    queued_shown = sum(1 for cid in listed if cid.startswith("q"))
    assert queued_shown > 0, "no queued law is shown at all"


def test_the_rung_distribution_counts_every_bracket(campaign_with_a_deep_queue):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview

    dsn, campaign_id = campaign_with_a_deep_queue
    with Repo(dsn) as repo:
        overview = build_fast_overview(repo, campaign_id)

    rows = {int(r["n"]): r for r in (overview.get("rung_distribution") or [])}
    assert 65536 in rows, "the rung with all the work has no row in the distribution"
    assert rows[65536]["running"] == RUNNING_LAWS
    assert rows[65536]["queued"] == QUEUED_LAWS


def test_the_distribution_is_a_declared_key_even_when_empty(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.services.api.main import build_fast_overview

    init_db(isolated_postgres_schema.dsn)
    init_db(isolated_postgres_schema.dsn)
    with Repo(isolated_postgres_schema.dsn) as repo:
        empty = str(repo.create_campaign({"name": "empty"}, search_seed=2)["campaign_id"])
        overview = build_fast_overview(repo, empty)
    assert "rung_distribution" in overview
    assert overview["rung_distribution"] == []


def test_a_seed_whose_worker_commits_reads_committing_not_evolving(campaign_with_a_deep_queue):
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.services.api.main import build_fast_overview
    from graph_scale_dynamics.services.api.overview import build_overview
    from graph_scale_dynamics.services.worker.main import COMMITTING

    dsn, campaign_id = campaign_with_a_deep_queue
    committing, evolving = "r0000".ljust(64, "0"), "r0001".ljust(64, "0")
    with Repo(dsn) as repo:
        for law, worker in ((committing, "worker-a"), (evolving, "worker-b")):
            repo.conn.execute("UPDATE jobs SET lease_owner=? WHERE job_id=?", (worker, f"j-{law}"))
            repo.conn.execute("UPDATE campaign_candidates SET state='BASE_BLOCK_RUNNING' WHERE candidate_id=?", (law,))
        repo.heartbeat("worker-a", {"job": f"j-{committing}", "phase": COMMITTING, "elapsed": 9.0}, paced=True)
        repo.heartbeat("worker-b", {"job": f"j-{evolving}", "elapsed": 9.0}, paced=True)
        for overview in (build_fast_overview(repo, campaign_id), build_overview(repo, campaign_id)):
            phases = {str(row["candidate_id"]): [run.get("phase") for run in row.get("running") or []]
                      for row in overview.get("active") or []}
            assert phases[committing] == ["committing"] and phases[evolving] == [None], phases
        repo.heartbeat("worker-a", {"job": "j-another", "phase": COMMITTING}, paced=True)
        phases = {str(row["candidate_id"]): [run.get("phase") for run in row.get("running") or []]
                  for row in build_fast_overview(repo, campaign_id).get("active") or []}
        assert phases[committing] == [None], "a worker committing another job's result is not this one's"


def test_a_worker_that_cannot_say_it_commits_still_commits():
    from graph_scale_dynamics.services.worker.main import say_committing

    class Silent:
        def heartbeat(self, *args, **kwargs):
            raise RuntimeError("no heartbeat table here")

    said = []

    class Log:
        def write(self, event, **fields):
            said.append((event, fields))

    say_committing(Silent(), Log(), "worker-a", {"job_id": "j-1"}, 3, 12.5, 1024)
    assert said and said[0][0] == "committing_unsaid" and "no heartbeat table" in said[0][1]["error"]
