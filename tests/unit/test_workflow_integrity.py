from __future__ import annotations

from tests.support.doubles import Cursor, bare_repo, RollbackCapable

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.services.analyzer.child import main as analyzer_child_main
from graph_scale_dynamics.services.controller.main import campaign_complete
from graph_scale_dynamics.domain.model import CandidateState


class TerminalConnection(RollbackCapable):
    def __init__(self):
        self.in_transaction = False
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, args=()):
        args = tuple(args)
        self.calls.append((sql, args))
        if sql == "BEGIN":
            self.in_transaction = True
            return Cursor(rowcount=1)
        if sql in ("COMMIT", "ROLLBACK"):
            self.in_transaction = False
            return Cursor(rowcount=1)
        if sql.startswith("SELECT state FROM campaign_candidates"):
            return Cursor({"state": CandidateState.DISCOVERY_ACTIVE.value})
        if sql.startswith("UPDATE campaign_candidates"):
            return Cursor(rowcount=1)
        if sql.startswith("UPDATE jobs SET status='cancelled'"):
            return Cursor(rowcount=2)
        if sql.startswith("UPDATE analysis_queue SET status='cancelled'"):
            return Cursor(rowcount=3)
        return Cursor(rowcount=1)


def test_terminalization_fences_simulation_and_analysis_work_atomically():
    conn = TerminalConnection()
    repo = bare_repo(conn)

    result = repo.terminalize_candidate(
        "campaign-1", "candidate-1", CandidateState.REJECTED_SCALING.value,
        "scaling rejection",
    )

    assert result == {
        "found": True,
        "state_changed": 1,
        "jobs_cancelled": 2,
        "analysis_cancelled": 4,
        "state": CandidateState.REJECTED_SCALING.value,
    }
    statements = [sql for sql, _ in conn.calls]
    jobs_sql = next(sql for sql in statements if sql.startswith("UPDATE jobs SET status='cancelled'"))
    assert "lease_generation=lease_generation+CASE WHEN status='leased'" in jobs_sql
    assert any(sql.startswith("UPDATE analysis_queue SET status='cancelled'")
               for sql in statements)
    assert any(sql.startswith("UPDATE candidate_evidence_rebuilds SET status='cancelled'")
               for sql in statements)
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"


class AnalysisFailureConnection(RollbackCapable):
    def __init__(self, *, attempts: int, max_attempts: int):
        self.in_transaction = False
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, args=()):
        args = tuple(args)
        self.calls.append((sql, args))
        if sql == "BEGIN":
            self.in_transaction = True
            return Cursor(rowcount=1)
        if sql in ("COMMIT", "ROLLBACK"):
            self.in_transaction = False
            return Cursor(rowcount=1)
        if sql.startswith("SELECT attempts,max_attempts FROM analysis_queue"):
            return Cursor({"attempts": self.attempts, "max_attempts": self.max_attempts})
        if sql.startswith("UPDATE analysis_queue SET status="):
            return Cursor(rowcount=1)
        return Cursor(rowcount=1)


def test_analysis_retry_is_bounded_and_backed_off():
    conn = AnalysisFailureConnection(attempts=1, max_attempts=3)
    repo = bare_repo(conn)
    result = repo.fail_analysis_claim(
        "campaign-1", "a" * 64, "analysis-v", "executor-1", "claim-1",
        error="temporary child crash", error_class="child_crash", retryable=True,
        terminal_topic="analysis_failed",
        terminal_payload={"candidate_id": "candidate-1", "job_id": "job-1"},
    )
    assert result is not None
    assert result["status"] == "queued"
    assert result["retry"] is True
    assert result["next_attempt_utc"] is not None
    assert not any(sql.startswith("INSERT INTO events") for sql, _ in conn.calls)


def test_deterministic_analysis_failure_is_terminal_and_published():
    conn = AnalysisFailureConnection(attempts=1, max_attempts=3)
    repo = bare_repo(conn)
    result = repo.fail_analysis_claim(
        "campaign-1", "a" * 64, "analysis-v", "executor-1", "claim-1",
        error="invalid envelope", error_class="envelope_contract:ValueError",
        retryable=False, terminal_topic="integrity_failure",
        terminal_payload={"candidate_id": "candidate-1", "job_id": "job-1"},
    )
    assert result is not None
    assert result["status"] == "failed"
    assert result["retry"] is False
    events = [(sql, args) for sql, args in conn.calls if sql.startswith("INSERT INTO events")]
    assert len(events) == 1
    payload = json.loads(events[0][1][1])
    assert payload["retry"] is False
    assert payload["error_class"].startswith("envelope_contract")


class CompletionRepo:
    def __init__(self, pending: bool):
        self.pending = pending

    def candidates(self, campaign_id):
        return [{"state": CandidateState.REJECTED_SCALING.value}]

    def campaign_pending_work(self, campaign_id):
        return self.pending


def test_campaign_completion_waits_for_analysis_queue():
    campaign = {"campaign_id": "campaign-1"}
    assert not campaign_complete(CompletionRepo(True), campaign)
    assert campaign_complete(CompletionRepo(False), campaign)


def test_analyzer_child_marks_missing_artifact_as_deterministic(tmp_path: Path):
    output = tmp_path / "result.json"
    failure = tmp_path / "failure.json"
    with pytest.raises(Exception):
        analyzer_child_main([
            str(tmp_path / "blobs"), "f" * 64, "7", "16", "job-1", "candidate-1",
            "1", str(output), str(failure),
        ])
    record = json.loads(failure.read_text())
    assert record["stage"] == "artifact_integrity"
    assert record["retryable"] is False
