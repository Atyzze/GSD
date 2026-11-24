from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.observability import law_score
from graph_scale_dynamics.services.api import campaign_manager as manager


@pytest.mark.parametrize("n,expected", [
    (1024, 14.0), (4096, 29.0), (16384, 43.0), (65536, 57.0), (262144, 71.0),
    (1048576, 86.0), (4194304, 100.0), (8388608, 100.0),
])
def test_a_rung_carries_the_ceiling_it_unlocks(n, expected):
    assert manager._rung_ceiling(n) == expected


def test_a_rung_below_the_first_ceiling_unlocks_nothing():
    assert manager._rung_ceiling(256) is None


def test_the_ceilings_come_from_the_score_and_are_not_retyped():
    text = open(manager.__file__, encoding="utf-8").read()
    assert "law_score.depth" in text and "SCORE_NINE" not in text
    for n in law_score.LADDER:
        assert manager._rung_ceiling(n) == round(100 * law_score.depth(n) * dict(law_score.WEIGHTS)["empty"])


def test_the_high_score_is_read_from_the_landscape_the_reporter_wrote(tmp_path):
    (tmp_path / "landscape-2.json").write_text(json.dumps({
        "generated_utc": "2026-09-20T10:00:00Z",
        "top_candidates": [{"candidate_id": "abc123", "stability_score": 100.0,
                            "law_score": {"score": 17, "by": "lattice", "chain": "honeycomb", "to_n": 65536,
                                          "top_n": 65536}},
                           {"candidate_id": "def456", "law_score": {"score": 0}}],
    }), encoding="utf-8")
    best = manager.high_score(tmp_path, "2")
    assert best["score"] == 17 and best["candidate_id"] == "abc123", "the old score is not the board's"
    assert (best["by"], best["to_n"]) == ("lattice", 65536)
    assert best["generated_utc"] == "2026-09-20T10:00:00Z"
    assert best["max"] == 100


def test_a_first_law_the_board_has_not_read_is_not_scored_yet(tmp_path):
    (tmp_path / "landscape-2.json").write_text(json.dumps({
        "top_candidates": [{"candidate_id": "abc123", "law_score": None}]}), encoding="utf-8")
    best = manager.high_score(tmp_path, "2")
    assert best["score"] is None and best["candidate_id"] == "abc123"


def test_a_campaign_with_no_landscape_yet_reads_as_no_score(tmp_path):
    assert manager.high_score(tmp_path, "2") is None
    assert manager.high_score(None, "2") is None


@pytest.mark.parametrize("body", ["not json", "{}", '{"top_candidates": []}',
                                  '{"top_candidates": [{"candidate_id": "x"}]}',
                                  '{"top_candidates": [{"candidate_id": "x", "stability_score": 63.5}]}',
                                  '{"top_candidates": [{"candidate_id": "x", "law_score": {"score": "high"}}]}',
                                  '{"top_candidates": "nonsense"}'])
def test_a_landscape_that_cannot_answer_reads_as_no_score(tmp_path, body):
    (tmp_path / "landscape-2.json").write_text(body, encoding="utf-8")
    assert manager.high_score(tmp_path, "2") is None


def test_a_campaign_id_cannot_escape_the_cache_directory(tmp_path):
    (tmp_path / "landscape-2.json").write_text(
        json.dumps({"top_candidates": [{"law_score": {"score": 1}}]}), encoding="utf-8")
    assert manager.high_score(tmp_path, "../../etc/passwd") is None
    assert manager.high_score(tmp_path, "2/../2") is None


def test_the_compute_query_is_the_one_the_system_page_uses():
    assert "FROM jobs j JOIN attempts a ON a.job_id=j.job_id" in manager._COMPUTE
    assert "unsuccessful_seconds" in manager._COMPUTE
    assert callable(manager.compute_seconds)
