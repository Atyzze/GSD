from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")

FIRST = {64: [("done", True)] * 3,
         256: [("done", True), ("done", True), ("done", False), ("failed", False)],
         1024: [(None, False), (None, False), ("leased", False)]}
SECOND = {64: [("done", True), ("cancelled", False)]}
THIRD = {4096: [("done", True)] * 3}
LONGER = {4096: [(0, "done", True), (1, None, False)]}


def _campaign(repo, name: str, jobs: dict, longer: dict | None = None, spec: dict | None = None) -> str:
    campaign = str(repo.create_campaign({"name": name, **(spec or {})}, search_seed=3)["campaign_id"])
    law = f"law-{name}".ljust(64, "0")
    repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
    for n, seeds in jobs.items():
        for seed, (status, result) in enumerate(seeds):
            job = f"{name}-{n}-{seed}"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=law, kind="simulate", stage=f"rung_n{n}",
                            n=n, seed=seed, replicate=0, spec={}, priority=1, requested_by="test", sealed=False)
            if status:
                repo.conn.execute("UPDATE jobs SET status=?,result_artifact=? WHERE job_id=?",
                                  (status, f"blob-{job}" if result else None, job))
    for n, seeds in (longer or {}).items():
        for seed, status, result in seeds:
            job = f"{name}-{n}-{seed}-longer"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=law, kind="simulate",
                            stage=f"longer_n{n}_x2", n=n, seed=seed, replicate=0, spec={}, priority=1,
                            requested_by="test", sealed=False)
            if status:
                repo.conn.execute("UPDATE jobs SET status=?,result_artifact=? WHERE job_id=?",
                                  (status, f"blob-{job}" if result else None, job))
    return campaign


def test_the_card_and_the_ladder_count_graphs_and_the_header_simulations(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.rung_distribution import rung_distribution_for
    from graph_scale_dynamics.services.api import campaign_manager
    from graph_scale_dynamics.services.api.main import build_fast_overview
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        first = _campaign(repo, "first", FIRST)
        second = _campaign(repo, "second", SECOND)
        third = _campaign(repo, "third", THIRD, LONGER)
        cards = {row["campaign_id"]: row for row in campaign_manager.overview(repo)["campaigns"]}
        assert cards[first]["graphs_bought"] == 10, "every seed of every rung bought, whatever its status"
        assert cards[first]["graphs_finished"] == 5, "done with a result; a done job without one is not a graph done"
        assert (cards[second]["graphs_bought"], cards[second]["graphs_finished"]) == (2, 1)
        assert (cards[third]["graphs_bought"], cards[third]["graphs_finished"]) == (3, 3), \
            "a seed run again on a longer chain is the same graph"
        assert (cards[third]["graphs_created"], cards[third]["graphs_total"]) == (5, 4), "and two more simulations"

        for campaign in (first, second, third):
            ladder = rung_distribution_for(repo, campaign)
            assert sum(rung["graphs"] for rung in ladder) == cards[campaign]["graphs_bought"], \
                "the card's first number is the ladder's foot row"
            assert sum(rung["completed"] for rung in ladder) == cards[campaign]["graphs_finished"]
            assert sum(rung["simulations"] for rung in ladder) == cards[campaign]["graphs_created"]
        at = {rung["n"]: rung for rung in rung_distribution_for(repo, third)}[4096]
        assert (at["graphs"], at["simulations"], at["completed"], at["queued"]) == (3, 5, 3, 1), \
            "the queued longer chain is work in flight on a graph already done"
        at = {rung["n"]: rung for rung in rung_distribution_for(repo, first)}[256]
        assert (at["completed"], at["done_without_artifact"], at["abandoned"]) == (2, 1, 1)

        header = {str(c["campaign_id"]): c["runtime_counts"] for c in build_fast_overview(repo, first)["campaigns"]}
        for campaign in (first, second, third):
            assert header[campaign]["graph_jobs_created"] == cards[campaign]["graphs_created"]
            assert header[campaign]["completed_graph_realizations"] == cards[campaign]["graphs_total"]
        assert sum(counts["graph_jobs_created"] for counts in header.values()) == 17, \
            "the header's tile reads every campaign's simulations: the cards' added up"
    finally:
        repo.close()


def test_the_header_counts_the_graphs_each_simulation_grows(isolated_postgres_schema):
    import json

    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability.rung_distribution import chains_per_seed
    from graph_scale_dynamics.services.api.main import build_fast_overview
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        plain = _campaign(repo, "plain", SECOND)
        starts = {"sampling_contract": {"given_starts": ["random", "honeycomb", "cubic", "tesseract"]}}
        given_chains = _campaign(repo, "given_chains", THIRD, LONGER, starts)
        spec = json.loads(repo.conn.execute("SELECT spec_json FROM campaigns WHERE campaign_id=?",
                                            (given_chains,)).fetchone()["spec_json"])
        assert chains_per_seed(spec) == 5
        header = {str(c["campaign_id"]): c["runtime_counts"] for c in build_fast_overview(repo, plain)["campaigns"]}
        assert header[plain]["graphs_grown"] == header[plain]["graph_jobs_created"] == 2
        assert header[given_chains]["graphs_grown"] == 5 * header[given_chains]["graph_jobs_created"] == 25, \
            "each simulation grows its seed's five chains, the empty start and its four given chains"
        assert header[given_chains]["graphs_grown_last_hour"] == 5 * header[given_chains]["graphs_finished_last_hour"]
    finally:
        repo.close()
