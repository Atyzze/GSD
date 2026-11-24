from __future__ import annotations

import pytest

from graph_scale_dynamics.db.decision_store import DecisionStore
from graph_scale_dynamics.db.repo import Repo, init_db
from graph_scale_dynamics.domain.model import content_hash
from graph_scale_dynamics.measurements.version import ANALYSIS_VERSION
from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.observability import score_board as B

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CAMPAIGN = "camp-board"
SPEC = {"terms": [{"kind": "edge_count", "coefficient": 0.3}],
        "dynamics": {"kind": "metropolis", "beta": 1.0, "sweeps": 2}}
_DIGESTS = iter(range(1, 1000))


def _law(repo, law: str, sizes: list[int]) -> None:
    if not repo.conn.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (CAMPAIGN,)).fetchone():
        campaign_spec = {"mode": "bounded", "ladder": [256, 1024, 4096], "analysis_version": ANALYSIS_VERSION}
        repo.insert_campaign(CAMPAIGN, campaign_spec, content_hash(campaign_spec))
    repo.insert_candidate(law, CAMPAIGN, SPEC, "metropolis", 1, "DISCOVERY_ACTIVE")
    for n in sizes:
        job, digest = f"job-{law}-{n}", f"{next(_DIGESTS):064d}"
        repo.insert_job(job_id=job, campaign_id=CAMPAIGN, candidate_id=law, kind="simulate", stage=f"rung_n{n}", n=n,
                        seed=1, replicate=0, spec={"candidate_spec": SPEC}, priority=1, sealed=False,
                        requested_by="608-test")
        claimed = repo.claim_job("executor-board", ("simulate",), job_id=job)
        assert claimed and repo.commit_job_result(
            job_id=job, owner="executor-board", lease_generation=claimed["lease_generation"], digest=digest, size=64,
            media_type="application/json", meta={"schema": "raw-simulation-envelope-v1"},
            analysis_version=ANALYSIS_VERSION)
        repo.conn.execute(
            "INSERT INTO measurements(campaign_id,analysis_id,candidate_id,n,seed,analysis_version,input_artifact,"
            "metrics_json,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
            (CAMPAIGN, f"an-{law}-{n}", law, n, 1, ANALYSIS_VERSION, digest, "{}", "2026-10-09T09:00:00Z"))


def _scored(value: int, to_n: int | None = None) -> dict:
    return {"score": value, "by": "lattice" if value else None, "chain": "cubic" if value else None,
            "to_n": to_n if value else None, "top_n": 4096}


def test_the_scan_reads_the_laws_from_1024_a_page_at_a_time_and_the_board_reads_back(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _law(repo, "law-a", [256, 1024])
        _law(repo, "law-b", [256])
        _law(repo, "law-c", [1024, 4096])
        _law(repo, "law-d", [4096])
        B._LAST_SCAN.clear()
        asked: list[str] = []

        def score_of(law: str) -> dict:
            asked.append(law)
            return _scored(9 if law == "law-c" else 0, 4096)

        assert B.scan(repo, CAMPAIGN, score_of, now=0.0, limit=2) == 2
        assert asked == ["law-a", "law-c"], "in id order, each law once, law-b never measured at 1,024"
        board = B.board(repo, CAMPAIGN)
        assert (board["after"], board["complete"]) == ("law-c", False)
        assert B.scan(repo, CAMPAIGN, score_of, now=100.0, limit=2) == 1 and asked[-1] == "law-d"
        board = B.board(repo, CAMPAIGN)
        assert board["complete"] and board["scores"] == {"law-c": _scored(9, 4096)}
        assert B.of(board, "law-a") == L.zero() and B.of(board, "law-b") == L.zero()
        B.keep(repo, CAMPAIGN, {"law-a": _scored(17, 65536)})
        assert B.of(B.board(repo, CAMPAIGN), "law-a") == _scored(17, 65536), "a decision's score on the board"
        assert repo.get_flag(B.FLAG_PREFIX + CAMPAIGN).startswith("{"), "kept in the campaign's control flag"
    finally:
        repo.close()


def test_a_decision_store_scores_a_law_from_its_stored_measurements(isolated_postgres_schema):
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    try:
        _law(repo, "law-low", [64, 256])
        _law(repo, "law-high", [1024, 4096])
        store = DecisionStore(repo, None, {"campaign_id": CAMPAIGN, "spec": {}})
        assert store.law_score(CAMPAIGN, "law-low") == L.zero(256), "nothing read from 1,024"
        found = store.law_score(CAMPAIGN, "law-high")
        assert set(found) == {"score", "by", "chain", "to_n", "top_n", "points", "points_of", "items", "einstein",
                              "parts", "d", "mean_degree", "kind", "kind_at_4096"} and found["score"] == 0, (
            "a law whose measurements read nothing scores 0, and the score is read on PostgreSQL's rows")
        assert found["kind"] == found["kind_at_4096"] and found["kind"] is not None, "its kind beside its score"
    finally:
        repo.close()
