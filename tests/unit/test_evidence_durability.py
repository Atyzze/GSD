from __future__ import annotations

from tests.support.doubles import Cursor, bare_repo, RollbackCapable

from graph_scale_dynamics.research.proposal_intelligence import candidate_family


def _spec(coefficient: float) -> dict:
    return {
        "init": "empty",
        "terms": [
            {"op": "edge_count", "params": {},
             "coeff": {"c0": coefficient, "scale": "log_N"}},
            {"op": "degree_anchor", "params": {"k": 3},
             "coeff": {"c0": 0.5, "scale": "one"}},
        ],
        "dynamics": {"kind": "equilibrium", "move_mix": {"add": 0.5, "delete": 0.5},
                     "sweeps": 30},
    }


def test_candidate_family_ignores_coefficients_but_preserves_structure():
    left = candidate_family(_spec(0.2))
    right = candidate_family(_spec(0.9))
    assert left == right
    changed = _spec(0.2)
    changed["terms"].append({"op": "triangle_count", "params": {},
                             "coeff": {"c0": 1.0, "scale": "one"}})
    assert candidate_family(changed)[0] != left[0]


class _EvidenceConnection(RollbackCapable):
    def __init__(self, *, current_count=2, current_newest="2026-01-01T00:00:00Z"):
        self.in_transaction = False
        self.current_count = current_count
        self.current_newest = current_newest
        self.calls = []

    def execute(self, sql, args=()):
        self.calls.append((sql, tuple(args)))
        if sql == "BEGIN":
            self.in_transaction = True
            return Cursor()
        if sql in ("COMMIT", "ROLLBACK"):
            self.in_transaction = False
            return Cursor()
        if sql.startswith("SELECT 1 FROM campaign_candidates"):
            return Cursor({"?column?": 1})
        if sql.startswith("SELECT 1 FROM candidate_evidence_rebuilds"):
            return Cursor({"?column?": 1})
        if sql.startswith("SELECT COUNT(*) c,COALESCE(MAX(created_utc)"):
            return Cursor({"c": self.current_count, "newest": self.current_newest})
        return Cursor(rowcount=1)


def test_evidence_rebuild_publication_is_one_revision_fenced_transaction():
    conn = _EvidenceConnection()
    repo = bare_repo(conn)
    result = repo.complete_candidate_evidence_rebuild(
        campaign_id="campaign", candidate_id="candidate", analysis_version="analysis-v",
        owner="executor", claim_token="token", measurement_count=2,
        newest_measurement_utc="2026-01-01T00:00:00Z",
        summaries={256: {"seeds": 2}}, transitions=[(256, 1024, {"delta": 1})],
        diagnostics={256: {"contract": "rung-chain-mixing-1"}},
    )
    assert result == "done"
    statements = [sql for sql, _ in conn.calls]
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
    summary_index = next(i for i, sql in enumerate(statements)
                         if sql.startswith("INSERT INTO rung_summaries"))
    revision_index = next(i for i, sql in enumerate(statements)
                          if sql.startswith("UPDATE candidate_evidence_rebuilds SET status='done'"))
    event_sql = [(i, args) for i, (sql, args) in enumerate(conn.calls)
                 if sql.startswith("INSERT INTO events")]
    ready_index = next(i for i, args in event_sql if args[0] == "analysis_ready")
    assert summary_index < revision_index < ready_index < len(statements) - 1

    diagnostics_index = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO rung_diagnostics"))
    assert 0 < diagnostics_index < revision_index
    for index, args in event_sql:
        assert 0 < index < len(statements) - 1, f"{args[0]} escaped the transaction"


def test_evidence_rebuild_rejects_stale_measurement_snapshot():
    conn = _EvidenceConnection(current_count=3)
    repo = bare_repo(conn)
    result = repo.complete_candidate_evidence_rebuild(
        campaign_id="campaign", candidate_id="candidate", analysis_version="analysis-v",
        owner="executor", claim_token="token", measurement_count=2,
        newest_measurement_utc="2026-01-01T00:00:00Z",
        summaries={256: {"seeds": 2}}, transitions=[],
    )
    assert result == "stale"
    statements = [sql for sql, _ in conn.calls]
    assert statements[-1] == "ROLLBACK"
    assert not any(sql.startswith("INSERT INTO rung_summaries") for sql in statements)


def test_summary_contract_change_requeues_derived_evidence_atomically_and_counts_unique_records():
    from graph_scale_dynamics.db.repo import Repo
    from graph_scale_dynamics.domain.model import EVIDENCE_SUMMARY_CONTRACT

    key = {"campaign_id": "campaign", "candidate_id": "candidate",
           "analysis_version": "analysis-3.0.0"}

    class ReturningCursor(Cursor):
        def __init__(self, rows):
            super().__init__(rowcount=len(rows))
            self.rows = rows

        def fetchall(self):
            return list(self.rows)

    class Conn(RollbackCapable):
        def __init__(self):
            self.calls = []
            self.in_transaction = False

        def execute(self, sql, args=()):
            self.calls.append((sql, tuple(args)))
            if sql == "BEGIN":
                self.in_transaction = True
                return ReturningCursor([])
            if sql in ("COMMIT", "ROLLBACK"):
                self.in_transaction = False
                return ReturningCursor([])
            return ReturningCursor([key])

    conn = Conn()
    repo = object.__new__(Repo)
    repo.conn = conn
    repo.backend = "postgresql"
    repo._closed = False
    changed = repo.ensure_candidate_evidence_rebuilds("analysis-3.0.0")
    assert changed == 1
    statements = [sql for sql, _ in conn.calls]
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
    stale_sql, stale_args = conn.calls[1]
    assert "summary_json::jsonb" in stale_sql
    assert "summary_contract" in stale_sql
    assert "RETURNING r.campaign_id" in stale_sql
    assert EVIDENCE_SUMMARY_CONTRACT in stale_args
    assert "RETURNING campaign_id" in conn.calls[2][0]


def test_summary_contract_reconciliation_rolls_back_as_one_transaction_on_failure():
    from graph_scale_dynamics.db.repo import Repo

    class Conn(RollbackCapable):
        def __init__(self):
            self.calls = []
            self.in_transaction = False

        def execute(self, sql, args=()):
            self.calls.append((sql, tuple(args)))
            if sql == "BEGIN":
                self.in_transaction = True
                return Cursor(rowcount=0)
            if sql == "ROLLBACK":
                self.in_transaction = False
                return Cursor(rowcount=0)
            if sql.startswith("UPDATE candidate_evidence_rebuilds"):
                raise RuntimeError("synthetic reconciliation failure")
            return Cursor(rowcount=0)

    conn = Conn()
    repo = object.__new__(Repo)
    repo.conn = conn
    repo.backend = "postgresql"
    repo._closed = False
    import pytest
    with pytest.raises(RuntimeError, match="synthetic reconciliation failure"):
        repo.ensure_candidate_evidence_rebuilds("analysis-3.0.0")
    assert [sql for sql, _ in conn.calls] == [
        "BEGIN", conn.calls[1][0], "ROLLBACK"
    ]
    assert conn.in_transaction is False
