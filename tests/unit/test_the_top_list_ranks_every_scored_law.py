from __future__ import annotations

from graph_scale_dynamics.services.api.landscape_worker import (
    NO_READING_FROM_EMPTY, scored_refusal, top_candidates_of)


def _score(score: int, to_n: int | None = 65536) -> dict:
    return {"by": "lattice" if score else None, "chain": "tesseract" if score else None, "score": score,
            "to_n": to_n if score else None, "top_n": 65536}


def _measured(cid: str, score: int) -> dict:
    return {"candidate_id": cid, "regime": "equilibrium", "law_score": _score(score), "d_s_estimate": 1.0,
            "landscape_band": "flowing"}


def _refused(cid: str, score: int, regime: str = "zero_temperature") -> dict:
    return {"candidate_id": cid, "law_score": _score(score), "state": "DONE", "law": "a law", "terms": [],
            "regime": regime, "law_dynamics": {"regime": regime}, "ensemble_code": "G-1", "measured_rungs": 6,
            "unfiltered": False, "mean_degree": 8.0, "limit_hits": [], "top_classification": None}


def test_a_law_a_lattice_built_is_listed_though_its_chain_from_empty_reads_nothing():
    measured = [_measured("a" * 64, 17), _measured("b" * 64, 0)]
    refused = [_refused("c" * 64, 17), _refused("d" * 64, 0), _refused("e" * 64, 13)]
    deepest = {cid: 65536 for cid in ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)}
    top = top_candidates_of(measured, refused, deepest)
    assert [row["candidate_id"][0] for row in top] == ["a", "c", "e", "b"], (
        "a scored law whose chain from empty read nothing reaches the top list, at zero temperature too")
    listed = {row["candidate_id"][0]: row for row in top}
    assert listed["c"]["regime"] == "zero_temperature"
    assert listed["c"]["landscape_band"] == NO_READING_FROM_EMPTY
    assert listed["c"]["law_score"]["score"] == 17


def test_a_refused_law_without_a_score_stays_off_the_list_and_the_list_keeps_its_length():
    refused = [_refused(f"{i:064d}", 0) for i in range(150)] + [_refused("f" * 64, 9)]
    top = top_candidates_of([], refused, {}, limit=100)
    assert [row["candidate_id"] for row in top] == ["f" * 64]
    many = [_refused(f"{i:064d}", 17) for i in range(150)]
    assert len(top_candidates_of([], many, {})) == 100


def test_a_listed_law_without_a_reading_carries_every_field_the_card_reads():
    row = scored_refusal(_refused("c" * 64, 17))
    for key in ("candidate_id", "state", "law", "ensemble_code", "terms", "regime", "law_dynamics", "mean_degree",
                "limit_hits", "law_score", "d_s_estimate", "d_v_estimate", "d_b_estimate", "d_w_estimate",
                "stability_contracting_probes", "stability_contracting_tier"):
        assert key in row, key
    assert row["d_s_estimate"] is None and row["stability_contracting_probes"] == []
