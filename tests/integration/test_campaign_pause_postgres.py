from __future__ import annotations

import pytest

from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.operations import campaign_control as control

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SPEC = {"mode": "continuous", "ladder": [64, 256], "analysis_version": "pause-contract-v1"}
LAW = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
       "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}


def _fleet(dsn: str) -> Repo:
    init_db(dsn)
    repo = Repo(dsn)
    for name in ("camp-a", "camp-b"):
        repo.insert_campaign(name, SPEC, content_hash(SPEC))
        repo.insert_candidate(f"law-{name}", name, LAW, "metropolis", 1, "BASE_BLOCK_RUNNING")
        repo.insert_job(job_id=f"job-{name}", campaign_id=name, candidate_id=f"law-{name}",
                        kind="simulate", stage="base", n=64, seed=0, replicate=0,
                        spec={"candidate_spec": LAW}, priority=10, sealed=False,
                        requested_by="pause-contract")
    return repo


def _claim(repo: Repo, campaign: str) -> dict | None:
    job = repo.claim_job("executor-pause", ("simulate",), campaigns=(campaign,))
    if job is not None:
        repo.release_job(job["job_id"], "executor-pause", int(job["lease_generation"]))
    return job


def test_a_paused_campaign_hands_out_no_work_and_its_neighbour_still_does(
        isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert _claim(repo, "camp-a") is not None, (
            "the fixture must hand out work before the pause, or this test "
            "cannot tell a pause from an empty queue")
        assert control.pause(repo, "camp-a")["ok"]
        assert _claim(repo, "camp-a") is None, (
            "a paused campaign handed out a simulation job; the cap is enforced "
            "in the worker's allocator a tick earlier, and the door is where it "
            "has to hold")
        assert _claim(repo, "camp-b") is not None, (
            "pausing one campaign stopped another; the clause must be per campaign")
    finally:
        repo.close()


def test_resume_opens_the_door_again(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a")
        assert control.resume(repo, "camp-a")["ok"]
        assert _claim(repo, "camp-a") is not None
    finally:
        repo.close()


def test_a_pause_cancels_nothing(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a")
        row = repo.conn.execute(
            "SELECT status FROM jobs WHERE job_id='job-camp-a'").fetchone()
        assert row["status"] == "queued", (
            "a pause cancelled queued work; that is what closing does, and it is "
            "why closing and reopening was not a usable pause")
        campaign = repo.campaign("camp-a")
        assert campaign["status"] == "active"
        assert control.derived_state(campaign) == "paused"
        assert repo.candidate_state_counts("camp-a") == {"BASE_BLOCK_RUNNING": 1}
    finally:
        repo.close()


def test_the_pause_and_the_resume_are_on_the_record(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a", reason="because the operator said so")
        control.resume(repo, "camp-a")
        kinds = [event["event_type"] for event in repo.campaign_events("camp-a")]
        assert "campaign_paused" in kinds and "campaign_resumed" in kinds, (
            "a control the page offers has to leave a trail the page can show")
    finally:
        repo.close()


def test_an_extend_only_switch_the_operator_set_survives_a_pause(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        repo.set_campaign_extend_only("camp-a", True)
        control.pause(repo, "camp-a")
        control.resume(repo, "camp-a")
        assert repo.campaign_extend_only("camp-a") is True, (
            "resume cleared an extend-only switch the operator had set; a pause "
            "that changes the experiment it paused is not a pause")
    finally:
        repo.close()


def test_a_pause_stops_the_proposer_as_well(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert repo.campaign_extend_only("camp-a") is False
        control.pause(repo, "camp-a")
        assert repo.campaign_extend_only("camp-a") is True, (
            "a paused campaign kept proposing; the pool would grow for a week "
            "while nothing ran")
    finally:
        repo.close()


def test_a_closed_campaign_is_reopened_rather_than_resumed(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        repo.stop_campaign_work("camp-a")
        refused = control.resume(repo, "camp-a")
        assert not refused["ok"] and "reopen" in refused["problem"]
    finally:
        repo.close()


def test_a_closed_campaign_reopens_beside_a_running_one(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        repo.stop_campaign_work("camp-a")
        assert repo.campaign("camp-b")["status"] == "active"
        problems = control.reopen_problems(repo, "camp-a")
        assert not any("camp-b" in problem or "another campaign" in problem
                       for problem in problems), (
            f"reopening an earlier arm is refused while the current one runs: {problems}")
    finally:
        repo.close()


def test_a_share_is_changeable_at_any_time(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert control.set_workers(repo, "camp-a", 8)["ok"]
        assert repo.campaign("camp-a")["workers_target"] == 8
        assert control.set_workers(repo, "camp-a", 3)["ok"]
        assert repo.campaign("camp-a")["workers_target"] == 3
        assert control.set_workers(repo, "camp-a", None)["ok"]
        assert repo.campaign("camp-a")["workers_target"] is None
    finally:
        repo.close()


def test_allocating_no_workers_is_the_same_thing_as_a_pause(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.set_workers(repo, "camp-a", 0)
        campaign = repo.campaign("camp-a")
        assert control.derived_state(campaign) == "paused"
        assert repo.campaign_extend_only("camp-a") is True, (
            "a campaign allocated no workers must stop proposing too, or the pool "
            "grows all week while nothing runs")
        assert _claim(repo, "camp-a") is None
    finally:
        repo.close()


def test_a_pause_puts_back_the_share_it_found(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.set_workers(repo, "camp-a", 6)
        control.pause(repo, "camp-a")
        control.resume(repo, "camp-a")
        assert repo.campaign("camp-a")["workers_target"] == 6, (
            "resume widened the campaign's share from six slots to all of them; a "
            "pause that changes the experiment it paused is not a pause")
    finally:
        repo.close()


def test_the_whole_fleet_is_divided_in_one_call(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        outcome = control.apply_allocation(repo, {"camp-a": 0, "camp-b": 12})
        assert outcome["ok"], outcome
        assert repo.campaign("camp-a")["workers_target"] == 0
        assert repo.campaign("camp-b")["workers_target"] == 12
    finally:
        repo.close()


def test_a_division_with_one_bad_share_changes_no_campaign(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        before = {name: repo.campaign(name)["workers_target"] for name in ("camp-a", "camp-b")}
        outcome = control.apply_allocation(repo, {"camp-a": 3, "camp-b": "many", "camp-x": 2})
        assert not outcome["ok"] and "nothing was changed" in outcome["problem"], outcome
        assert "camp-b" in outcome["problem"] and "camp-x" in outcome["problem"]
        assert {name: repo.campaign(name)["workers_target"] for name in ("camp-a", "camp-b")} == before, (
            "camp-a's share was not changed for a division the page reports as refused")
    finally:
        repo.close()


def test_a_fenced_pause_returns_the_leased_work_instead_of_saving_it(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        claimed = repo.claim_job("executor-fence", ("simulate",), campaigns=("camp-a",))
        assert claimed is not None, "the fixture must have work in flight to fence"
        outcome = control.pause(repo, "camp-a", fence=True)
        assert outcome["ok"] and outcome["fenced"] == 1, outcome
        row = repo.conn.execute(
            "SELECT status,lease_owner,lease_generation FROM jobs WHERE job_id='job-camp-a'"
        ).fetchone()
        assert row["status"] == "queued" and row["lease_owner"] is None, (
            "a fenced job must go back to its queue, not be cancelled")
        assert int(row["lease_generation"]) > int(claimed["lease_generation"]), (
            "the generation must move or a still-running child can publish into "
            "a campaign the operator has stopped")
    finally:
        repo.close()


def test_a_pause_with_chains_in_flight_says_it_is_still_pausing(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert repo.claim_job("executor-slow", ("simulate",), campaigns=("camp-a",)) is not None
        outcome = control.pause(repo, "camp-a")
        assert outcome["state"] == "pausing" and outcome["chains_running"] == 1, outcome
        assert "saving their position" in outcome["reading"]
        campaign = repo.campaign("camp-a")
        assert control.derived_state(campaign, chains_running=1) == "pausing"
        assert control.derived_state(campaign, chains_running=0) == "paused"
    finally:
        repo.close()


def test_a_pause_waits_for_the_analyses_of_finished_rungs(isolated_postgres_schema):
    from datetime import datetime, timedelta, timezone
    from graph_scale_dynamics.domain.model import utc_now
    from graph_scale_dynamics.services.api import campaign_manager
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        now = utc_now()
        later = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo.conn.execute("UPDATE jobs SET status='done',result_artifact='art-pause' WHERE job_id='job-camp-a'")
        repo.conn.execute("INSERT INTO artifacts(artifact_hash,size_bytes,media_type,producer_job,meta_json,"
                          "created_utc) VALUES(?,?,?,?,?,?)",
                          ("art-pause", 1, "application/json", "job-camp-a", "{}", now))
        repo.conn.execute(
            "INSERT INTO analysis_queue(campaign_id,input_artifact,analysis_version,candidate_id,n,seed,"
            "producer_job,status,lease_owner,lease_expires_utc,created_utc,updated_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("camp-a", "art-pause", "pause-contract-v1", "law-camp-a", 64, 0, "job-camp-a", "leased",
             "executor-analysis", later, now, now))
        control.pause(repo, "camp-a")
        row = next(r for r in campaign_manager.overview(repo)["campaigns"] if r["campaign_id"] == "camp-a")
        assert (row["state"], row["slots_held"], row["analyses_running"]) == ("pausing", 0, 1), row
        repo.conn.execute("UPDATE analysis_queue SET status='done',lease_owner=NULL WHERE campaign_id='camp-a'")
        row = next(r for r in campaign_manager.overview(repo)["campaigns"] if r["campaign_id"] == "camp-a")
        assert (row["state"], row["analyses_running"]) == ("paused", 0), row
    finally:
        repo.close()


def test_analyses_are_told_to_stop_only_once_the_chains_have_saved(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert control.analysis_stop_reason(repo, "camp-a") is None, "a running campaign's analyses run"
        assert repo.claim_job("executor-slow", ("simulate",), campaigns=("camp-a",)) is not None
        control.pause(repo, "camp-a")
        assert control.analysis_stop_reason(repo, "camp-a") is None, "a chain is still saving"
        repo.conn.execute("UPDATE jobs SET status='queued',lease_owner=NULL WHERE job_id='job-camp-a'")
        assert "chains have saved" in (control.analysis_stop_reason(repo, "camp-a") or "")
        assert control.analysis_stop_reason(repo, "camp-b") is None, "the neighbour is not paused"
    finally:
        repo.close()


def test_a_clone_can_change_the_grid_and_the_parent_keeps_its_own(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        parent = dict(SPEC, operator_whitelist=["degree_square_sum"],
                      search_policy={"kind": "blind", "grid": {"magnitudes": [1.0],
                                                               "betas": [1.0, 2.0]}})
        repo.insert_campaign("camp-grid", parent, content_hash(parent))
        cloned = control.clone_spec(repo, "camp-grid", grid={"betas": [1.0, 2.0, 4.0, 8.0]})
        assert cloned["ok"], cloned
        assert cloned["spec"]["search_policy"]["grid"]["betas"] == [1.0, 2.0, 4.0, 8.0]
        assert cloned["spec"]["search_policy"]["grid"]["magnitudes"] == [1.0], (
            "a key the clone did not send must keep the parent's value; the page "
            "sends only what changed")
        assert repo.campaign("camp-grid")["spec"]["search_policy"]["grid"]["betas"] == [1.0, 2.0]
    finally:
        repo.close()


def test_the_change_reason_names_the_grid_change_as_well_as_the_terms(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        parent = dict(SPEC, operator_whitelist=["degree_square_sum"],
                      search_policy={"kind": "blind", "grid": {"betas": [1.0]}})
        repo.insert_campaign("camp-reason", parent, content_hash(parent))
        cloned = control.clone_spec(repo, "camp-reason",
                                    operator_whitelist=["degree_square_sum", "edge_count"],
                                    grid={"betas": [1.0, 2.0, 4.0]})
        assert "added edge_count" in cloned["suggested_reason"]
        assert "betas 1 to 3" in cloned["suggested_reason"], (
            "a clone whose only change is its grid would otherwise be recorded "
            "as changing nothing")
    finally:
        repo.close()


def test_a_grid_the_drawer_would_refuse_is_refused_at_the_clone(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        parent = dict(SPEC, operator_whitelist=["degree_square_sum"],
                      search_policy={"kind": "blind", "grid": {"betas": [1.0]}})
        repo.insert_campaign("camp-bad", parent, content_hash(parent))
        refused = control.clone_spec(repo, "camp-bad", grid={"betas": [0.0]})
        assert not refused["ok"] and "betas" in refused["problem"]
        assert control.clone_spec(repo, "camp-bad", grid=[1, 2])["ok"] is False
    finally:
        repo.close()


def test_a_clone_that_changes_nothing_still_says_so(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        cloned = control.clone_spec(repo, "camp-a")
        assert cloned["ok"] and "nothing changed" in cloned["suggested_reason"]
    finally:
        repo.close()


def _manage(repo, **body):
    from graph_scale_dynamics.services.api.campaign_manager import handle
    return handle(repo, body)


def test_a_delete_without_the_id_typed_back_removes_nothing(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a")
        payload, code = _manage(repo, action="delete", campaign_id="camp-a", confirm="yes")
        assert code == 400 and "type camp-a" in payload["error"]
        assert repo.campaign("camp-a") is not None
    finally:
        repo.close()


def test_a_running_campaign_is_never_deleted(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        payload, code = _manage(repo, action="delete", campaign_id="camp-a", confirm="camp-a")
        assert code == 409 and "pause it first" in payload["error"]
        assert repo.campaign("camp-a") is not None
    finally:
        repo.close()


def test_a_campaign_another_was_cloned_from_is_not_deleted(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        made = control.create_campaign(
            repo, control.shipped_spec(), parent_campaign_id="camp-a",
            reason="a child for the deletion guard")
        child = str(made["campaign_id"])
        control.pause(repo, "camp-a")
        payload, code = _manage(repo, action="delete", campaign_id="camp-a", confirm="camp-a")
        assert code == 409 and child in payload["error"] and "cloned from it" in payload["error"], payload
    finally:
        repo.close()


def test_a_paused_campaign_is_deleted_and_its_neighbour_is_untouched(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a")
        payload, code = _manage(repo, action="delete", campaign_id="camp-a", confirm="camp-a")
        assert code == 200 and payload["ok"], payload
        assert repo.campaign("camp-a") is None
        left = repo.conn.execute("SELECT COUNT(*) c FROM jobs WHERE campaign_id='camp-a'").fetchone()["c"]
        assert left == 0, "the campaign's jobs outlived it"
        assert repo.campaign("camp-b") is not None
        kept = repo.conn.execute("SELECT COUNT(*) c FROM jobs WHERE campaign_id='camp-b'").fetchone()["c"]
        assert kept == 1, "deleting one campaign touched another's work"
    finally:
        repo.close()


def test_a_campaign_resumed_while_its_deletion_waits_for_the_lock_is_not_deleted(isolated_postgres_schema,
                                                                                    monkeypatch):
    from contextlib import contextmanager

    from graph_scale_dynamics.operations import maintenance
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.pause(repo, "camp-a")

        @contextmanager
        def resumed_while_waiting(held_repo):
            control.resume(held_repo, "camp-a")
            yield

        monkeypatch.setattr(maintenance, "exclusive_maintenance", resumed_while_waiting)
        payload, code = _manage(repo, action="delete", campaign_id="camp-a", confirm="camp-a")
        assert code == 409 and "pause it first" in payload["error"] and "changed while" in payload["error"], payload
        assert repo.campaign("camp-a") is not None, "the guard read before the lock let a running campaign go"
    finally:
        repo.close()


def test_a_deleted_campaign_stops_being_the_reporting_focus(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        control.set_reporting_focus(repo, "camp-a")
        control.pause(repo, "camp-a")
        _manage(repo, action="delete", campaign_id="camp-a", confirm="camp-a")
        assert repo.get_flag(control.FOCUS_FLAG, "") == ""
    finally:
        repo.close()


def test_a_campaign_started_from_the_defaults_records_no_parent(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        payload, code = _manage(
            repo, action="create", parent_campaign_id="defaults",
            operator_whitelist=["edge_count", "degree_square_sum"],
            grid={"betas": [100.0], "term_counts": [2], "per_term": {
                "edge_count": {"magnitudes": [1.0], "signs": [-1], "scales": ["one"]},
                "degree_square_sum": {"magnitudes": {"min": 0.015, "max": 0.2},
                                      "signs": [1]}}})
        assert code == 200, payload
        made = repo.campaign(str(payload["campaign_id"]))
        assert made["parent_campaign_id"] is None
        assert made["spec"]["operator_whitelist"] == ["edge_count", "degree_square_sum"]
        assert made["spec"]["search_policy"]["grid"]["term_counts"] == [2]
        assert "shipped defaults" in str(made.get("change_reason") or "")
    finally:
        repo.close()


def test_the_preflight_says_what_a_clone_carries_over(isolated_postgres_schema):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        payload, code = _manage(repo, action="preflight", parent_campaign_id="defaults",
                                operator_whitelist=["edge_count", "degree_square_sum"])
        assert code == 200
        fields = {row["field"] for row in payload["inherited"]}
        assert {"ladder", "limits", "proposer", "policy", "engine"} <= fields
        assert all(row["shipped_default"] for row in payload["inherited"]), (
            "starting from the defaults, nothing carried over can differ from them")
    finally:
        repo.close()


def test_a_campaign_authored_with_a_mean_degree_window_is_frozen_with_it(isolated_postgres_schema):
    from graph_scale_dynamics.decisions.engine import Policy
    from graph_scale_dynamics.scheduling.limits import mean_degree_window
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        payload, code = _manage(repo, action="preflight", parent_campaign_id="defaults",
                                operator_whitelist=["edge_count", "degree_square_sum"],
                                mean_degree_window={"min": 1.5, "max": 32})
        assert code == 200 and payload["mean_degree_window"]["max"] == 32.0, payload
        assert payload["mean_degree_window"]["dense_cap"] == 32.0 and payload["mean_degree_window"]["armed_from_n"] == 64
        payload, code = _manage(repo, action="create", parent_campaign_id="defaults",
                                operator_whitelist=["edge_count", "degree_square_sum"],
                                mean_degree_window={"min": 1.5, "max": 32})
        assert code == 200, payload
        made = repo.campaign(str(payload["campaign_id"]))
        assert mean_degree_window(made["spec"]) == (1.5, 32.0)
        assert Policy.from_spec(made["spec"]).dense_cap == 32.0, "the engine's stop moves with the window's top"
        assert "mean-degree window 1.5 to 32 (was 0 to 16)" in str(made.get("change_reason") or "")
        refused, code = _manage(repo, action="preflight", parent_campaign_id="defaults",
                                operator_whitelist=["edge_count"], mean_degree_window={"min": 8, "max": 4})
        assert code == 400 and "above its min" in refused["error"]
    finally:
        repo.close()


def test_a_campaign_closed_while_paused_reopens_proposing(isolated_postgres_schema, monkeypatch):
    repo = _fleet(isolated_postgres_schema.dsn)
    try:
        assert not repo.campaign_extend_only("camp-a")
        assert control.pause(repo, "camp-a", fence=False)["ok"]
        assert repo.campaign_extend_only("camp-a"), "a pause stops new laws"
        repo.stop_campaign_work("camp-a")
        monkeypatch.setattr(control, "reopen_problems", lambda repo, campaign_id: [])
        found = control._campaign_or_problem
        monkeypatch.setattr(control, "_campaign_or_problem", lambda repo, campaign_id: (
            lambda campaign, problem: ({**campaign, "search_seed": 7} if campaign else campaign, problem))(
                *found(repo, campaign_id)))
        reopened = control.reopen(repo, "camp-a")
        assert reopened["ok"], reopened
        assert not repo.campaign_extend_only("camp-a"), "reopened, it proposes again"
        assert repo.get_flag(f"{control.PAUSE_MEMO_PREFIX}camp-a", "") == "", "the memo is spent"
    finally:
        repo.close()
