from __future__ import annotations

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements import analysis
from graph_scale_dynamics.measurements import calibration as cal
from graph_scale_dynamics.measurements import estimators as est
from graph_scale_dynamics.measurements import known_answers as ka
from graph_scale_dynamics.measurements import walk_dimension as walk
from graph_scale_dynamics.scaleflow import engine_door


def _random_regular(n: int, k: int, seed: int):
    rng = np.random.default_rng(seed)
    stubs = np.repeat(np.arange(n), k)
    rng.shuffle(stubs)
    pairs = {(int(min(a, b)), int(max(a, b))) for a, b in zip(stubs[0::2], stubs[1::2], strict=True) if a != b}
    return n, sorted(pairs)


def _graph(n, edges):
    adj = est.build_adjacency(n, edges)
    return adj, est.largest_component(n, adj)


def test_the_tree_measures_with_one_analysis_and_no_other_can_be_asked_for():
    import inspect

    from graph_scale_dynamics.measurements import version
    assert version.ANALYSIS_VERSION == "analysis-5.3.0"
    assert sorted(name for name in vars(version) if name.isupper()) == ["ANALYSIS_VERSION", "PROBE_STREAM"]
    for function in (est.fit_dh, est.fit_ds, est._measure_graph, est.return_probability, walk.fit_walk_dimension,
                     analysis.analyze_envelope):
        assert "analysis_version" not in inspect.signature(function).parameters, function.__name__


def test_d_v_refuses_an_expander_read_through_four_radii():
    adj, comp = _graph(*_random_regular(4096, 6, 0))
    fit = est.fit_dh(est.volume_growth(adj, comp, np.random.default_rng(1)), len(comp))
    assert not fit["valid"] and fit["refusal"] == "EXPONENTIAL_GROWTH"
    assert fit["volume_growth"] == {**fit["volume_growth"], "verdict": "exponential", "radii": 4}


def test_d_v_keeps_a_lattice_read_through_four_radii():
    n, edges = cal.periodic_hypercubic_lattice_4d(5)
    adj, comp = _graph(n, edges)
    fit = est.fit_dh(est.volume_growth(adj, comp, np.random.default_rng(1)), len(comp))
    if fit.get("window"):
        assert fit["window"]["points"] >= 4
    assert fit["volume_growth"]["verdict"] in {"power", "untested"}


def test_a_chain_is_read_at_one_state_and_nothing_is_left_that_combines_several():
    assert not [name for name in vars(analysis) if "combine" in name], "5.2 reads the last state only"
    read = analysis._of_the_last_state({"valid": True, "d_V_window": 3.44, "se": 0.1, "measured_se": 0.02}, "d_V_window")
    assert (read["d_V_window"], read["se"], read["measured_se"]) == (3.44, 0.1, 0.02)
    assert read["snapshots"] == {"k": 1, "valid_k": 1, "independence_certified": False, "spread": 0.0, "values": [3.44]}
    refused = analysis._of_the_last_state({"valid": False, "refusal": "NO_SCALING_WINDOW", "reason": "test"}, "d_V_window")
    assert refused == {"valid": False, "refusal": "NO_SCALING_WINDOW", "reason": "test",
                       "snapshots": {"k": 1, "valid_k": 0}}


def test_a_rung_of_several_chunks_is_read_at_its_last_state_only():
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    from graph_scale_dynamics.services.worker import engine_rs

    def term(op, c0, scale="one", **params):
        return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}

    spec = {"dsl_version": 1, "init": "empty",
            "terms": [term("edge_count", 0.25, "log_N"), term("degree_anchor", 0.3, k=4)],
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}, "sweeps": 10}}
    from graph_scale_dynamics.operations.campaign_control import shipped_spec
    from graph_scale_dynamics.scheduling.limits import work_unit
    policy = {"contract": "one-shot-sampling-1", "max_sweeps_multiplier": 64,
              "required_consecutive_passes": 2, "work_budget": 10 ** 15, "work_unit": work_unit(shipped_spec())}
    envelope = run_one_shot(spec, 512, 3, one_shot=policy, simulate=engine_door.simulate_of("rust"))
    assert len(envelope["sampling_checkpoints"]) > 1, "the fixture must be a multi-chunk rung"
    assert "snapshots" not in CL.block(envelope, CL.FROM_EMPTY), "the engine keeps no copy of a graph"
    read, curves = analysis.analyze_envelope(envelope, seed=3)
    assert [c["move"] for c in curves["configurations"]] == ["final"]
    assert read["d_V"]["snapshots"]["k"] == read["d_s"]["snapshots"]["k"] == 1
    assert read["snapshot_selection"] == {"contract": "final-chunk-2", "configurations": 1}
    assert read["geometry_snapshot_mode"] == "final_state_only"


def test_the_d_s_error_matches_the_spread_over_estimator_seeds():
    adj, comp = _graph(*ka.periodic_square_torus(4096))
    values, errors, wide = [], [], []
    for seed in range(8):
        ret = est.return_probability(adj, comp, np.random.default_rng(1000 + seed), keep_probes=True)
        fit = est.fit_ds(ret, len(comp))
        assert fit["valid"]
        values.append(fit["d_s"])
        assert fit["se"] == fit["measured_se"] and fit["se_method"] == "bootstrap over probes"
        errors.append(fit["se"])
        wide.append(fit["analytic_se"])
    spread = float(np.std(values, ddof=1))
    assert 0.4 * spread <= float(np.median(errors)) <= 2.5 * spread
    assert float(np.median(wide)) > 4 * spread, "the analytic bound, kept beside the error, is the wide one"


def test_a_curve_without_probes_has_no_measured_error():
    adj, comp = _graph(*cal.periodic_ring(512))
    ret = est.return_probability(adj, comp, np.random.default_rng(1))
    assert "p0_per_probe" not in ret
    assert "measured_se" not in est.fit_ds(ret, len(comp))


def test_the_per_probe_matrix_is_not_kept_with_the_curves():
    n, edges = cal.periodic_square_lattice(16)
    result, curves = est._measure_graph(n, edges, np.random.default_rng(0))
    assert "p0_per_probe" not in curves["return_probability"]
    assert (result["d_s"].get("window") or {}).get("probe_error", {}).get("method") == "bootstrap over probes"


def test_d_w_refuses_a_dense_expander_with_too_few_radii():
    adj, comp = _graph(*_random_regular(4096, 12, 0))
    profile = walk.walk_displacement_profile(adj, comp, np.random.default_rng(2))
    assert not walk.fit_walk_dimension(profile)["valid"]


def test_d_w_on_a_cubic_lattice_is_near_two():
    adj, comp = _graph(*cal.periodic_cubic_lattice(24))
    read = []
    for seed in range(4):
        profile = walk.walk_displacement_profile(adj, comp, np.random.default_rng(seed))
        assert profile["equilibrium_msd"] > 0
        read.append(walk.fit_walk_dimension(profile)["walk_dimension"])
    assert abs(np.mean(read) - 2.0) < 0.15


def test_the_small_world_flag_marks_an_expander_and_not_a_lattice():
    n, edges = _random_regular(1024, 4, 0)
    flagged, _ = est._measure_graph(n, edges, np.random.default_rng(0))
    lattice, _ = est._measure_graph(*cal.periodic_square_lattice(32), np.random.default_rng(0))
    assert flagged["small_world"] is True
    assert lattice["small_world"] is False
