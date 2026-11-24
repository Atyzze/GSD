from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")
LAWS = [f"law-overview-{i}".ljust(64, "0") for i in range(10)]
JOBS = 30_000


@pytest.fixture
def repo(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "overview"}, search_seed=3)["campaign_id"])
    for law in LAWS:
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    repo.insert_job(job_id="overview-template", campaign_id=campaign, candidate_id=LAWS[0], kind="simulate",
                    stage="rung_n64", n=64, seed=0, replicate=0, spec={}, priority=64, requested_by="test",
                    sealed=False)
    columns = ",".join(r["column_name"] for r in repo.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
        "AND table_name='jobs' AND is_generated='NEVER' ORDER BY ordinal_position").fetchall())
    repo.conn.execute(
        f"INSERT INTO jobs({columns}) SELECT {columns} FROM (SELECT (jsonb_populate_record(NULL::jobs, "
        "to_jsonb(t) || jsonb_build_object("
        "'job_id', 'overview-' || g, 'seed', g, 'graph_ordinal', g + 1, "
        "'candidate_id', rpad('law-overview-' || (g % 10), 64, '0'), "
        "'n', CASE WHEN g % 10 < 7 THEN (ARRAY[64,256,1024,4096])[1 + (g / 10) % 4] ELSE 4096 END))).* "
        "FROM jobs t, generate_series(1, ?) g WHERE t.job_id='overview-template') copied", (JOBS,))
    yield repo, campaign
    repo.close()


def test_the_overview_counts_the_graphs_in_linear_time(repo):
    from graph_scale_dynamics.services.api.main import build_fast_overview
    repo, campaign = repo
    repo.conn.execute("SELECT set_config('statement_timeout', '10s', false)")
    started = time.monotonic()
    payload = build_fast_overview(repo, campaign)
    elapsed = time.monotonic() - started
    entry = next(c for c in payload["campaigns"] if str(c["campaign_id"]) == campaign)
    counts = entry["runtime_counts"]
    assert counts["graph_jobs_created"] == JOBS + 1
    assert elapsed < 10.0, f"the overview took {elapsed:.1f}s on {JOBS} jobs"
