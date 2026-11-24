from __future__ import annotations

from graph_scale_dynamics.research.survey_reports import build_hang_autopsy


def _metrics(from_empty_accepted, from_empty_s, given_s, given_degree):
    return {"health": {"activity": {"accepted_topology_changes_per_node_cumulative": from_empty_accepted}},
            "chain_mixing": {"chain_seconds": {"empty_chain_seconds": from_empty_s, "given_chain_seconds": given_s},
                             "given": {"mean_degree": {"halves": [{"mean": given_degree - 1}, {"mean": given_degree}]}}}}


def _law(cid, terms, beta):
    return {"candidate_id": cid, "spec": {"terms": [{"op": op, "coeff": {"c0": c0}} for op, c0 in terms],
                                          "dynamics": {"beta": beta}}}


def test_the_frozen_from_empty_busy_given_corner_is_counted_and_located():
    snapshot = {
        "candidates": [_law("g133", [("degree_cube_sum", -0.05), ("degree_square_sum", 1.0),
                                     ("triangle_edge_overlap", -0.05)], 100),
                       _law("ordinary", [("edge_count", 0.5)], 1)],
        "measurements": [{"candidate_id": "g133", "n": n, "seed": s, "metrics": _metrics(0.0, 0.3, 40.0, 17.5)}
                         for n in (256, 1024) for s in range(3)]
                        + [{"candidate_id": "ordinary", "n": 1024, "seed": s, "metrics": _metrics(2.1, 1.0, 1.0, 4.0)}
                           for s in range(3)],
        "rung_spend": [{"candidate_id": "g133", "n": 256, "core_seconds": 6.0, "interrupted_seconds": 0.0},
                       {"candidate_id": "g133", "n": 1024, "core_seconds": 114.0, "interrupted_seconds": 0.0},
                       {"candidate_id": "g133", "n": 4096, "core_seconds": 0.0, "interrupted_seconds": 9959.0},
                       {"candidate_id": "ordinary", "n": 1024, "core_seconds": 30.0, "interrupted_seconds": 0.0}],
    }
    body = build_hang_autopsy(snapshot)
    corner = body["frozen_from_empty_busy_given"]
    assert (corner["rungs"], corner["laws"], corner["laws_in_campaign"]) == (2, 1, 2)
    assert corner["rungs_by_n"] == {256: 1, 1024: 1}
    assert corner["law_core_seconds"] == 120.0 and corner["interrupted_core_seconds"] == 9959.0
    assert corner["law_list"][0]["rungs"][1]["given_late_mean_degree_max"] == 17.5
    terms = {row["term"]: row for row in corner["term_signatures"]}
    assert terms["degree_cube_sum:-"]["share_of_these_laws"] == 1.0
    assert terms["degree_cube_sum:-"]["share_of_all_laws"] == 0.5
    assert body["interrupted_core_seconds_total"] == 9959.0
    assert next(r for r in body["ranked"] if r["candidate_id"] == "g133")["interrupted_core_seconds"] == 9959.0


def test_a_rung_with_one_moving_chain_from_empty_seed_is_not_counted():
    snapshot = {
        "candidates": [_law("mixed", [("wedge_count", -0.1)], 5)],
        "measurements": [{"candidate_id": "mixed", "n": 256, "seed": 0, "metrics": _metrics(0.0, 0.1, 5.0, 9.0)},
                         {"candidate_id": "mixed", "n": 256, "seed": 1, "metrics": _metrics(0.4, 0.1, 5.0, 9.0)}],
        "rung_spend": [{"candidate_id": "mixed", "n": 256, "core_seconds": 10.0, "interrupted_seconds": 0.0}],
    }
    assert build_hang_autopsy(snapshot)["frozen_from_empty_busy_given"]["rungs"] == 0
