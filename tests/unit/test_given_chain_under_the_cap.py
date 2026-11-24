from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.engine import engine as E
from graph_scale_dynamics.scaleflow import equilibration as eq
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import one_shot_policy
from graph_scale_dynamics.services.worker.engine_rs import rust_chain_runner
from tests.support.engines import require_rust_engine
from graph_scale_dynamics.scaleflow import engine_door

ROOT = Path(__file__).resolve().parents[2]
LAW = json.loads((ROOT / "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json").read_text())
RUNNERS = {"python": E.run_chain, "rust": rust_chain_runner}


def _given_made_dense(engine, mean_degree=24):
    calls = []

    def runner(ctx, rng, state, energy, *args, **kwargs):
        calls.append({"kwargs": kwargs, "edges_at_start": len(state.edges)})
        if len(calls) == 2:
            target = mean_degree * ctx.n // 2
            for u in range(ctx.n):
                for v in range(u + 1, ctx.n):
                    if len(state.edges) >= target:
                        break
                    if (u, v) not in state.edges:
                        deltas, delta_h = ctx.apply_edge(state, u, v, True, energy)
                        state.apply(u, v, True, deltas)
                        energy += delta_h
        return RUNNERS[engine](ctx, rng, state, energy, *args, **kwargs)
    if engine == "rust":
        setattr(runner, engine_door.GIVEN_INITIALISER, getattr(rust_chain_runner, engine_door.GIVEN_INITIALISER))
    return runner, calls


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_the_given_chain_stops_at_the_cap(engine):
    if engine == "rust":
        require_rust_engine()
    runner, calls = _given_made_dense(engine)
    envelope = engine_door.run_simulation(LAW, 64, 1, target_sweeps=4, record_points=10, mean_degree_cap=16.0,
                                chain_runner=runner)
    assert len(calls) == 2 and calls[1]["kwargs"].get("enforce_limits") is True, "the given chain runs under the cap"
    assert CL.record(envelope, CL.GIVEN)["termination"]["reason"] == "mean_degree_cap", CL.record(envelope, CL.GIVEN)["termination"]
    assert (envelope["termination"] or {}).get("reason") != "mean_degree_cap", "the chain from empty stayed in the window"


def test_a_twin_that_leaves_the_window_alone_ends_alone_and_the_twins_are_apart():
    campaign = json.loads((ROOT / "tests/fixtures/campaign_5rung_sparse_survey.json").read_text())
    policy = dict(one_shot_policy(campaign), mean_degree_cap=16.0)

    def simulate(*args, **kwargs):
        runner, _ = _given_made_dense("python")
        return engine_door.run_simulation(*args, chain_runner=runner, **kwargs)

    envelope = run_one_shot(LAW, 64, 1, one_shot=policy, initial_multiplier=1, record_points=10, simulate=simulate)
    terminal = envelope["rung_terminal"]
    assert terminal["reason"] != "mean_degree_cap" and "mean_degree_cap_chain" not in terminal, (
        "the random start's chain at the cap ends alone, as the chain from empty's does")
    assert terminal["classification"] == eq.METASTABLE_OR_NONMIXING
    assert "the given chain ended at the mean-degree cap and the chain from empty did not" in [
        f["detail"] for f in terminal["failures"]]


@pytest.mark.parametrize("engine", ["python", "rust"])
def test_the_given_chain_never_starts_above_the_cap(engine):
    if engine == "rust":
        require_rust_engine()
    """The given chain's random start is at mean degree 8; a campaign whose cap is lower starts it at the cap."""
    calls = []

    def runner(ctx, rng, state, energy, *args, **kwargs):
        calls.append(len(state.edges))
        return RUNNERS[engine](ctx, rng, state, energy, *args, **kwargs)
    if engine == "rust":
        setattr(runner, engine_door.GIVEN_INITIALISER, getattr(rust_chain_runner, engine_door.GIVEN_INITIALISER))
    engine_door.run_simulation(LAW, 64, 1, target_sweeps=2, record_points=10, mean_degree_cap=4.0, chain_runner=runner)
    if len(calls) == 2:
        assert calls[1] <= 4 * 64 // 2, f"the given chain started with {calls[1]} edges, above a cap of 4"
    engine_door.run_simulation(LAW, 64, 1, target_sweeps=2, record_points=10, mean_degree_cap=16.0, chain_runner=runner)
    assert calls[-1] == engine_door.GIVEN_START_MEAN_DEGREE * 64 // 2, "under the cap the start is unchanged, draw for draw"
