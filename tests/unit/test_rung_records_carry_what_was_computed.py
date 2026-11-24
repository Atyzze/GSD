from __future__ import annotations

from graph_scale_dynamics.scaleflow.flow import rung_summary, transition_record


def _seed(flag, *, split=None, withheld=None, census_diameter=10, gap=0.1):
    metrics = {"log_diameter_flag": flag,
               "d_s": ({"valid": False, "refusal": "NO_DIFFUSIVE_WINDOW", "would_have_reported": withheld}
                       if withheld is not None else {"valid": True, "d_s": 2.0, "se": 0.1}),
               "health": {"equilibration": {"structural_split": split or {"connected_fraction": 0.01}},
                          "sampling_checkpoints": [{"certificate": {"structural_limits": {
                              "connected_fraction": 0.25}}}]},
               "census": {"empty": {"largest_component": {"size": 100, "cycle_rank": 3,
                                                            "diameter": {"lower_bound": census_diameter,
                                                                         "upper_bound": 2 * census_diameter},
                                                            "spectral_gap": {"value": gap}},
                                      "components": {"count": 2}, "cliques": {"triangles": 4, "largest_clique": 3},
                                      "squares": 1, "assortativity": -0.1, "k_core": {"degeneracy": 2}}},
               "couplings": {"n": 1024, "terms": []}}
    return metrics


def test_the_flags_third_state_is_counted_apart():
    summary = rung_summary([_seed(True), _seed(False), _seed(None), _seed(None)])
    assert (summary["log_diameter_flags"], summary["log_diameter_false"], summary["log_diameter_unknown"]) == (1, 1, 2)


def test_withheld_values_are_kept_with_their_reason():
    summary = rung_summary([_seed(True, withheld=5.5), _seed(True, withheld=6.5), _seed(True)])
    assert summary["withheld"]["d_s"] == {"values": [5.5, 6.5], "mean": 6.0, "seeds": 2,
                                          "reasons": {"NO_DIFFUSIVE_WINDOW": 2}}


def test_each_given_chain_observable_is_kept_per_seed_with_its_spread_and_limit():
    summary = rung_summary([_seed(True, split={"connected_fraction": 0.02}),
                            _seed(True, split={"connected_fraction": 0.04})])
    record = summary["equilibration_structural_split"]["connected_fraction"]
    assert record["per_seed"] == [0.02, 0.04] and record["max"] == 0.04 and record["limit"] == 0.25
    assert abs(record["seed_sd"] - 0.014142) < 1e-5


def test_the_census_is_summarised_and_the_couplings_carried():
    summary = rung_summary([_seed(True, census_diameter=10), _seed(True, census_diameter=12)])
    assert summary["census"]["largest_component_diameter"]["mean"] == 11.0
    assert summary["census"]["spectral_gap"]["mean"] == 0.1
    assert summary["couplings"]["n"] == 1024


def test_a_transition_reads_d_eff_off_the_uncapped_diameter_and_says_why_a_value_is_missing():
    small = rung_summary([_seed(True, census_diameter=10)] * 3)
    large = rung_summary([_seed(True, census_diameter=20)] * 3)
    small["distance_window_truncated_fraction"] = 1.0
    record = transition_record(1024, small, 4096, large)
    assert record["d_eff"]["diameter"] is None
    assert record["d_eff_reasons"]["diameter"] == "a sampled BFS stopped at its radius cap"
    assert abs(record["d_eff"]["census_diameter"] - 2.0) < 1e-9, "x4 nodes over x2 diameter"
