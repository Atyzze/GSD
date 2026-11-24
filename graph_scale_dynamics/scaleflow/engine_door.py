from __future__ import annotations

from graph_scale_dynamics.engine import chains as _chains
from graph_scale_dynamics.engine import engine as _engine

RestoreInterrupted = _engine.RestoreInterrupted
START_KERNELS = _engine.START_KERNELS
GIVEN_START_MEAN_DEGREE = _engine.GIVEN_START_MEAN_DEGREE
given_start_edges = _engine.given_start_edges
given_start_name = _engine.given_start_name
declared_given = _engine.declared_given
GIVEN_INITIALISER = "init_random_graph"
CHAIN_NAMES = _chains.RESERVED
run_simulation = _engine.run_simulation


def simulate_of(engine: str, door: str | None = None):
    from graph_scale_dynamics.services.worker import engine_registry
    return engine_registry.simulate_of(engine, door)
