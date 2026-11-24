from __future__ import annotations

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine
from graph_scale_dynamics.scaleflow import engine_door

LAW = {"dsl_version": 1, "init": "empty",
       "dynamics": {"kind": "equilibrium", "beta": 2.0, "sweeps": 40,
                    "move_mix": {"add": 0.425, "delete": 0.425, "swap": 0.15}},
       "terms": [{"op": "degree_anchor", "params": {"k": 4}, "coeff": {"c0": 1.0, "scale": "one"}},
                 {"op": "triangle_count", "params": {}, "coeff": {"c0": -0.5, "scale": "one"}}]}


def _run(**kwargs):
    return engine_door.run_simulation(LAW, 256, 7, record_points=32, **kwargs)


def test_every_chain_enforces_the_mean_degree_cap_and_nothing_else_stops_it():
    seen = {}
    real_run_chain = engine.run_chain

    def spy(ctx, rng, state, energy, points, **kw):
        seen.setdefault("calls", []).append({"enforce_limits": kw.get("enforce_limits", False),
                                             "keys": sorted(kw)})
        return real_run_chain(ctx, rng, state, energy, points, **kw)

    engine.run_chain = spy
    try:
        envelope = _run()
    finally:
        engine.run_chain = real_run_chain
    declared, given = seen["calls"][0], seen["calls"][1]
    assert declared["enforce_limits"] is True and given["enforce_limits"] is True, (
        "the declared chain and the given chain enforce the mean-degree cap, from a start clamped to it")
    assert not [key for call in seen["calls"] for key in call["keys"] if "deadline" in key]
    assert CL.record(envelope, CL.GIVEN)["termination"] is None, "an unhurried control run stops on nothing"


@pytest.mark.parametrize("runner_module", ["graph_scale_dynamics.services.worker.engine_rs"])
def test_the_rust_runner_takes_the_same_one_flag(runner_module):
    import importlib
    import inspect
    runner = importlib.import_module(runner_module).rust_chain_runner
    parameters = inspect.signature(runner).parameters
    assert parameters["enforce_limits"].default is False
    assert not [name for name in parameters if "deadline" in name]
