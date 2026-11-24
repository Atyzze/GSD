from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


def _utc(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_campaigns_page_prices_the_queued_seeds_and_the_last_hours_pace(isolated_postgres_schema):
    from graph_scale_dynamics.db.repo import Repo, init_db
    from graph_scale_dynamics.observability import work_left
    from graph_scale_dynamics.services.api import campaign_manager
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        campaign = str(repo.create_campaign({"name": "work left"}, search_seed=3)["campaign_id"])
        law = "law-work-left".ljust(64, "0")
        repo.insert_candidate(law, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        for seed in range(8):
            job = f"done-{seed}"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=law, kind="simulate", stage="rung_n4096",
                            n=4096, seed=seed, replicate=0, spec={}, priority=1, requested_by="test", sealed=False)
            repo.record_attempt(f"{job}-1", job, 1, "executor-1")
            repo.close_attempt(f"{job}-1", 0, 0, 600.0, None, {})
            started = 90 if seed == 0 else 20
            repo.conn.execute("UPDATE attempts SET started_utc=?,finished_utc=? WHERE attempt_id=?",
                              (_utc(started), _utc(10), f"{job}-1"))
            repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job,))
        interrupted = "done-0"
        repo.record_attempt(f"{interrupted}-2", interrupted, 2, "executor-1")
        repo.close_attempt(f"{interrupted}-2", 1, 0, 5.0, "paused", {}, error_class="supervisor_interrupted")
        for seed in range(8, 11):
            repo.insert_job(job_id=f"queued-{seed}", campaign_id=campaign, candidate_id=law, kind="simulate",
                            stage="rung_n4096", n=4096, seed=seed, replicate=0, spec={}, priority=1,
                            requested_by="test", sealed=False)
        other = "law-work-left-2".ljust(64, "0")
        repo.insert_candidate(other, campaign, {"terms": []}, "equilibrium", 1, "BASE_BLOCK_RUNNING")
        repo.insert_job(job_id="queued-other", campaign_id=campaign, candidate_id=other, kind="simulate",
                        stage="rung_n16384", n=16384, seed=1, replicate=0, spec={}, priority=1, requested_by="test",
                        sealed=False)
        scan = work_left.scan(repo)
        assert all(r["exit_code"] == 0 for r in scan["durations"][campaign][4096]), "an interruption is no duration"
        assert len(scan["durations"][campaign][4096]) == 8
        assert scan["pace_core_seconds"][campaign] == pytest.approx(7 * 600 + 3000 + 5, abs=120)
        payload = campaign_manager.overview(repo)
        row = next(r for r in payload["campaigns"] if r["campaign_id"] == campaign)
        work = row["work_left"]
        assert work["graphs_queued"] == 4 and work["queued_by_n"] == {"4096": 3, "16384": 1}
        assert work["queued_core_hours"] == pytest.approx(3 * 600 / 3600, abs=0.01), "16,384 has no seed to price by"
        assert work["laws_climbing"] == 2, "the laws the queued seeds belong to, each once"
        assert work["hours_at_last_hours_pace"] is not None and payload["work_left"]["pool"] >= 1
        assert work["sizes_to_come_unpriced"] == [16384], "no law is measured at 4,096 yet, so the next size is named"
        assert work["sizes_to_come_core_hours"] == 0.0 and work["core_hours_expected"] == work["core_hours_left"]
        assert payload["work_left"]["core_hours_expected"] == payload["work_left"]["core_hours_left"]
        for seed in range(5):
            job = f"deep-{seed}"
            repo.insert_job(job_id=job, campaign_id=campaign, candidate_id=law, kind="simulate", stage="rung_n16384",
                            n=16384, seed=seed, replicate=0, spec={}, priority=1, requested_by="test", sealed=False)
            repo.record_attempt(f"{job}-1", job, 1, "executor-1")
            repo.close_attempt(f"{job}-1", 0, 0, 2400.0 if seed else 5400.0, None, {})
            repo.conn.execute("UPDATE attempts SET started_utc=?,finished_utc=? WHERE attempt_id=?",
                              (_utc(40), _utc(10), f"{job}-1"))
            repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job,))
        repo.conn.execute(
            "INSERT INTO rung_summaries(campaign_id,candidate_id,n,analysis_version,summary_json,created_utc) "
            "VALUES(?,?,?,?,?,?)", (campaign, law, 4096, "analysis-test", "{}", _utc(10)))
        work = next(r for r in campaign_manager.overview(repo)["campaigns"] if r["campaign_id"] == campaign)["work_left"]
        assert work["sizes_to_come_unpriced"] == []
        assert work["sizes_to_come_core_hours"] == pytest.approx(3000.0 / 3600.0, abs=0.01), (
            "one law with seeds queued at 4,096, every law measured there went on, one seed a law, a seed's mean 3,000 s")
        assert work["queued_core_hours"] == pytest.approx((3 * 600 + 2400) / 3600, abs=0.01), (
            "five seeds have finished at 16,384, so the one queued there is priced, at their median")
        assert work["queued_core_hours_at_the_mean"] == pytest.approx((3 * 600 + 3000) / 3600, abs=0.01), (
            "and at their mean, which the one slow seed raises, in the work expected")
        assert work["core_hours_expected"] > work["core_hours_left"] > 0
    finally:
        repo.close()
