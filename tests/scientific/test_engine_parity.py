from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.services.worker.engine_registry import (
    ENGINES, available_engines, resolve_engine, simulate_of)
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.scientific]

EVERY_OTHER_ENGINE = [(name, door) for name, engine in ENGINES.items() if not engine.reference
                      for door in engine.doors]


@pytest.fixture(params=EVERY_OTHER_ENGINE, ids=lambda found: f"{found[0]}-{found[1]}")
def other(request):
    name, door = request.param
    return simulate_of(name, door)


VOLATILE = {"resource_usage", "engine", "wall_seconds", "wall_seconds_so_far", "elapsed_seconds", "started_utc",
            "finished_utc", "timing", "seconds", "runtime_fingerprint"}


def _stable(obj):
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in sorted(obj.items()) if k not in VOLATILE}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def _term(op, c0, scale="one", **params):
    return {"op": op, "params": params, "coeff": {"c0": c0, "scale": scale}}


def _law(terms, mix=(0.45, 0.45, 0.10), sweeps=12):
    return {"dsl_version": 1, "init": "empty", "terms": terms,
            "dynamics": {"kind": "equilibrium", "beta": 1.0,
                         "move_mix": {"add": mix[0], "delete": mix[1], "swap": mix[2]},
                         "sweeps": sweeps}}


LAWS = {
    "reference": json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text()),
    "anchor": _law([_term("edge_count", 0.25, "log_N"), _term("degree_anchor", 0.3, k=8)]),
    "triangles_squares": _law([_term("edge_count", 0.4), _term("triangle_count", -0.2, "inv_log_N"),
                               _term("square_count", 0.05, "inv_N")]),
    "overlaps": _law([_term("edge_count", 0.3), _term("square_edge_overlap", 0.02),
                      _term("triangle_edge_overlap", -0.05), _term("induced_square_count", 0.01)]),
    "gradient_moments": _law([_term("degree_neighbor_gradient", 0.01, "inv_N"), _term("degree_cube_sum", 0.002),
                              _term("degree_fourth_sum", 0.0001, "inv_sqrt_N"), _term("wedge_count", -0.1),
                              _term("degree_anchor_abs", 0.2, k=4)]),
    "curvature": _law([_term("degree_anchor", 0.5, k=6), _term("ollivier_curvature", -0.05),
                       _term("triangle_count", 0.4)], mix=(0.4, 0.4, 0.2)),
    "power_scale": _law([_term("edge_count", 0.2),
                         {"op": "degree_square_sum", "params": {}, "coeff": {"c0": 0.01, "scale": "power", "p": -0.5}}]),
}


def _dynamics(law, **settings):
    law["dynamics"].update(settings)
    return law


LAWS |= {
    "local_toggle": _dynamics(_law([_term("edge_count", 0.2), _term("triangle_count", -0.3)]), locality=0.6),
    "zero_t_global": _dynamics(_law([_term("edge_count", -0.5), _term("degree_anchor", 0.2, k=4)]),
                               zero_temperature=True),
    "zero_t_local": _dynamics(_law([_term("edge_count", -1.0), _term("degree_square_sum", 0.1)]),
                              zero_temperature=True, locality=0.99),
    "cooled_global": _dynamics(_law([_term("edge_count", 0.3), _term("degree_anchor", 0.4, k=4),
                                     _term("induced_square_count", -0.2)], mix=(0.4, 0.4, 0.2)),
                               cooling={"from_beta": 0.25, "over_sweeps": 10}),
    "cooled_local": _dynamics(_law([_term("edge_count", 0.2), _term("triangle_count", -0.3)]), locality=0.6,
                              cooling={"from_beta": 0.1, "over_sweeps": 7}),
    "cooled_past_the_run": _dynamics(_law([_term("degree_anchor", 0.5, k=6), _term("ollivier_curvature", -0.05),
                                           _term("triangle_count", 0.4)], mix=(0.4, 0.4, 0.2)),
                                     cooling={"from_beta": 0.5, "over_sweeps": 1000}),
}


def test_rust_engine_is_installed():
    engines = available_engines()
    assert engines["rust"]["available"], (
        "gsd_engine_rs is not installed; run ./tools/build_engine.sh (cargo and maturin via "
        "tools/setup_host.sh or tools/prepare_environment.sh)")


@pytest.mark.parametrize("name", sorted(LAWS))
@pytest.mark.parametrize("seed", [1, 2])
def test_python_and_rust_envelopes_are_identical(name, seed, other):
    spec = LAWS[name]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    kwargs = {"target_sweeps": int(spec["dynamics"]["sweeps"]) * 2}
    a = _stable(run_py(spec, 192, seed, **kwargs))
    b = _stable(run_rs(spec, 192, seed, **kwargs))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_the_installed_engine_is_built_from_this_tree():
    from graph_scale_dynamics.services.worker.engine_registry import rust_source_version, stale_rust_engine
    assert rust_source_version() is not None
    assert stale_rust_engine() is None, stale_rust_engine()


def test_both_engines_read_the_clock_on_the_same_stride():
    import gsd_engine_rs
    from graph_scale_dynamics.engine.engine import (CLOCK_STRIDE_MAX_MOVES, CLOCK_STRIDE_START_MOVES,
                                                    next_clock_stride)
    assert gsd_engine_rs.CLOCK_STRIDE_START_MOVES == CLOCK_STRIDE_START_MOVES
    assert gsd_engine_rs.CLOCK_STRIDE_MAX_MOVES == CLOCK_STRIDE_MAX_MOVES
    for tick in (4.0, 0.2, 0.0005, 0.0):
        for stride in (1, 2, 3, 255, 256, 1000, CLOCK_STRIDE_MAX_MOVES):
            for elapsed in (0.0, 1e-6, 0.4999 * tick, 0.5 * tick, 0.75 * tick, tick, 1.0001 * tick + 1e-9,
                            9.0, 100.0):
                assert gsd_engine_rs.next_clock_stride(stride, elapsed, tick) == \
                    next_clock_stride(stride, elapsed, tick), (stride, elapsed, tick)


def test_a_stop_asked_before_the_first_move_stops_both_engines_identically(other, tmp_path, monkeypatch):
    from graph_scale_dynamics.engine import engine as engine_module
    monkeypatch.setattr(engine_module, "STOP_CHECK_SECONDS", 0.0)
    stop = tmp_path / "stop"
    stop.write_text("")
    spec = LAWS["overlaps"]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    kw = {"target_sweeps": 24, "record_points": 3, "stop_file": str(stop)}
    a = _stable(run_py(spec, 192, 4, **kw))
    b = _stable(run_rs(spec, 192, 4, **kw))
    assert a["termination"]["reason"] == "stop_requested" and a["termination"]["at_move"] == 0
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_checkpoint_started_by_python_continues_on_rust(other):
    spec = LAWS["anchor"]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    first = run_py(spec, 128, 5, target_sweeps=12)
    cp = first["sampling_checkpoint"]
    cont_py = _stable(run_py(spec, 128, 5, target_sweeps=24, resume_checkpoint=cp))
    cont_rs = _stable(run_rs(spec, 128, 5, target_sweeps=24, resume_checkpoint=cp))
    assert json.dumps(cont_py, sort_keys=True, default=str) == json.dumps(cont_rs, sort_keys=True, default=str)


@pytest.mark.parametrize("name", ["local_toggle", "zero_t_local"])
def test_a_law_with_its_own_dynamics_continues_across_engines(name, other):
    spec = LAWS[name]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    cp = run_rs(spec, 128, 6, target_sweeps=12)["sampling_checkpoint"]
    cont_py = _stable(run_py(spec, 128, 6, target_sweeps=24, resume_checkpoint=cp))
    cont_rs = _stable(run_rs(spec, 128, 6, target_sweeps=24, resume_checkpoint=cp))
    assert json.dumps(cont_py, sort_keys=True, default=str) == json.dumps(cont_rs, sort_keys=True, default=str)


def test_mean_degree_cap_terminates_identically(other):
    spec = LAWS["triangles_squares"]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    kw = {"target_sweeps": 24, "mean_degree_cap": 6.0}
    a = _stable(run_py(spec, 192, 7, **kw))
    b = _stable(run_rs(spec, 192, 7, **kw))
    assert a.get("termination") and a["termination"]["reason"] == "mean_degree_cap"
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_one_shot_run_is_identical_on_both_engines_and_says_which(other):
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    from graph_scale_dynamics.services.worker.engine_registry import resolve_engine

    law = LAWS["reference"]
    policy = one_shot_policy(json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text()))
    policy = dict(policy, max_sweeps_multiplier=4)
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    a = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_py)
    b = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_rs)
    assert a.get("one_shot", {}).get("terminal_reason") or a.get("termination")
    assert json.dumps(_stable(a), sort_keys=True, default=str) == json.dumps(_stable(b), sort_keys=True, default=str)


def test_a_one_shot_run_stopped_on_one_engine_resumes_on_the_other_as_if_never_stopped(other):
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    from graph_scale_dynamics.services.worker.engine_registry import resolve_engine

    law = LAWS["reference"]
    policy = one_shot_policy(json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text()))
    policy = dict(policy, max_sweeps_multiplier=4)
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    whole = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_py)
    assert whole["rung_terminal"]["chunks"] >= 2
    states, calls = [], [0]

    class Stop(Exception):
        pass

    def stopping(*args, **kwargs):
        calls[0] += 1
        if calls[0] > 1:
            raise Stop()
        return run_py(*args, **kwargs)

    try:
        run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=stopping,
                     on_chunk=states.append)
    except Stop:
        pass
    state = json.loads(json.dumps(states[-1]))
    resumed = run_one_shot(law, 96, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_rs,
                           resume=state)
    resumed["rung_terminal"].pop("resumed")
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)


def test_child_stamps_the_engine_on_a_one_shot_envelope(tmp_path, monkeypatch):
    import json as _json
    from graph_scale_dynamics.services.worker import child

    monkeypatch.setenv("GSD_ENGINE", "rust")
    monkeypatch.setattr(child, "RUN_ENGINE", {})
    from graph_scale_dynamics.domain.version import environment_fingerprint, source_fingerprint, ROOT as PKG_ROOT
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint

    law = LAWS["reference"]
    policy = one_shot_policy_for_test()
    job = {"candidate_spec": law, "candidate_id": law_fingerprint(law), "n": 64, "seed": 1,
           "record_points": 30, "engine_version": child.ENGINE_VERSION,
           "execution_provenance": {"source_fingerprint": source_fingerprint(PKG_ROOT),
                                    "environment_fingerprint": environment_fingerprint()},
           "execution": {"sweeps_multiplier": 1, "one_shot": policy}}
    job_file = tmp_path / "job.json"
    out_file = tmp_path / "out.json"
    job_file.write_text(_json.dumps(job))
    child._run([str(job_file), str(out_file)])
    assert child.RUN_ENGINE.get("name") == "rust"
    envelope = _json.loads(out_file.read_text())
    assert envelope["engine"]["name"] == "rust"
    assert envelope["engine"]["implementation_fingerprint"].startswith("rs:")


def one_shot_policy_for_test():
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    policy = one_shot_policy(json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text()))
    return dict(policy, max_sweeps_multiplier=2)


def _stop_runner(base, which, stop_file):
    calls = [0]

    def runner(ctx, rng, state, energy, points, **kwargs):
        calls[0] += 1
        chain = "empty" if calls[0] == 1 else "given"
        kwargs["stop_file"] = str(stop_file) if chain == which else None
        return base(ctx, rng, state, energy, points, **kwargs)

    if hasattr(base, engine_door.GIVEN_INITIALISER):
        setattr(runner, engine_door.GIVEN_INITIALISER, getattr(base, engine_door.GIVEN_INITIALISER))
    return runner


def _runner(engine):
    from graph_scale_dynamics.engine.engine import run_chain
    from graph_scale_dynamics.services.worker.engine_rs import rust_chain_runner
    return rust_chain_runner if engine == "rust" else run_chain


@pytest.mark.parametrize("stop_on,resume_on", [("python", "python"), ("rust", "rust"), ("python", "rust")])
@pytest.mark.parametrize("which", ["empty", "given"])
def test_a_chain_stopped_mid_segment_resumes_to_the_rung_it_would_have_been(tmp_path, monkeypatch, stop_on,
                                                                             resume_on, which):
    from graph_scale_dynamics.engine import engine as E
    spec = LAWS["overlaps"]
    monkeypatch.setattr(E, "STOP_CHECK_SECONDS", 0.0005)
    kw = {"target_sweeps": 60, "record_points": 30}
    first = engine_door.run_simulation(spec, 256, 7, target_sweeps=20, record_points=30, chain_runner=_runner(stop_on))
    whole = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=first["sampling_checkpoint"],
                             chain_runner=_runner(resume_on), **kw)
    stop = tmp_path / "stop"
    stop.write_text("")
    stopped = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=first["sampling_checkpoint"],
                               chain_runner=_stop_runner(_runner(stop_on), which, stop), **kw)
    assert stopped.get("stopped") and stopped["termination"]["reason"] == "stop_requested", stopped.get("termination")
    segment = stopped["sampling_checkpoint"]["in_segment"]
    assert segment["chain"] == which and segment["segment_start"] == 20 * 256 < segment["next_move"] < 60 * 256
    checkpoint = json.loads(json.dumps(stopped["sampling_checkpoint"], default=list))
    resumed = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=checkpoint, chain_runner=_runner(resume_on), **kw)
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)


def test_both_engines_look_for_a_stop_on_the_same_interval():
    import gsd_engine_rs
    from graph_scale_dynamics.engine.engine import STOP_CHECK_SECONDS
    assert STOP_CHECK_SECONDS == gsd_engine_rs.STOP_CHECK_SECONDS == 4.0


def test_both_engines_rebuild_a_checkpoint_graph_identically():
    import gsd_engine_rs
    from graph_scale_dynamics.engine import engine as E
    from graph_scale_dynamics.services.worker.engine_rs import rebuild as rust_rebuild, rust_chain_runner
    assert gsd_engine_rs.REBUILD_CLOCK_EDGES == E.REBUILD_CLOCK_EDGES
    spec = LAWS["overlaps"]
    first = engine_door.run_simulation(spec, 128, 5, target_sweeps=20, record_points=10, chain_runner=rust_chain_runner)
    seen = {}

    def capture(ctx, rng, state, energy, *args, **kwargs):
        seen.setdefault("ctx", ctx)
        seen.setdefault("python", state)
        raise RuntimeError("captured")

    try:
        engine_door.run_simulation(spec, 128, 5, target_sweeps=40, record_points=10,
                         resume_checkpoint=first["sampling_checkpoint"], chain_runner=capture)
    except RuntimeError:
        pass
    python_state = seen["python"]
    rust_state = rust_rebuild(seen["ctx"], CL.block(first, CL.FROM_EMPTY))
    assert rust_state.edge_list == python_state.edge_list
    assert [sorted(a) for a in rust_state.adj] == [sorted(a) for a in python_state.adj]
    for name, value in python_state.ledgers.items():
        assert rust_state.ledgers[name] == pytest.approx(value, rel=0, abs=1e-9), name


def test_the_move_accounting_is_recorded_and_the_same_on_both_engines(other):
    run_py = resolve_engine({"engine": "python"})[1]
    run_rs = other
    law = _dynamics(_law([_term("edge_count", -0.5), _term("degree_anchor", 0.3, k=3),
                          _term("triangle_count", -0.4, "log_N")], sweeps=30), zero_temperature=True)
    py, rs = run_py(law, 128, 3), run_rs(law, 128, 3)
    for chain in ("empty", "given"):
        acc = CL.record(py, chain)["accounting"]
        assert acc == CL.record(rs, chain)["accounting"] == CL.block(py, chain)["accounting"]
        counts = acc["counts"]
        assert sum(counts.values()) > 0 and sum(acc["late"]["counts"].values()) > 0
        assert any(v for k, v in counts.items() if ".neg.accepted" in k)
        assert any(v for k, v in counts.items() if ".zero." in k)
        assert acc["last_decrease_move"] is not None
        assert sum(acc["delta_h_log2"]["proposed"].values()) == sum(counts.values())
    points = CL.trajectory(py, CL.FROM_EMPTY)
    carrying = [i for i, p in enumerate(points) if {"components", "largest_component", "triangles"} <= set(p)]
    assert carrying and carrying == list(range(0, len(points), py["trajectory_structure_stride"]))
    assert points == CL.trajectory(rs, CL.FROM_EMPTY)


def test_both_engines_bin_an_energy_change_alike():
    import gsd_engine_rs
    from graph_scale_dynamics.engine import engine as E
    values = [0.0, -0.0, 1.0, -1.0, 0.75, 1.5, 2.0 ** -45, -(2.0 ** 60), 3e-16, -7.25, 5e-324, 1e300]
    assert [E.delta_h_bin(v) for v in values] == [gsd_engine_rs.delta_h_bin(v) for v in values]
    assert E.delta_h_bin(1.5) == "+2^1" and E.delta_h_bin(-0.75) == "-2^0" and E.delta_h_bin(0.0) == "0"
    assert gsd_engine_rs.DELTA_H_BIN_LIMIT == E.DELTA_H_BIN_LIMIT


def test_both_engines_thin_structure_points_alike():
    import gsd_engine_rs
    from graph_scale_dynamics.engine import engine as E
    assert gsd_engine_rs.STRUCTURE_POINT_STRIDE == E.STRUCTURE_POINT_STRIDE
    for n in (1, 64, 262144, 262145, 1048576, 4194304):
        assert gsd_engine_rs.structure_point_stride(n) == E.structure_point_stride(n)


@pytest.mark.parametrize("name", sorted(LAWS))
@pytest.mark.parametrize("dimension, degree", [(2, 4), (3, 6)])
def test_the_given_chain_s_local_moves_are_identical_in_both_engines(name, dimension, degree, other):
    from graph_scale_dynamics.measurements import shaped_starts
    spec = LAWS[name]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    declared = {"family": shaped_starts.family(dimension, degree), "kernel": "local_walk",
                "edges": shaped_starts.build(192, dimension, degree, 1)}
    kwargs = {"target_sweeps": int(spec["dynamics"]["sweeps"]) * 2, "given_start": declared}
    a = _stable(run_py(spec, 192, 1, **kwargs))
    b = _stable(run_rs(spec, 192, 1, **kwargs))
    assert CL.record(a, CL.GIVEN)["kernel"] == "local_walk"
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


@pytest.mark.parametrize("name", ["overlaps", "zero_t_global", "cooled_past_the_run"])
def test_a_given_chain_moving_locally_continues_the_same_on_either_engine(name, other):
    from graph_scale_dynamics.measurements import shaped_starts
    spec = LAWS[name]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    family = shaped_starts.family(2, 4)
    declared = {"family": family, "kernel": "local_walk", "edges": shaped_starts.build(160, 2, 4, 3)}
    sweeps = int(spec["dynamics"]["sweeps"])
    first = run_rs(spec, 160, 3, target_sweeps=sweeps, given_start=declared)
    assert CL.block(first, CL.GIVEN)["kernel"] == "local_walk"
    going_on = {"family": family, "kernel": "local_walk"}
    a = _stable(run_py(spec, 160, 3, target_sweeps=2 * sweeps, resume_checkpoint=first["sampling_checkpoint"],
                       given_start=going_on))
    b = _stable(run_rs(spec, 160, 3, target_sweeps=2 * sweeps, resume_checkpoint=first["sampling_checkpoint"],
                       given_start=going_on))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _from_the_starts(n, seed, *, edges=True):
    from graph_scale_dynamics.measurements import random_starts
    from graph_scale_dynamics.measurements.calibration import control_family_edges
    families = {"random": random_starts.family(5.5), "honeycomb": "periodic_honeycomb_lattice",
                "cubic": "periodic_cubic_quotient", "tesseract": "periodic_tesseract_quotient"}
    built = [{"name": name, "family": family,
              **({"edges": control_family_edges(family, n, seed=seed)} if edges else {})}
             for name, family in families.items()]
    first = {key: value for key, value in built[0].items() if key != "name"}
    return first, built[1:]


@pytest.mark.parametrize("name", ["anchor", "overlaps", "zero_t_global", "cooled_global", "curvature"])
def test_every_start_s_chain_is_the_same_on_both_engines(name, other):
    spec = LAWS[name]
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    first, more = _from_the_starts(256, 1)
    kw = {"target_sweeps": int(spec["dynamics"]["sweeps"]) * 2, "given_start": first, "more_given": more,
          "mean_degree_cap": 16.0}
    a = _stable(run_py(spec, 256, 1, **kw))
    b = _stable(run_rs(spec, 256, 1, **kw))
    assert [row["start"] for row in a["chains"]] == ["empty", "given", "honeycomb", "cubic", "tesseract"]
    assert [row["start"] for row in a["sampling_checkpoint"]["chains"]] == [row["start"] for row in a["chains"]]
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _nth_chain_stops(base, which, stop_file):
    calls = [0]

    def runner(ctx, rng, state, energy, points, **kwargs):
        calls[0] += 1
        kwargs["stop_file"] = str(stop_file) if calls[0] == which else None
        return base(ctx, rng, state, energy, points, **kwargs)

    for attribute in (engine_door.GIVEN_INITIALISER, "init_declared", "rebuild"):
        if hasattr(base, attribute):
            setattr(runner, attribute, getattr(base, attribute))
    return runner


@pytest.mark.parametrize("stop_on,resume_on", [("python", "python"), ("rust", "rust"), ("python", "rust")])
@pytest.mark.parametrize("which", [1, 2, 3, 4, 5])
def test_any_of_five_chains_stopped_mid_segment_resumes_to_the_rung_it_would_have_been(tmp_path, monkeypatch,
                                                                                      stop_on, resume_on, which):
    from graph_scale_dynamics.engine import engine as E
    spec = LAWS["anchor"]
    monkeypatch.setattr(E, "STOP_CHECK_SECONDS", 0.0005)
    first, more = _from_the_starts(256, 7)
    going_on, going_more = _from_the_starts(256, 7, edges=False)
    kw = {"target_sweeps": 60, "record_points": 30, "given_start": going_on, "more_given": going_more}
    chunk = engine_door.run_simulation(spec, 256, 7, target_sweeps=20, record_points=30, chain_runner=_runner(stop_on),
                             given_start=first, more_given=more)
    checkpoint = json.loads(json.dumps(chunk["sampling_checkpoint"], default=list))
    whole = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=checkpoint, chain_runner=_runner(resume_on), **kw)
    stop = tmp_path / "stop"
    stop.write_text("")
    stopped = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=checkpoint,
                               chain_runner=_nth_chain_stops(_runner(stop_on), which, stop), **kw)
    assert stopped.get("stopped") and stopped["termination"]["reason"] == "stop_requested", stopped.get("termination")
    segment = stopped["sampling_checkpoint"]["in_segment"]
    assert segment["chain"] == ["empty", "given", "honeycomb", "cubic", "tesseract"][which - 1]
    assert segment["segment_start"] == 20 * 256 < segment["next_move"] < 60 * 256
    resumed = engine_door.run_simulation(spec, 256, 7, chain_runner=_runner(resume_on), **dict(
        kw, resume_checkpoint=json.loads(json.dumps(stopped["sampling_checkpoint"], default=list))))
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)


def _starts_policy(law, n):
    from graph_scale_dynamics.dsl.dsl import fingerprint as law_fingerprint
    from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
    spec = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    spec["sampling_contract"] = dict(spec.get("sampling_contract") or {}, given_starts=[
        {"name": "random", "family": "random_at_drawn_degree"},
        {"name": "honeycomb", "family": "periodic_honeycomb_lattice"},
        {"name": "cubic", "family": "periodic_cubic_quotient"},
        {"name": "tesseract", "family": "periodic_tesseract_quotient"}])
    policy = one_shot_policy(spec, n, law_fingerprint(law), law)
    return dict(policy, max_sweeps_multiplier=4)


def test_a_one_shot_run_from_its_starts_is_the_same_on_both_engines_and_resumes_on_either(other):
    from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
    law = LAWS["reference"]
    policy = _starts_policy(law, 256)
    assert policy["given_start"]["family"].startswith("random_mean_degree_") and "given_capped_alone" not in policy
    _, run_py, _ = resolve_engine({"engine": "python"})
    run_rs = other
    whole = run_one_shot(law, 256, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_py)
    theirs = run_one_shot(law, 256, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_rs)
    assert json.dumps(_stable(whole), sort_keys=True, default=str) == json.dumps(_stable(theirs), sort_keys=True,
                                                                                   default=str)
    assert whole["rung_terminal"]["chunks"] >= 2
    assert [given["name"] for given in whole["rung_terminal"]["given_chains"]] == ["random", "honeycomb", "cubic", "tesseract"]
    states, calls = [], [0]

    class Stop(Exception):
        pass

    def stopping(*args, **kwargs):
        calls[0] += 1
        if calls[0] > 1:
            raise Stop()
        return run_py(*args, **kwargs)

    with pytest.raises(Stop):
        run_one_shot(law, 256, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=stopping,
                     on_chunk=states.append)
    resumed = run_one_shot(law, 256, 3, one_shot=policy, initial_multiplier=1, record_points=60, simulate=run_rs,
                           resume=json.loads(json.dumps(states[-1])))
    resumed["rung_terminal"].pop("resumed")
    assert json.dumps(_stable(resumed), sort_keys=True, default=str) == json.dumps(_stable(whole), sort_keys=True,
                                                                                     default=str)
