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
    assert [row["candidate_id"][0] for row in top] == ["a", "c", "e", "b", "d"], (
        "a scored law whose chain from empty read nothing reaches the top list, at zero temperature too")
    listed = {row["candidate_id"][0]: row for row in top}
    assert listed["c"]["regime"] == "zero_temperature"
    assert listed["c"]["landscape_band"] == NO_READING_FROM_EMPTY
    assert listed["c"]["law_score"]["score"] == 17


def test_a_refused_law_without_a_score_takes_only_a_place_left_empty_and_the_list_keeps_its_length():
    refused = [_refused(f"{i:064d}", 0) for i in range(150)] + [_refused("f" * 64, 9)]
    deepest = {f"{i:064d}": 1024 * (1 + i % 3) for i in range(150)}
    top = top_candidates_of([], refused, deepest, limit=100)
    assert len(top) == 100 and top[0]["candidate_id"] == "f" * 64
    assert [deepest[row["candidate_id"]] for row in top[1:4]] == [3072, 3072, 3072], "the deepest first"
    many = [_refused(f"{i:064d}", 17) for i in range(150)]
    assert len(top_candidates_of([], many + refused, {})) == 100
    assert all(row["law_score"]["score"] == 17 for row in top_candidates_of([], many + refused, {}))


def test_a_campaign_of_five_laws_lists_all_five_its_negative_controls_last():
    measured = [_measured("a" * 64, 0)]
    refused = [_refused("p" * 64, 9), _refused("n" * 64, 0), _refused("q" * 64, 1), _refused("m" * 64, 0)]
    deepest = {cid * 64: 65536 for cid in "apnqm"}
    top = top_candidates_of(measured, refused, deepest)
    assert [row["candidate_id"][0] for row in top] == ["p", "q", "a", "m", "n"], (
        "every law of a small campaign is listed, a law that reads nothing and scores 0 after every other")
    assert top[-1]["landscape_band"] == NO_READING_FROM_EMPTY and top[-1]["law_score"]["score"] == 0


def test_a_listed_law_without_a_reading_carries_every_field_the_card_reads():
    row = scored_refusal(_refused("c" * 64, 17))
    for key in ("candidate_id", "state", "law", "ensemble_code", "terms", "regime", "law_dynamics", "mean_degree",
                "limit_hits", "law_score", "d_s_estimate", "d_v_estimate", "d_b_estimate", "d_w_estimate",
                "stability_contracting_probes", "stability_contracting_tier"):
        assert key in row, key
    assert row["d_s_estimate"] is None and row["stability_contracting_probes"] == []
