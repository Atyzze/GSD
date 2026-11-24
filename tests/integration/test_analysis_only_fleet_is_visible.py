from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.observability.rung_distribution import (
    live_work_candidate_ids, rung_distribution_for)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

VERSION = "ladder-contract-v1"
SPEC = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
        "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def _campaign_5_shape(dsn: str, *, lease: bool = True) -> Repo:
    init_db(dsn)
    repo = Repo(dsn)
    spec = {"mode": "continuous", "ladder": [16384, 65536], "analysis_version": VERSION}
    repo.insert_campaign("camp-ladder", spec, content_hash(spec))
    for index in (1, 2):
        candidate = f"cand-ladder-{index}"
        repo.insert_candidate(candidate, "camp-ladder", SPEC, "metropolis", 1,
                              "DISCOVERY_ACTIVE")
        repo.insert_job(job_id=f"job-ladder-{index}", campaign_id="camp-ladder",
                        candidate_id=candidate, kind="simulate",
                        stage="rung_n65536", n=65536, seed=0, replicate=0,
                        spec={"candidate_spec": SPEC}, priority=10, sealed=False,
                        requested_by="ladder-contract")
        claimed = repo.claim_job("executor-ladder", ("simulate",))
        assert claimed
        assert repo.commit_job_result(
            job_id=f"job-ladder-{index}", owner="executor-ladder",
            lease_generation=claimed["lease_generation"], digest=str(index) * 64,
            size=123, media_type="application/json",
            meta={"schema": "raw-simulation-envelope-v1"}, analysis_version=VERSION)
    if lease:
        assert repo.claim_analysis_job("executor-ladder", VERSION) is not None
    return repo


def test_a_leased_analysis_puts_its_law_in_front_of_the_operator(isolated_postgres_schema):
    repo = _campaign_5_shape(isolated_postgres_schema.dsn)
    try:
        assert repo.conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE campaign_id='camp-ladder' "
            "AND status='leased'").fetchone()["c"] == 0, (
            "the fixture must have no live simulation, or it cannot fail")
        working = live_work_candidate_ids(repo, "camp-ladder")
        assert working, (
            "32 slots were busy and this returned nothing, so NOW RESEARCHING "
            "had no law to draw")
        assert len(working) == 1
    finally:
        repo.close()


def test_running_work_still_comes_before_queued(isolated_postgres_schema):
    repo = _campaign_5_shape(isolated_postgres_schema.dsn)
    try:
        repo.insert_job(job_id="job-ladder-queued", campaign_id="camp-ladder",
                        candidate_id="cand-ladder-2", kind="simulate",
                        stage="base_block", n=64, seed=1, replicate=0,
                        spec={"candidate_spec": SPEC}, priority=1, sealed=False,
                        requested_by="ladder-contract")
        working = live_work_candidate_ids(repo, "camp-ladder")
        leased = repo.conn.execute(
            "SELECT candidate_id FROM analysis_queue WHERE campaign_id='camp-ladder' "
            "AND status='leased'").fetchone()["candidate_id"]
        assert working[0] == leased, (
            f"the running law must lead the list, got {working}")
    finally:
        repo.close()


def test_the_ladder_counts_analysis_at_the_rung_it_runs_at(isolated_postgres_schema):
    repo = _campaign_5_shape(isolated_postgres_schema.dsn)
    try:
        rows = {int(row["n"]): row for row in rung_distribution_for(repo, "camp-ladder")}
        assert 65536 in rows, "the rung with all the work must appear at all"
        rung = rows[65536]
        assert rung["analysing"] == 1, (
            f"one analysis is leased at N=65536 and the table said {rung['analysing']}; "
            "a heading that reads '32 analysis job(s) running' above a table of "
            "zeros is why the fleet was reported as broken")
        assert rung["queued_analyses"] == 1
        assert rung["running"] == 0 and rung["queued"] == 0, (
            "the simulate columns stay honest: no rung is running")
    finally:
        repo.close()


def test_a_wholly_idle_campaign_still_reads_as_idle(isolated_postgres_schema):
    repo = _campaign_5_shape(isolated_postgres_schema.dsn, lease=False)
    try:
        rows = {int(row["n"]): row for row in rung_distribution_for(repo, "camp-ladder")}
        assert rows[65536]["analysing"] == 0
        assert rows[65536]["queued_analyses"] == 2
        assert live_work_candidate_ids(repo, "camp-ladder") == [], (
            "queued analyses are not running work; 586 of them would crowd out "
            "the 32 that are, which is the defect build 404 fixed")
    finally:
        repo.close()
