from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import quiet_report

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "quiet-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def _fleet(dsn: str, names=("camp-a", "camp-b", "camp-c")) -> Repo:
    init_db(dsn)
    repo = Repo(dsn)
    for name in names:
        repo.insert_campaign(name, SPEC, content_hash(SPEC))
        repo.insert_candidate(f"law-{name}", name, LAW, "metropolis", 1, "BASE_BLOCK_RUNNING")
        repo.insert_job(job_id=f"job-{name}", campaign_id=name, candidate_id=f"law-{name}",
                        kind="simulate", stage="base", n=64, seed=0, replicate=0,
                        spec={"candidate_spec": LAW}, priority=10, sealed=False,
                        requested_by="quiet-contract")
    return repo


def _lease(repo: Repo, campaign: str) -> dict:
    job = repo.claim_job("executor-quiet", ("simulate",), campaigns=(campaign,))
    assert job is not None, "the fixture must hand out work, or 'in flight' is untested"
    return job


def _runner(monkeypatch, base, started=None) -> None:
    import os

    from graph_scale_dynamics.domain.model import utc_now

    def fake_start(record):
        folder = base / "study" / "runs" / record["request_id"]
        folder.mkdir(parents=True, exist_ok=True)
        record["study_process"] = {"pid": os.getpid(), "progress": str(folder / "progress.json"),
                                   "started_utc": utc_now()}
        if started is not None:
            started.append(list(record["campaigns"]))
        return f"every campaign's report cycle at once ({len(record['campaigns'])}), by a stand-in runner"

    monkeypatch.setattr(quiet_report, "start_study_run", fake_start)


def _progress(base, record: dict, campaigns: dict, *, finished: bool = True) -> None:
    import json
    path = base / "study" / "runs" / record["request_id"] / "progress.json"
    path.write_text(json.dumps({"at_once": len(campaigns), "finished": finished, "seconds": 10.0,
                                "campaigns": campaigns}))


def test_a_report_is_refused_while_work_is_in_flight_and_says_what_is(isolated_postgres_schema, tmp_path,
                                                                      monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        job = _lease(repo, "camp-a")
        payload, code = quiet_report.request(repo, "camp-b", "start", report_base=base, db="folder")
        assert code == 409
        assert payload["in_flight"]["total"] == 1
        assert payload["in_flight"]["by_campaign"] == {"camp-a": {"simulate": 1}}
        assert "quiet" in payload["hint"], "the refusal must name the way through"
        assert not quiet_report.in_progress(repo), "nothing was started"

        repo.release_job(job["job_id"], "executor-quiet", int(job["lease_generation"]))
        payload, code = quiet_report.request(repo, "camp-b", "start", report_base=base, db="folder")
        assert code == 202, payload
        assert payload["quiet_report"]["campaigns"] == ["camp-b"] and payload["quiet_report"]["only"] is True
        assert control.reporting_focus(repo) == "camp-b", (
            "the bundle the page offers must be the campaign just reported on")
    finally:
        repo.close()


def test_a_cycle_without_the_report_root_and_the_database_is_refused(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        for action in ("start", "quiet"):
            payload, code = quiet_report.request(repo, "camp-a", action)
            assert code == 409 and "report folder and the database" in payload["error"], payload
        assert not quiet_report.in_progress(repo)
    finally:
        repo.close()


def test_a_paused_campaign_does_not_block_reporting(isolated_postgres_schema, tmp_path, monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        for name in ("camp-a", "camp-b", "camp-c"):
            assert control.pause(repo, name)["ok"]
        assert quiet_report.work_in_flight(repo)["total"] == 0
        assert quiet_report.request(repo, "camp-a", "start", report_base=base, db="folder")[1] == 202
    finally:
        repo.close()


def test_the_quiet_report_pauses_reports_every_campaign_and_resumes_exactly_what_it_paused(
        isolated_postgres_schema, tmp_path, monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    started: list = []
    _runner(monkeypatch, base, started)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert control.pause(repo, "camp-c")["ok"]
        job = _lease(repo, "camp-a")

        payload, code = quiet_report.request(repo, "camp-b", "quiet", report_base=base, db="folder")
        assert code == 202, payload
        record = payload["quiet_report"]
        assert sorted(record["paused"]) == ["camp-a", "camp-b"]
        assert record["campaigns"] == ["camp-a", "camp-b", "camp-c"], "every campaign, whichever is selected"
        assert record["stage"] == quiet_report.PAUSING

        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.DRAINING
        for name in ("camp-a", "camp-b"):
            assert control.is_paused(repo, name)

        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.DRAINING
        assert record["in_flight"]["total"] == 1 and started == [], "no cycle while work is in flight"

        repo.release_job(job["job_id"], "executor-quiet", int(job["lease_generation"]))
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and started == [["camp-a", "camp-b", "camp-c"]]
        again, code = quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder")
        assert code == 202 and again["already"] and again["quiet_report"]["request_id"] == record["request_id"], (
            "a second click on the study bundle joins the one being made")
        assert quiet_report.request(repo, "camp-a", "start", report_base=base, db="folder")[1] == 409
        assert quiet_report.step(repo)["stage"] == quiet_report.REPORTING, "still running"
        _progress(base, record, {name: {"state": "complete"} for name in ("camp-a", "camp-b", "camp-c")})
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.MAINTAINING, "544 (F): the maintenance, while the fleet is quiet"
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.RESUMING
        assert not any(e.startswith("repair") for e in record["maintenance"]["errors"])
        assert "given back" in record["maintenance"]["note"]
        assert [r["campaign_id"] for r in record["reported"]] == ["camp-a", "camp-b", "camp-c"]
        assert {r["outcome"] for r in record["reported"]} == {"complete"}

        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.BUNDLING, "every cycle completed: one study bundle next"
        assert sorted(record["resumed"]) == ["camp-a", "camp-b"]
        assert not control.is_paused(repo, "camp-a")
        assert not control.is_paused(repo, "camp-b")
        assert control.is_paused(repo, "camp-c"), (
            "the quiet report resumed a campaign the operator had paused themselves")
        assert control.reporting_focus(repo) == "camp-b", "reporting goes back to the page's campaign"
    finally:
        repo.close()


def test_a_failed_cycle_costs_the_other_campaigns_nothing_and_still_resumes_the_fleet(
        isolated_postgres_schema, tmp_path, monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    try:
        assert quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder")[1] == 202
        quiet_report.step(repo)
        record = quiet_report.step(repo)
        _progress(base, record, {"camp-a": {"state": "error", "error": "boom"}, "camp-b": {"state": "running"}},
                  finished=False)
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and record["campaign_id"] == "camp-b"
        assert "boom" in record["error"]
        _progress(base, record, {"camp-a": {"state": "error", "error": "boom"}, "camp-b": {"state": "complete"}})
        assert quiet_report.step(repo)["stage"] == quiet_report.MAINTAINING
        assert quiet_report.step(repo)["stage"] == quiet_report.RESUMING
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.BUNDLING
        assert [r["outcome"] for r in record["reported"]] == ["error", "complete"]
        assert not control.is_paused(repo, "camp-a")
    finally:
        repo.close()


def _published(base, campaign: str, state: str = "COMPLETE") -> None:
    import json

    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.operations.report_home import root_for
    from graph_scale_dynamics.research.report_bundle import REPORT_CODES
    root = root_for(base, campaign)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    for code in REPORT_CODES:
        (root / "reports" / f"{code}.json").write_text(json.dumps(
            {"bundle_revision": f"rev-{campaign}", "report_cycle_id": f"cycle-{campaign}", "body": {}}))
    (root / "manifest.json").write_text(json.dumps({
        "campaign_id": campaign, "cycle_state": state, "bundle_revision": f"rev-{campaign}",
        "bundle_cycle_id": f"cycle-{campaign}", "generation_finished_utc": utc_now()}))


def test_the_study_bundle_holds_every_campaign_whose_cycle_completed_and_names_the_rest(isolated_postgres_schema,
                                                                                       tmp_path, monkeypatch):
    import shutil

    if shutil.which("zstd") is None:
        pytest.skip("the bundle codec is zstd")
    from graph_scale_dynamics.reporting import study_bundle

    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    try:
        payload, code = quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder")
        assert code == 202 and payload["quiet_report"]["report_base"] == str(base)
        quiet_report.step(repo)
        record = quiet_report.step(repo)
        _published(base, "camp-a")
        _published(base, "camp-b", state="PARTIAL")
        _progress(base, record, {"camp-a": {"state": "complete"}, "camp-b": {"state": "complete_with_errors"}})
        assert quiet_report.step(repo)["stage"] == quiet_report.MAINTAINING
        assert quiet_report.step(repo)["stage"] == quiet_report.RESUMING
        assert quiet_report.step(repo)["stage"] == quiet_report.BUNDLING
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.DONE, record.get("error")
        made = record["study_bundle"]
        assert made["study_id"] == "default" and [c["campaign_id"] for c in made["campaigns"]] == ["camp-a"]
        assert [m["campaign_id"] for m in made["missing"]] == ["camp-b"], "a partial cycle is named, not dropped"
        assert (study_bundle.bundles_dir(base) / made["filename"]).is_file()
        assert study_bundle.read_index(base)["bundles"][0]["filename"] == made["filename"]
    finally:
        repo.close()


def test_an_expired_lease_is_not_work_in_flight(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a",))
    try:
        _lease(repo, "camp-a")
        assert quiet_report.work_in_flight(repo)["total"] == 1
        assert quiet_report.work_in_flight(repo, now="9999-01-01T00:00:00Z")["total"] == 0
    finally:
        repo.close()


def test_the_quiet_phase_gives_back_an_analysis_stopped_at_the_memory_ceiling_before_resuming(isolated_postgres_schema,
                                                                                           tmp_path, monkeypatch):
    from graph_scale_dynamics.operations import memory_giveback as M
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a",))
    try:
        repo.conn.execute("UPDATE jobs SET status='done' WHERE job_id='job-camp-a'")
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,created_utc) "
                          "VALUES(?,?,?,?,?,?)", ("k" * 64, 1, "application/json", None, "{}", "2026-09-29T10:00:00Z"))
        repo.conn.execute("INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
                          "producer_job,status,error,error_class,attempts,created_utc,updated_utc) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          ("camp-a", "k" * 64, repo.campaign_analysis_contract("camp-a"), "law-camp-a", 64, 0,
                           "job-camp-a", "failed",
                           "ceiling", M.MEMORY_CEILING_CLASS, 3, "2026-09-29T10:00:00Z", "2026-09-29T10:00:00Z"))
        repo.conn.execute(
            "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
            "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("camp-a", "0001", "law-camp-a", 64, None, "stop", "failed", "failed at 64", None, None, 0, 1, False,
             "1:mark", "decision-engine-2", "{}", "2026-09-29T10:05:00Z"))
        repo.conn.execute("UPDATE campaign_candidates SET state='STOPPED' WHERE candidate_id='law-camp-a'")
        assert quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder")[1] == 202
        quiet_report.step(repo)
        record = quiet_report.step(repo)
        _progress(base, record, {"camp-a": {"state": "complete"}})
        assert quiet_report.step(repo)["stage"] == quiet_report.MAINTAINING
        assert control.is_paused(repo, "camp-a"), "the maintenance runs while the fleet is still quiet"
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.RESUMING
        assert record["maintenance"]["failures"]["memory_given_back"] == 1
        assert "1 of them stopped at the memory ceiling" in record["maintenance"]["note"]
        state = repo.conn.execute("SELECT state FROM campaign_candidates WHERE candidate_id='law-camp-a'").fetchone()
        assert state["state"] == "BASE_BLOCK_RUNNING"
        row = repo.conn.execute("SELECT status,error_class FROM analysis_queue WHERE input_artifact=?",
                                ("k" * 64,)).fetchone()
        assert (row["status"], row["error_class"]) == ("queued", M.GIVEN_BACK_CLASS)
    finally:
        repo.close()


def test_every_campaign_reports_at_once_through_the_study_runner(isolated_postgres_schema, tmp_path, monkeypatch):
    import json
    base = tmp_path / "FOLDER" / "var" / "reports"
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    started = []

    def fake_start(record):
        folder = base / "study" / "runs" / record["request_id"]
        folder.mkdir(parents=True, exist_ok=True)
        record["study_process"] = {"pid": os.getpid(), "progress": str(folder / "progress.json"),
                                   "started_utc": "2026-09-29T20:00:00Z"}
        started.append(list(record["campaigns"]))
        return "every campaign's report cycle at once (2), by the study runner"

    import os
    monkeypatch.setattr(quiet_report, "start_study_run", fake_start)
    try:
        payload, code = quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder",
                                             api_base="http://127.0.0.1:1")
        assert code == 202 and payload["quiet_report"]["study_run"] is True
        quiet_report.step(repo)
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and started == [["camp-a", "camp-b"]]
        progress = base / "study" / "runs" / record["request_id"] / "progress.json"
        progress.write_text(json.dumps({"at_once": 2, "campaigns": {"camp-a": {"state": "complete", "seconds": 40.0},
                                                                     "camp-b": {"state": "running"}}}))
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and [r["campaign_id"] for r in record["reported"]] == ["camp-a"]
        assert record["campaign_id"] == "camp-b" and record["index"] == 1
        progress.write_text(json.dumps({"at_once": 2, "finished": True, "seconds": 61.0,
                                        "campaigns": {"camp-a": {"state": "complete"},
                                                      "camp-b": {"state": "error", "error": "boom"}}}))
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.MAINTAINING and "2 at once" in record["history"][-1]["note"]
        assert [r["outcome"] for r in record["reported"]] == ["complete", "error"] and "boom" in record["error"]
        assert quiet_report.step(repo)["stage"] == quiet_report.RESUMING
    finally:
        repo.close()


def test_one_campaign_s_cycle_goes_through_the_study_runner_too(isolated_postgres_schema, tmp_path, monkeypatch):
    import json
    import os
    base = tmp_path / "FOLDER" / "var" / "reports"
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    started = []

    def fake_start(record):
        folder = base / "study" / "runs" / record["request_id"]
        folder.mkdir(parents=True, exist_ok=True)
        record["study_process"] = {"pid": os.getpid(), "progress": str(folder / "progress.json"),
                                   "started_utc": "2026-09-30T20:00:00Z"}
        started.append((list(record["campaigns"]), record.get("only")))
        return "campaign camp-b's report cycle, by the study runner, one report at a time"

    monkeypatch.setattr(quiet_report, "start_study_run", fake_start)
    try:
        job = _lease(repo, "camp-a")
        payload, code = quiet_report.request(repo, "camp-b", "start", report_base=base, db="folder")
        assert code == 409 and payload["in_flight"]["total"] == 1, "still refused while work is in flight"
        repo.release_job(job["job_id"], "executor-quiet", int(job["lease_generation"]))
        payload, code = quiet_report.request(repo, "camp-b", "start", report_base=base, db="folder")
        assert code == 202 and payload["quiet_report"]["only"] is True, payload
        assert payload["quiet_report"]["campaigns"] == ["camp-b"] and payload["quiet_report"]["paused"] == []
        assert control.reporting_focus(repo) == "camp-b"
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and started == [(["camp-b"], True)], "no drain to wait on"
        progress = base / "study" / "runs" / record["request_id"] / "progress.json"
        progress.write_text(json.dumps({"at_once": 1, "finished": True, "seconds": 12.0,
                                        "campaigns": {"camp-b": {"state": "complete", "seconds": 12.0}}}))
        assert quiet_report.step(repo)["stage"] == quiet_report.MAINTAINING
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.RESUMING and "maintenance" not in record
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.DONE and record.get("study_bundle") is None, "no study bundle"
        assert [r["outcome"] for r in record["reported"]] == ["complete"]
    finally:
        repo.close()


def test_the_study_runner_reports_every_campaign_into_its_root(isolated_postgres_schema, tmp_path):
    import json
    import subprocess
    import sys

    from graph_scale_dynamics import PROJECT_ROOT
    from graph_scale_dynamics.operations.report_home import root_for
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    repo.close()
    base = tmp_path / "var" / "reports"
    progress = base / "study" / "runs" / "t1" / "progress.json"
    done = subprocess.run([sys.executable, "-m", "graph_scale_dynamics.services.reporter.study_run",
                           "--db", isolated_postgres_schema.reference, "--base", str(base),
                           "--campaigns", "camp-a,camp-b", "--progress", str(progress), "--request-id", "t1"],
                          cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=600)
    record = json.loads(progress.read_text())
    assert record["finished"] is True and record["at_once"] >= 1, (done.stdout, done.stderr)
    for campaign in ("camp-a", "camp-b"):
        entry = record["campaigns"][campaign]
        log = (progress.parent / f"{campaign}.log").read_text(errors="replace")
        assert entry["state"] in ("complete", "complete_with_errors"), (entry, log[-3000:])
        manifest = json.loads((root_for(base, campaign) / "manifest.json").read_text())
        assert manifest["cycle"]["report_pool"]["workers"] >= 1 and manifest["cycle_state"]
        assert list((root_for(base, campaign) / "reports").glob("*.json")), "no report was written"
        cycle = manifest["cycle"]
        assert cycle["snapshot_peak_bytes"] > 0 and cycle["snapshot_parts"], cycle
        assert cycle["snapshot_decompressed_bytes"] > 0 and "types" in [s["stage"] for s in cycle["snapshot_stages"]]
        cost = json.loads((root_for(base, campaign) / "study_run_cost.json").read_text())
        assert cost["transport"] == "in place (548)" and cost["worker_resident_bytes"] > 0, cost


def test_the_study_bundle_is_made_with_every_batch_shown(isolated_postgres_schema, tmp_path, monkeypatch):
    from graph_scale_dynamics.services.api.study_scope import STUDY
    assert quiet_report.STUDY_SCOPE == STUDY
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        payload, code = quiet_report.request(repo, STUDY, "start", report_base=base, db="folder")
        assert code == 400 and "one campaign" in payload["error"], "one campaign's cycle still needs one campaign"
        payload, code = quiet_report.request(repo, STUDY, "quiet", report_base=base, db="folder")
        assert code == 202, payload
        record = payload["quiet_report"]
        assert record["campaigns"] == ["camp-a", "camp-b", "camp-c"] and record["selected"] is None
    finally:
        repo.close()



def test_a_study_bundle_cancelled_resumes_what_it_paused_and_makes_no_bundle(isolated_postgres_schema, tmp_path,
                                                                            monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert quiet_report.request(repo, "camp-a", "cancel", report_base=base, db="folder")[1] == 409
        payload, code = quiet_report.request(repo, "camp-b", "quiet", report_base=base, db="folder")
        assert code == 202, payload
        quiet_report.step(repo)
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING
        import subprocess
        child = subprocess.Popen(["sleep", "60"], start_new_session=True)
        record["study_process"]["pid"] = child.pid
        quiet_report._save(repo, record)
        payload, code = quiet_report.request(repo, "camp-b", "cancel", report_base=base, db="folder")
        assert code == 202 and payload["quiet_report"]["stage"] == quiet_report.RESUMING, payload
        assert child.wait(timeout=10) < 0, "the study's report runner is stopped"
        assert "cancelled at reporting" in payload["quiet_report"]["error"]
        record = quiet_report.step(repo)
        assert record["stage"] == "done" and not record.get("study_bundle"), "a cancelled bundle makes no bundle"
        assert not any(control.is_paused(repo, name) for name in ("camp-a", "camp-b", "camp-c"))
        assert quiet_report.request(repo, "camp-b", "cancel", report_base=base, db="folder")[1] == 409
    finally:
        repo.close()


def test_a_runner_that_keeps_failing_says_why_and_resumes_the_fleet(isolated_postgres_schema, tmp_path, monkeypatch,
                                                                    capsys):
    base = tmp_path / "FOLDER" / "var" / "reports"
    _runner(monkeypatch, base)
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert quiet_report.request(repo, "camp-b", "quiet", report_base=base, db="folder")[1] == 202
        error = RuntimeError("the report root went away")
        quiet_report._runner_failed(lambda: Repo(isolated_postgres_schema.dsn), error, 1)
        record = quiet_report.state(repo)
        assert record["stage"] == quiet_report.PAUSING and record["runner_error"].endswith("went away")
        assert "failure 1: RuntimeError" in capsys.readouterr().err, "the failure is logged, not swallowed"
        quiet_report._runner_failed(lambda: Repo(isolated_postgres_schema.dsn), error,
                                    quiet_report.RUNNER_FAILURES_BEFORE_RESUMING)
        record = quiet_report.state(repo)
        assert record["stage"] == quiet_report.RESUMING and record["cancelled"]
        assert "failed 15 times in a row" in record["error"]
    finally:
        repo.close()


def test_a_quiet_bundle_leaves_the_n_push_running_and_waits_for_nothing_of_it(isolated_postgres_schema, tmp_path,
                                                                             monkeypatch):
    base = tmp_path / "FOLDER" / "var" / "reports"
    started: list = []
    _runner(monkeypatch, base, started)
    repo = _fleet(isolated_postgres_schema.dsn, names=("camp-a", "camp-b"))
    try:
        pushed = dict(SPEC, study_design={"kind": "focus", "focus": {"part": "P"}})
        repo.insert_campaign("camp-push", pushed, content_hash(pushed))
        repo.insert_candidate("law-push", "camp-push", LAW, "metropolis", 1, "EXTENDING")
        repo.insert_job(job_id="job-push", campaign_id="camp-push", candidate_id="law-push", kind="simulate",
                        stage="extend", n=1048576, seed=2, replicate=0, spec={"candidate_spec": LAW}, priority=10,
                        sealed=False, requested_by="quiet-contract")
        seed = _lease(repo, "camp-push")
        assert quiet_report.beside_the_push(repo) == ["camp-push"]

        payload, code = quiet_report.request(repo, "camp-a", "quiet", report_base=base, db="folder")
        assert code == 202, payload
        record = payload["quiet_report"]
        assert sorted(record["paused"]) == ["camp-a", "camp-b"] and record["beside"] == ["camp-push"], (
            "899, the operator's answer of 18:26: a bundle leaves the N-push's seeds running")
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.DRAINING and not control.is_paused(repo, "camp-push")
        record = quiet_report.step(repo)
        assert record["stage"] == quiet_report.REPORTING and started, "the N-push's seed in flight holds nothing back"
        assert record["in_flight"]["beside"] == {"camp-push": {"simulate": 1}}
        assert repo.conn.execute("SELECT status FROM jobs WHERE job_id=?", (seed["job_id"],)).fetchone()[
            "status"] == "leased"
        assert quiet_report.quiet_problem(repo) is None, "one campaign's cycle is not refused for the N-push's seed"
    finally:
        repo.close()
