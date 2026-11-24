from __future__ import annotations

import json

import pytest

from tests.support.engines import require_rust_engine  # noqa: E402
from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.scaleflow import engine_door

gsd_engine_rs = require_rust_engine(module_level=True)

from graph_scale_dynamics.engine import engine as E  # noqa: E402
from graph_scale_dynamics.services.worker import engine_rs as bridge  # noqa: E402
from tests.scientific.test_engine_parity import LAWS, _stable, _stop_runner  # noqa: E402


@pytest.fixture
def rebuilds(monkeypatch):
    calls = []
    real = gsd_engine_rs.call

    def counting(operation, request):
        if operation == "rebuild_graph":
            calls.append(len(request["edge_list"]))
        return real(operation, request)

    monkeypatch.setattr(gsd_engine_rs, "call", counting)
    return calls


def _eager_runner():
    def eager(ctx, chain, *, stop_file=None):
        return bridge._rebuilt_now_through(bridge.the_default_door, ctx, chain, stop_file=stop_file)

    def runner(*args, **kwargs):
        return bridge.rust_chain_runner(*args, **kwargs)

    setattr(runner, engine_door.GIVEN_INITIALISER, getattr(bridge, engine_door.GIVEN_INITIALISER))
    runner.rebuild = eager
    return runner


def _envelope(result) -> str:
    return json.dumps(_stable(result), sort_keys=True, default=str)


def test_a_resumed_chunk_that_runs_both_chains_rebuilds_nothing_twice(rebuilds):
    spec = LAWS["overlaps"]
    first = engine_door.run_simulation(spec, 128, 5, target_sweeps=20, record_points=10,
                             chain_runner=bridge.rust_chain_runner)
    checkpoint = json.loads(json.dumps(first["sampling_checkpoint"], default=list))
    rebuilds.clear()
    resumed = engine_door.run_simulation(spec, 128, 5, target_sweeps=40, record_points=10,
                               resume_checkpoint=checkpoint, chain_runner=bridge.rust_chain_runner)
    assert rebuilds == [], "a graph the chain rebuilds itself was restored in full first"
    eager = engine_door.run_simulation(spec, 128, 5, target_sweeps=40, record_points=10,
                             resume_checkpoint=checkpoint, chain_runner=_eager_runner())
    assert len(rebuilds) == 2, "the eager bridge restores both chains, which is the defect measured"
    assert _envelope(resumed) == _envelope(eager)


def test_a_chain_not_run_again_is_carried_unbuilt_and_reads_the_same(tmp_path, monkeypatch, rebuilds):
    spec = LAWS["overlaps"]
    monkeypatch.setattr(E, "STOP_CHECK_SECONDS", 0.0005)
    kw = {"target_sweeps": 60, "record_points": 30}
    first = engine_door.run_simulation(spec, 256, 7, target_sweeps=20, record_points=30,
                             chain_runner=bridge.rust_chain_runner)
    stop = tmp_path / "stop"
    stop.write_text("")
    stopped = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=first["sampling_checkpoint"],
                               chain_runner=_stop_runner(bridge.rust_chain_runner, "given", stop), **kw)
    checkpoint = json.loads(json.dumps(stopped["sampling_checkpoint"], default=list))
    assert checkpoint["in_segment"]["chain"] == "given"
    rebuilds.clear()
    resumed = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=checkpoint,
                               chain_runner=bridge.rust_chain_runner, **kw)
    assert rebuilds == [], "the chain from empty finished the segment, so its checkpoint block is carried as it is"
    eager = engine_door.run_simulation(spec, 256, 7, resume_checkpoint=checkpoint, chain_runner=_eager_runner(), **kw)
    assert _envelope(resumed) == _envelope(eager)


def test_the_deferred_state_is_the_rebuilt_state_once_read():
    spec = LAWS["overlaps"]
    first = engine_door.run_simulation(spec, 128, 5, target_sweeps=20, record_points=10,
                             chain_runner=bridge.rust_chain_runner)
    seen = {}

    def capture(ctx, rng, state, energy, *args, **kwargs):
        seen["ctx"] = ctx
        raise RuntimeError("captured")

    with pytest.raises(RuntimeError, match="captured"):
        engine_door.run_simulation(spec, 128, 5, target_sweeps=40, record_points=10,
                         resume_checkpoint=first["sampling_checkpoint"], chain_runner=capture)
    chain = CL.block(first, CL.FROM_EMPTY)
    deferred = bridge.rebuild(seen["ctx"], chain)
    eager = bridge._rebuilt_now_through(bridge.the_default_door, seen["ctx"], chain)
    assert isinstance(deferred, E.GraphState)
    assert deferred.edge_list == eager.edge_list
    assert "adj" not in deferred.__dict__, "reading the edge list built the graph"
    assert [sorted(a) for a in deferred.adj] == [sorted(a) for a in eager.adj]
    assert deferred.ledgers == eager.ledgers and deferred.edges == eager.edges
    assert deferred.structural_summary_cache == eager.structural_summary_cache
    with pytest.raises(AttributeError):
        deferred.not_an_attribute  # noqa: B018


def test_a_restore_asked_to_stop_stops_before_the_chain_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "STOP_CHECK_SECONDS", 0.0)
    spec = LAWS["overlaps"]
    first = engine_door.run_simulation(spec, 256, 7, target_sweeps=20, record_points=10,
                             chain_runner=bridge.rust_chain_runner)
    assert len(CL.edges(first, CL.FROM_EMPTY)) > E.REBUILD_CLOCK_EDGES, "the rebuild must reach a check"
    stop = tmp_path / "stop"
    stop.write_text("")
    with pytest.raises(E.RestoreInterrupted) as stopped:
        engine_door.run_simulation(spec, 256, 7, target_sweeps=40, record_points=10, stop_file=str(stop),
                         resume_checkpoint=first["sampling_checkpoint"], chain_runner=bridge.rust_chain_runner)
    assert stopped.value.reason == "stop_requested"
