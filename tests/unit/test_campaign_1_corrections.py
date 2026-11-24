from __future__ import annotations


from graph_scale_dynamics.research.stability_score import (
    CONTROL_FAMILY_MEAN_DEGREE, CONTROL_MATCH_AMBIGUITY_MARGIN, gate_bucket_names)


def _match(candidates: dict) -> dict:
    from graph_scale_dynamics.research import stability_score as S

    result = {"candidates": candidates, "family": None, "rungs_matched": 0}
    survivors = [(name, c) for name, c in candidates.items()
                 if not c["disagreed"] and c["top_rung_compared"]
                 and c["rungs_matched"] >= S.CONTROL_MATCH_MIN_RUNGS]
    survivors.sort(key=lambda item: (item[1]["worst_deviation_over_tolerance"],
                                     -item[1]["rungs_matched"]))
    if survivors:
        best_name, best = survivors[0]
        rivals = [n for n, c in survivors[1:]
                  if c["worst_deviation_over_tolerance"]
                  - best["worst_deviation_over_tolerance"] <= CONTROL_MATCH_AMBIGUITY_MARGIN]
        result["family"] = None if rivals else best_name
        result["ambiguous_with"] = rivals
    return result


def _cand(rungs, deviation, *, disagreed=False, top=True):
    return {"rungs_matched": rungs, "worst_deviation_over_tolerance": deviation,
            "disagreed": disagreed, "top_rung_compared": top}


def test_the_campaign_1_law_is_no_longer_labelled_a_honeycomb_lattice():
    chosen = _match({
        "periodic_honeycomb_lattice": _cand(5, 0.569),
        "erdos_renyi_dense": _cand(4, 0.280),
        "erdos_renyi_mid": _cand(4, 0.708),
        "random_3_regular": _cand(4, 0.990),
        "periodic_ring": _cand(0, 0.0, disagreed=True, top=False),
    })
    assert chosen["family"] != "periodic_honeycomb_lattice", (
        "the confident wrong label is the defect this build removes")
    assert chosen["family"] is None
    assert chosen["ambiguous_with"] == ["periodic_honeycomb_lattice"]


def test_the_best_fit_wins_when_it_wins_clearly():
    chosen = _match({
        "periodic_honeycomb_lattice": _cand(5, 0.90),
        "erdos_renyi_dense": _cand(4, 0.28),
    })
    assert chosen["family"] == "erdos_renyi_dense"


def test_two_families_that_fit_alike_produce_no_label_at_all():
    chosen = _match({
        "erdos_renyi_mid": _cand(5, 0.41),
        "periodic_honeycomb_lattice": _cand(5, 0.52),
    })
    assert chosen["family"] is None
    assert chosen["ambiguous_with"] == ["periodic_honeycomb_lattice"]


def test_a_clear_winner_is_still_named():
    chosen = _match({
        "sierpinski_gasket": _cand(5, 0.09),
        "periodic_honeycomb_lattice": _cand(5, 0.88),
    })
    assert chosen["family"] == "sierpinski_gasket"
    assert chosen["ambiguous_with"] == []


def test_every_calibration_family_declares_a_mean_degree():
    from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES

    missing = [f for f in SUITE_FAMILIES if f not in CONTROL_FAMILY_MEAN_DEGREE]
    assert missing == list(SUITE_FAMILIES[17:]) and len(missing) == 10, (
        "the six families the table gained at 765 and the four of 800 are no controls of this score, which the new "
        f"score replaces: {missing}")
    assert set(CONTROL_FAMILY_MEAN_DEGREE) <= set(SUITE_FAMILIES)
    for family, degree in CONTROL_FAMILY_MEAN_DEGREE.items():
        assert degree > 0, family


def test_the_histogram_can_name_every_bucket_a_gate_can_write():
    names = set(gate_bucket_names())
    from graph_scale_dynamics.calibration.contract import SUITE_FAMILIES

    for family in SUITE_FAMILIES[:17]:
        assert f"CONTROL_{family.upper()}" in names, family
    for family in SUITE_FAMILIES[17:]:
        assert f"CONTROL_{family.upper()}" not in names, "no bucket for a family this score cannot be matched to"


def test_the_tree_families_are_declared_below_mean_degree_two():
    for family in ("uniform_random_tree", "balanced_binary_tree"):
        assert CONTROL_FAMILY_MEAN_DEGREE[family] <= 2.0


def test_erdos_renyi_densities_are_the_giant_components_not_the_requested_ones():
    assert CONTROL_FAMILY_MEAN_DEGREE["erdos_renyi_sparse"] > 2.5
    assert CONTROL_FAMILY_MEAN_DEGREE["erdos_renyi_mid"] > 3.0
    assert CONTROL_FAMILY_MEAN_DEGREE["erdos_renyi_dense"] > 4.0


def test_an_asymptote_outside_its_own_observed_range_is_refused():
    from graph_scale_dynamics.research.probe_atlas import _guarded_asymptote

    carpet = _guarded_asymptote({"asymptote": 2.911, "asymptote_gap": 1.018, "omega": 0.2},
                                [{"mean": m} for m in (1.247, 1.5, 1.808)])
    assert carpet["asymptote"] is None and carpet["asymptote_gap"] is None
    assert carpet["asymptote_refused"]["value"] == 2.911
    assert carpet["asymptote_refused"]["observed_range"] == [1.247, 1.808]

    four_d = _guarded_asymptote({"asymptote": 3.140, "asymptote_gap": -0.86, "omega": 0.3},
                                [{"mean": m} for m in (4.049, 4.3, 4.719)])
    assert four_d["asymptote"] is None
    assert four_d["asymptote_refused"] is not None


def test_a_sequence_approaching_its_limit_from_one_side_is_not_refused():
    from graph_scale_dynamics.research.probe_atlas import _guarded_asymptote

    cubic = _guarded_asymptote({"asymptote": 3.015, "asymptote_gap": 0.015, "omega": 0.3},
                               [{"mean": m} for m in (2.90, 2.95, 2.98)])
    assert cubic["asymptote"] == 3.015
    assert cubic["asymptote_refused"] is None


def test_a_family_with_no_fit_or_no_rungs_is_handled():
    from graph_scale_dynamics.research.probe_atlas import _guarded_asymptote

    assert _guarded_asymptote({}, [])["asymptote"] is None
    unverifiable = _guarded_asymptote({"asymptote": 2.0}, [])
    assert unverifiable["asymptote"] == 2.0
    assert unverifiable["asymptote_refused"] is None


def test_no_family_description_still_claims_d_s_refuses_on_dense_random_graphs():
    from graph_scale_dynamics.measurements.calibration import CALIBRATION_FAMILIES

    dense = next(f for f in CALIBRATION_FAMILIES if f["name"] == "erdos_renyi_dense")
    why = dense["why"]
    assert "stops returning anything" not in why
    assert "does NOT stop answering" in why
    assert "2.824" in why, "the description should carry the reading it corrects"
