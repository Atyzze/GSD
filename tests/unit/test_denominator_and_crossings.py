from __future__ import annotations

def test_report_22_names_no_share_or_denominator_of_score_8():
    from graph_scale_dynamics.research import stability_score as S
    body = S.build_stability_report([], None)
    assert "points_available" not in body and "score_resolution" not in body["population"]
