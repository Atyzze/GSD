from graph_scale_dynamics.scheduling.rung_eta import extrapolated_estimate, own_rung_seconds


def test_a_law_s_time_at_a_size_is_shared_by_the_seeds_that_ran_there():
    own = own_rung_seconds([{"n": 262144, "elapsed_s": 93776.0, "seeds": 16}, {"n": 65536, "elapsed_s": 2475.0}])
    assert own == {262144: 5861.0, 65536: 825.0}, "the N-push's sixteen seeds, a base block's three"
    rough = extrapolated_estimate(own, 1048576)
    assert rough["seconds"] == 23444.0 and rough["basis"] == 262144, (
        "about 6 h 31 min a seed of 1,048,576, where 897 read 34 h 44 min")
