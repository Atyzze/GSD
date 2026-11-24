from __future__ import annotations

from graph_scale_dynamics.reporting.reset_rules_report import band, reset_sections


def _seed(n, *, at_rest=None, thresholds=None, split=None, given=None, d_s=None, whole=None):
    health = {"rung_terminal": {"classification": "AT_REST" if at_rest else "EQUILIBRATED_ACTIVE",
                                "final_multiplier": 6, "at_rest": at_rest},
              "sampling_checkpoints": [{"certificate": {"structural_thresholds": thresholds or {},
                                                        "structural_split": split or {}}}]}
    metrics = {"health": health, "meeting_reading": given or {}, "d_s": d_s or {}}
    if whole is not None:
        metrics["d_s_whole_range"] = whole
    return {"candidate_id": "law", "n": n, "seed": 0, "metrics": metrics}


def test_the_rules_the_certificate_the_wiring_and_the_windows_are_counted():
    record = {
        "counts": [{"rule": "unsettled_twice", "at_n": 16384, "c": 3}, {"rule": "unsettled", "at_n": 4096, "c": 7},
                   {"rule": "d_s_settled", "at_n": 16384, "c": 4}],
        "across": [{"candidate_id": "a", "decision_id": "d1", "at_n": 16384, "next_n": 65536, "across": "4096"}],
        "park_audits": [{"candidate_id": "b", "decision_id": "d2", "at_n": 16384, "next_n": 65536}],
        "after": [{"candidate_id": "a", "at_n": 65536, "rule": "d_s_settled", "decision_id": "d3"},
                  {"candidate_id": "b", "at_n": 65536, "rule": "unsettled_twice", "decision_id": "d4"}],
        "regime_by_rung": [{"work_kind": "simulation", "n": 64, "zero_temperature": True, "attempts": 3,
                            "laws": 1, "core_seconds": 10.0}],
        "regime_laws": [{"zero_temperature": True, "rule": "unsettled", "top_n": 64}],
    }
    rest = {"chains": {"empty": {"at_rest": True, "late_descent_share": 0.001}},
            "pairs": {"empty|given": {"reading": "different_minima"}}}
    measurements = [
        _seed(256, at_rest=rest),
        _seed(4096, thresholds={"connected_fraction": {"threshold": 0.025, "basis": "floor"},
                                "two_core_fraction": {"threshold": 0.25, "basis": "absolute"}},
              split={"connected_fraction": 0.03, "two_core_fraction": 0.1},
              given={"reading": "disagreeing_while_moving",
                    "observables": {"energy_per_node": {"agree": True}, "mean_degree": {"agree": True},
                                    "triangles_per_node": {"agree": False}}},
              d_s={"valid": False, "would_have_reported": 2.1, "diffusive_window_evidence": {"delta_aicc": 0.4}},
              whole={"whole_range_comparable": True, "whole_range_is_power_law": True}),
    ]
    sections = reset_sections(record, measurements)
    rules = sections["reset_rules"]
    assert rules["parks"]["laws_parked"] == 3 and rules["parks"]["audit_next_rung_showed"] == {"unsettled_twice": 1}
    across = rules["settled_across_a_refused_rung"]
    assert across["decisions"] == 1 and across["share"] == 0.25 and across["next_rung_showed"] == {"d_s_settled": 1}
    assert rules["zero_temperature"]["given_at_rest"] == {"different_minima": 1}
    assert rules["zero_temperature"]["by_rung"] == {"256": {"AT_REST": 1}}
    structural = rules["given_structural_thresholds"]
    assert structural["judged_by"]["connected_fraction"] == {"4096": {"floor": 1}}
    assert structural["failed_on_the_last_chunk"] == {"connected_fraction": {"floor": 1}}
    assert structural["seeds"] == 1 and structural["zero_temperature"]["seeds"] == 0
    assert rules["given_wiring"]["disagree_on_wiring_alone"] == 1
    spectral = sections["spectral_windows"]
    assert spectral["d_s_by_rung"]["4096"] == {"withheld": 1}
    assert spectral["whole_range_test"]["totals"] == {"refused now, reported on the whole range": 1}
    assert sections["compute_by_regime"]["laws"]["zero_temperature"] == 1


def test_an_empty_campaign_says_why_each_section_is_empty():
    sections = reset_sections({}, [])
    assert "no zero-temperature seed" in sections["reset_rules"]["zero_temperature"]["why"]
    assert "no analysis records the whole-range comparison" in sections["spectral_windows"]["whole_range_test"]["why"]
    assert band(0.5) == "power law ahead, refused for not winning by enough" and band(None) == "no comparison"
    assert "error" in reset_sections({"error": "boom"}, [])["reset_rules"]


def test_the_given_chain_thresholds_count_zero_temperature_apart():
    rest = {"chains": {"empty": {"at_rest": True, "late_descent_share": 0.0}}, "pairs": {"empty|given": {"reading": "same_minimum"}}}
    judged = {"largest_component_cycle_rank_density": {"threshold": 0.15, "basis": "absolute"}}
    measurements = [_seed(4096, at_rest=rest, thresholds=judged, split={"largest_component_cycle_rank_density": 0.4}),
                    _seed(4096, thresholds=judged, split={"largest_component_cycle_rank_density": 0.1})]
    structural = reset_sections({}, measurements)["reset_rules"]["given_structural_thresholds"]
    assert structural["seeds"] == 1 and structural["failed_on_the_last_chunk"] == {}
    zero = structural["zero_temperature"]
    assert zero["seeds"] == 1 and zero["failed_on_the_last_chunk"] == {"largest_component_cycle_rank_density": {"absolute": 1}}
    assert "not compared" in zero["reading"]


def test_the_second_look_and_its_parks_are_counted():
    record = {"counts": [{"rule": "second_rung", "at_n": 4096, "c": 2}, {"rule": "no_reading", "at_n": 4096, "c": 5},
                         {"rule": "no_second_rung", "at_n": 65536, "c": 1}],
              "second": [{"candidate_id": "a", "decision_id": "d1", "at_n": 4096, "next_n": 16384},
                         {"candidate_id": "b", "decision_id": "d2", "at_n": 4096, "next_n": 16384}],
              "after": [{"candidate_id": "a", "at_n": 16384, "rule": "d_s_settled", "decision_id": "d3"},
                        {"candidate_id": "b", "at_n": 16384, "rule": "unsettled_twice", "decision_id": "d4"}]}
    look = reset_sections(record, [])["reset_rules"]["second_look"]
    assert look["decisions"] == 2 and look["by_rung"] == {"4096": 2}
    assert look["next_rung_showed"] == {"d_s_settled": 1, "unsettled_twice": 1}
    assert look["parked_unread"] == {"4096": 5} and look["parked_at_the_plateau_rung"] == {"65536": 1}
