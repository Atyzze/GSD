from graph_scale_dynamics.scaleflow.flow import transition_record


def test_transition_record_d_eff():
    a = {"d_V": {"mean": 2.5, "se": 0.05, "n_seeds": 2}, "mean_distance": {"mean": 4.0, "se": 0.1, "n_seeds": 2},
         "diameter": {"mean": 8.0, "se": 0.2, "n_seeds": 2}}
    b = {"d_V": {"mean": 2.8, "se": 0.05, "n_seeds": 2}, "mean_distance": {"mean": 5.65, "se": 0.1, "n_seeds": 2},
         "diameter": {"mean": 11.3, "se": 0.2, "n_seeds": 2}}
    record = transition_record(1024, a, 4096, b)
    assert abs(record["d_eff"]["mean_distance"] - 4.0) < 0.15
    assert record["metric_deltas"]["d_V"]["delta"] > 0
